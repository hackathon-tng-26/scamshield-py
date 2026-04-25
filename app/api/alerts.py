from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Transaction, User
from app.schemas.alerts import AlertEntry

router = APIRouter()


@router.get("", response_model=list[AlertEntry])
def list_alerts(
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[AlertEntry]:
    rows = (
        db.query(Transaction, User)
        .join(User, Transaction.recipient_id == User.id)
        .filter(Transaction.verdict.isnot(None))
        .order_by(desc(Transaction.timestamp))
        .limit(limit)
        .all()
    )

    return [
        AlertEntry(
            transaction_id=txn.id,
            timestamp=txn.timestamp,
            sender_id=txn.sender_id,
            recipient_id=txn.recipient_id,
            recipient_phone=recipient.phone,
            recipient_label=recipient.name,
            amount=txn.amount,
            score=txn.risk_score or 0,
            verdict=txn.verdict,  # type: ignore[arg-type]
            top_feature=txn.top_feature,
        )
        for txn, recipient in rows
    ]
