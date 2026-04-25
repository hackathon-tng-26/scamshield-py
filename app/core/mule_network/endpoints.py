from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.mule_network.service import (
    compute_mule_likelihood,
    explain_mule_score,
    get_laundering_paths,
    refresh_graph_scores,
)
from app.db import get_db
from app.schemas.mule_network import (
    ExplainabilityResponse,
    GraphRefreshResponse,
    LaunderingPathResponse,
    MuleLikelihoodScore,
)

router = APIRouter(prefix="/mule-network", tags=["Layer 3 — Mule Network Intelligence"])


@router.get("/score/{account_id}", response_model=MuleLikelihoodScore)
def score_account(account_id: str, db: Session = Depends(get_db)) -> MuleLikelihoodScore:
    """Real-time mule-likelihood score for L2 consumption."""
    result = compute_mule_likelihood(account_id, db)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    return result


@router.post("/refresh", response_model=GraphRefreshResponse)
def refresh(db: Session = Depends(get_db)) -> GraphRefreshResponse:
    """Scheduled refresh — recompute all node scores and pattern detections."""
    return refresh_graph_scores(db)


@router.get("/paths/{account_id}", response_model=list[LaunderingPathResponse])
def laundering_paths(account_id: str, db: Session = Depends(get_db)) -> list[LaunderingPathResponse]:
    """Detect money-laundering chains from account_id to off-ramps."""
    return get_laundering_paths(account_id, db)


@router.get("/explain/{account_id}", response_model=ExplainabilityResponse)
def explain(account_id: str, db: Session = Depends(get_db)) -> ExplainabilityResponse:
    """Graph-based explainability for mule-likelihood score."""
    result = explain_mule_score(account_id, db)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    return result
