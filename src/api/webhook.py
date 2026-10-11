"""GitHub webhook receiver."""

import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from src.config import Settings, get_settings
from src.db.models import Run
from src.db.session import get_db
from src.jobs import enqueue_run
from src.schemas import RunStatus

router = APIRouter(tags=["webhook"])

HANDLED_ISSUE_ACTIONS = {"opened", "labeled"}


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Check GitHub's X-Hub-Signature-256 header against our shared secret."""
    if not secret or not signature_header:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@router.post("/webhook/github", status_code=202)
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> dict:
    body = await request.body()

    if not verify_signature(settings.github_webhook_secret, body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    if x_github_event == "ping":
        return {"message": "pong"}

    payload = json.loads(body)

    if x_github_event == "issues" and payload.get("action") in HANDLED_ISSUE_ACTIONS:
        run = Run(
            repo_full_name=payload["repository"]["full_name"],
            issue_number=payload["issue"]["number"],
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        try:
            enqueue_run(run.id)
        except Exception as exc:
            run.status = RunStatus.FAILED.value
            db.commit()
            raise HTTPException(status_code=503, detail="Could not queue the run") from exc

        return {"accepted": True, "run_id": run.id}

    return {"ignored": True, "event": x_github_event}
