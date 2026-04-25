"""Protected admin endpoints for hackathon convenience."""

import os
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Header
from pydantic import BaseModel, ConfigDict

from app.db import init_db
from app.logger import get_logger

router = APIRouter(prefix="/admin", tags=["admin"])
log = get_logger("admin")

_seed_lock = False


class SeedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: Literal["DESTROY_ALL_DATA"]


@router.post("/seed")
def trigger_seed(
    req: SeedRequest,
    background: BackgroundTasks,
    x_admin_secret: str = Header(...),
) -> dict:
    """Trigger a full database re-seed in the background.

    Requires:
      - Header: X-Admin-Secret matching ADMIN_SEED_SECRET env var
      - Body: {"confirm": "DESTROY_ALL_DATA"}

    Returns immediately; seeding continues in a background task.
    """
    allow = os.environ.get("ALLOW_ADMIN_SEED", "false").lower() == "true"
    if not allow:
        raise HTTPException(status_code=404, detail="Not found")

    secret = os.environ.get("ADMIN_SEED_SECRET", "")
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="ADMIN_SEED_SECRET not configured",
        )

    if x_admin_secret != secret:
        raise HTTPException(status_code=403, detail="Invalid admin secret")

    global _seed_lock
    if _seed_lock:
        raise HTTPException(status_code=409, detail="Seed already in progress")

    background.add_task(_run_seed_safe)
    return {
        "status": "accepted",
        "message": "Database re-seed started in background. Check logs.",
    }


def _run_seed_safe() -> None:
    global _seed_lock
    _seed_lock = True
    try:
        log.info("admin.seed.start")
        init_db(drop_first=True)
        from scripts.seed import seed as run_seed

        run_seed()
        log.info("admin.seed.complete")
    except Exception as exc:
        log.error("admin.seed.failed", error=str(exc))
    finally:
        _seed_lock = False
