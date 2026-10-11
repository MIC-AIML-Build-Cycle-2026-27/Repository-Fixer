"""GitHub webhook receiver."""

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from src.config import Settings, get_settings
from src.db.models import Run
from src.db.session import get_db
from src.jobs import enqueue_run
from src.schemas import RunStatus

router = APIRouter(tags=["webhook"])

log = logging.getLogger(__name__)

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
        log.warning("Rejected webhook event=%r: invalid signature", x_github_event)
        raise HTTPException(status_code=401, detail="Invalid signature")

    if x_github_event == "ping":
        return {"message": "pong"}

    if x_github_event == "issues":
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON") from exc
        action = payload.get("action")
        if action not in HANDLED_ISSUE_ACTIONS:
            log.info("Ignoring issues action=%r", action)
            return {"ignored": True, "event": x_github_event}
        repo = payload.get("repository", {}).get("full_name")
        num = payload.get("issue", {}).get("number")
        if not repo or not isinstance(num, int):
            raise HTTPException(status_code=400, detail="Invalid issues payload")
        run = Run(
            repo_full_name=repo,
            issue_number=num,
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        try:
            enqueue_run(run.id)
        except Exception as exc:
            log.exception("Failed to queue run %s", run.id)
            run.status = RunStatus.FAILED.value
            try:
                db.commit()
            except Exception:
                log.exception("Failed to mark run %s as failed", run.id)
                db.rollback()
            raise HTTPException(status_code=503, detail="Could not queue the run") from exc

        return {"accepted": True, "run_id": run.id}

    log.info("Ignoring event=%r", x_github_event)
    return {"ignored": True, "event": x_github_event}