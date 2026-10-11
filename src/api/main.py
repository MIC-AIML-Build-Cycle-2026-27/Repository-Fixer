from fastapi import FastAPI

from src.api import health, runs, webhook
from src.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)
app.include_router(health.router)
app.include_router(webhook.router)
app.include_router(runs.router)


@app.get("/")
def root() -> dict:
    return {"service": settings.app_name, "docs": "/docs"}
