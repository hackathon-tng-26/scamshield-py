"""Optional — train a GBDT on seeded transactions. Rules-only scoring works fine without this."""

from __future__ import annotations

import pickle
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean, stdev

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.logger import get_logger
from app.models import Transaction, User

log = get_logger("train")


FEATURE_ORDER: list[str] = [
    "recipient_mule_likelihood",
    "velocity_cluster_size",
    "amount_zscore",
    "new_recipient",
    "recipient_account_age_days",
]


def main() -> None:
    try:
        from sklearn.ensemble import GradientBoostingClassifier
    except ImportError:
        log.error("train.missing_sklearn", hint="pip install scikit-learn")
        sys.exit(1)

    with SessionLocal() as db:
        x, y = _build_training_set(db)

    if len(y) < 50:
        log.error("train.insufficient_data", rows=len(y), needed=50)
        sys.exit(1)

    log.info("train.begin", rows=len(y), features=FEATURE_ORDER)
    model = GradientBoostingClassifier(n_estimators=80, max_depth=3, random_state=42)
    model.fit(x, y)
    log.info("train.fit.done", classes=list(model.classes_))

    from app.scoring.model import ModelBundle

    bundle = ModelBundle(estimator=model, feature_order=FEATURE_ORDER)
    out_path = "./data/scorer.pkl"
    with open(out_path, "wb") as f:
        pickle.dump(bundle, f)
    log.info("train.saved", path=out_path)


def _build_training_set(db: Session) -> tuple[list[list[float]], list[int]]:
    history_by_sender: dict[str, list[float]] = defaultdict(list)
    for txn in db.query(Transaction).order_by(Transaction.timestamp).all():
        history_by_sender[txn.sender_id].append(txn.amount)

    x: list[list[float]] = []
    y: list[int] = []

    cutoff_2h = datetime.utcnow() - timedelta(hours=2)

    for txn in db.query(Transaction).filter(Transaction.verdict.isnot(None)).all():
        recipient = db.query(User).filter(User.id == txn.recipient_id).first()
        if recipient is None:
            continue

        velocity = (
            db.query(func.count(func.distinct(Transaction.sender_id)))
            .filter(Transaction.recipient_id == recipient.id, Transaction.timestamp >= cutoff_2h)
            .scalar()
            or 0
        )

        prior_history = history_by_sender.get(txn.sender_id, [])[:-1] or [txn.amount]
        z = 0.0
        if len(prior_history) >= 2:
            sd = stdev(prior_history)
            if sd > 0:
                z = (txn.amount - mean(prior_history)) / sd

        new_rec = (
            db.query(Transaction)
            .filter(
                Transaction.sender_id == txn.sender_id,
                Transaction.recipient_id == recipient.id,
                Transaction.timestamp < txn.timestamp,
            )
            .count()
            == 0
        )

        age_days = max(0, (datetime.utcnow() - (recipient.created_at or datetime.utcnow())).days)

        features = [
            float(recipient.mule_likelihood or 0.0),
            float(velocity),
            float(z),
            float(new_rec),
            float(age_days),
        ]
        label = {"GREEN": 0, "YELLOW": 1, "RED": 2}.get(txn.verdict, 0)

        x.append(features)
        y.append(label)

    return x, y


if __name__ == "__main__":
    main()
