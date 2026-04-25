from fastapi import APIRouter

from app import __version__
from app.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "version": __version__,
        "env": settings.app_env,
        "demo_overrides_enabled": str(settings.demo_overrides_enabled),
    }
