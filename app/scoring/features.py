from datetime import datetime, timedelta
from statistics import mean, stdev

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Transaction, User
from app.schemas.transfer import ScoreTransferRequest


def extract_features(req: ScoreTransferRequest, db: Session) -> dict:
    sender = _get_or_synthesise_user(db, req.sender_id, phone=None, default_mule_likelihood=0.05)
    recipient = _get_or_synthesise_user(
        db, req.recipient_id, phone=req.recipient_phone, default_mule_likelihood=0.10
    )

    prior_count = (
        db.query(Transaction)
        .filter(Transaction.sender_id == sender.id, Transaction.recipient_id == recipient.id)
        .count()
    )

    cutoff_2h = datetime.utcnow() - timedelta(hours=2)
    velocity_count = (
        db.query(func.count(func.distinct(Transaction.sender_id)))
        .filter(Transaction.recipient_id == recipient.id, Transaction.timestamp >= cutoff_2h)
        .scalar()
        or 0
    )

    user_history = [
        row[0]
        for row in db.query(Transaction.amount)
        .filter(Transaction.sender_id == sender.id)
        .limit(100)
        .all()
    ]

    amount_zscore = _zscore(req.amount, user_history) if user_history else 0.0
    new_recipient = prior_count == 0

    return {
        "recipient_mule_likelihood": float(recipient.mule_likelihood or 0.0),
        "recipient_mule_pattern_tag": recipient.mule_pattern_tag,
        "velocity_cluster_size": int(velocity_count),
        "amount_zscore": float(amount_zscore),
        "amount_raw": float(req.amount),
        "new_recipient": new_recipient,
        "prior_transfer_count": int(prior_count),
        "recipient_account_age_days": _account_age_days(recipient),
        "time_of_day_in_pattern": True,
        "user_risk_history": "clean",
    }


def _zscore(x: float, history: list[float]) -> float:
    if len(history) < 2:
        return 0.0
    m = mean(history)
    sd = stdev(history)
    if sd == 0:
        return 0.0
    return (x - m) / sd


def _account_age_days(user: User) -> int:
    if user.created_at is None:
        return 999
    return max(0, (datetime.utcnow() - user.created_at).days)


def _get_or_synthesise_user(
    db: Session, user_id: str, phone: str | None, default_mule_likelihood: float
) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user is not None:
        return user

    if phone:
        user = db.query(User).filter(User.phone == phone).first()
        if user is not None:
            return user

    return User(
        id=user_id,
        phone=phone or f"unknown-{user_id}",
        name="(unknown)",
        account_type="normal",
        mule_likelihood=default_mule_likelihood,
    )
