"""Layer 2 Transaction Risk Scoring endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.scoring.service import score_transfer
from app.db import get_db
from app.schemas.transfer import ScoreTransferRequest, ScoreTransferResponse

router = APIRouter(prefix="/scoring", tags=["Layer 2 — Transaction Risk Scoring"])

@router.post("/score", response_model=ScoreTransferResponse)
def score(req: ScoreTransferRequest, db: Session = Depends(get_db)) -> ScoreTransferResponse:
    return score_transfer(req, db)
