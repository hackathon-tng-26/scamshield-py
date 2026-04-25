import json
from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Transaction
from app.schemas.transfer import (
    ExecuteTransferResponse,
    ScoreTransferRequest,
    ScoreTransferResponse,
)
from app.scoring.service import score_transfer

router = APIRouter()


@router.post("/score", response_model=ScoreTransferResponse)
def score(req: ScoreTransferRequest, db: Session = Depends(get_db)) -> ScoreTransferResponse:
    return score_transfer(req, db)


@router.post("/execute", response_model=ExecuteTransferResponse)
def execute(req: ScoreTransferRequest, db: Session = Depends(get_db)) -> ExecuteTransferResponse:
    scored = score_transfer(req, db)
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
    return ExecuteTransferResponse(success=True, transaction_id=txn.id)
