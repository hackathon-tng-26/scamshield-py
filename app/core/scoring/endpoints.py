"""Layer 2 Transaction Risk Scoring endpoints."""
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.core.identity.service import is_device_in_cooldown
from app.core.scoring.service import score_transfer
from app.core.scoring.features import _get_or_synthesise_user
from app.core.oss import upload_transaction_log
from app.db import get_db
from app.models import Transaction
from app.schemas.transfer import (
    ExecuteTransferResponse,
    ScoreTransferRequest,
    ScoreTransferResponse,
)

# ---------------------------------------------------------------------------
# Public transfer router — mobile-facing API contract
# ---------------------------------------------------------------------------
transfer_router = APIRouter(tags=["transfer"])


@transfer_router.post("/score", response_model=ScoreTransferResponse)
def score(req: ScoreTransferRequest, db: Session = Depends(get_db)) -> ScoreTransferResponse:
    """Fired when user taps Continue. Returns risk score and attribution."""
    return score_transfer(req, db)


@transfer_router.post("/execute", response_model=ExecuteTransferResponse)
def execute(
    req: ScoreTransferRequest, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db)
) -> ExecuteTransferResponse:
    """Fired when user taps Send. Enforces L1 cooldown then persists transaction."""
    in_cooldown, until = is_device_in_cooldown(db, req.sender_id, req.device_fingerprint)
    if in_cooldown:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "DEVICE_COOLDOWN",
                "cooldown_until": until.isoformat() if until else None,
                "message": "This device is in security cooldown. Transfers are blocked.",
            },
        )

    scored = score_transfer(req, db)

    # Ensure sender and recipient exist in DB to prevent foreign key violations, 
    # especially when demo overrides bypass standard feature extraction
    sender = _get_or_synthesise_user(db, req.sender_id, phone=None, default_mule_likelihood=0.05)
    recipient = _get_or_synthesise_user(db, req.recipient_id, phone=req.recipient_phone, default_mule_likelihood=0.10)
    db.add(sender)
    db.add(recipient)

    txn = Transaction(
        id=scored.transaction_id or str(uuid4()),
        sender_id=req.sender_id,
        recipient_id=req.recipient_id,
        amount=req.amount,
        risk_score=scored.score,
        verdict=scored.verdict,
        feature_attribution=json.dumps([a.model_dump() for a in scored.attribution]),
        top_feature=scored.attribution[1].feature if len(scored.attribution) > 1 else None,
        device_id=req.device_fingerprint,
    )
    db.add(txn)
    db.commit()

    # Prepare data for Alibaba Cloud OSS Audit Logging
    transaction_data = {
        "transaction_id": txn.id,
        "sender_id": req.sender_id,
        "receiver_id": req.recipient_id,
        "amount": req.amount,
        "l2_score": scored.score,
        "timestamp": req.timestamp_ms,
        "risk_factors": [attr.feature for attr in scored.attribution]
    }
    
    # Trigger background async upload to OSS
    background_tasks.add_task(upload_transaction_log, transaction_data)

    return ExecuteTransferResponse(success=True, transaction_id=txn.id)


# ---------------------------------------------------------------------------
# Internal scoring router — direct L2 access for debugging / BO dashboard
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/scoring", tags=["Layer 2 — Transaction Risk Scoring"])


@router.post("/score", response_model=ScoreTransferResponse)
def debug_score(req: ScoreTransferRequest, db: Session = Depends(get_db)) -> ScoreTransferResponse:
    """Direct Layer 2 scoring endpoint (same logic, different path)."""
    return score_transfer(req, db)
