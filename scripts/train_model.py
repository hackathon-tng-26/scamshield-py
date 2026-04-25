from __future__ import annotations

import pickle
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean, stdev

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.logger import get_logger
from app.models import ScamReport, Transaction, User
from app.core.scoring.rules import apply_rules, verdict_from_score

log = get_logger("train")

FEATURE_ORDER: list[str] = [
    "recipient_mule_likelihood",
    "velocity_cluster_size",
    "recipient_account_age_days",
    "scam_report_count",
    "recipient_in_contacts",
    "amount_zscore",
    "amount_raw",
    "new_recipient",
    "prior_transfer_count",
    "time_of_day_anomaly",
    "structuring_pattern",
]

_BNM_THRESHOLD: float = 10_000.0
_STRUCTURING_MIN_PARTS: int = 3


def main() -> None:
    try:
        from sklearn.ensemble import GradientBoostingClassifier
    except ImportError:
        log.error("train.missing_sklearn")
        sys.exit(1)

    with SessionLocal() as db:
        x, y = _build_training_set(db)

    if len(y) < 50:
        log.error("train.insufficient_data", rows=len(y), needed=50)
        sys.exit(1)

    label_counts = {v: y.count(v) for v in set(y)}
    log.info("train.begin", rows=len(y), features=len(FEATURE_ORDER), label_distribution=label_counts)

    model = GradientBoostingClassifier(
        n_estimators=120,
        max_depth=4,
        learning_rate=0.08,
        subsample=0.85,
        random_state=42,
    )
    model.fit(x, y)
    log.info("train.fit.done", classes=list(model.classes_))

    from app.core.scoring.model import ModelBundle

    bundle = ModelBundle(estimator=model, feature_order=FEATURE_ORDER)
    out_path = "./data/scorer.pkl"
    with open(out_path, "wb") as f:
        pickle.dump(bundle, f)
    log.info("train.saved", path=out_path)


def _build_training_set(db: Session) -> tuple[list[list[float]], list[int]]:
    all_txns = db.query(Transaction).order_by(Transaction.timestamp).all()
    users: dict[str, User] = {u.id: u for u in db.query(User).all()}

    scam_counts: dict[str, int] = defaultdict(int)
    for row in db.query(ScamReport.reported_user_id).all():
        scam_counts[row[0]] += 1

    sender_history: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    recipient_history: dict[str, list[tuple[datetime, str, float]]] = defaultdict(list)

    for t in all_txns:
        if t.timestamp is None:
            continue
        sender_history[t.sender_id].append((t.timestamp, float(t.amount)))
        recipient_history[t.recipient_id].append((t.timestamp, t.sender_id, float(t.amount)))

    x: list[list[float]] = []
    y: list[int] = []

    for txn in all_txns:
        recipient = users.get(txn.recipient_id)
        if recipient is None or txn.timestamp is None:
            continue

        ts = txn.timestamp
        features = _compute_features(txn, ts, recipient, sender_history, recipient_history, scam_counts)

        if txn.verdict in ("GREEN", "YELLOW", "RED"):
            label = {"GREEN": 0, "YELLOW": 1, "RED": 2}[txn.verdict]
        else:
            rule_score, _, _ = apply_rules(features)
            label = {"GREEN": 0, "YELLOW": 1, "RED": 2}[verdict_from_score(rule_score)]

        x.append([features[f] for f in FEATURE_ORDER])
        y.append(label)

    return x, y


def _compute_features(
    txn: Transaction,
    ts: datetime,
    recipient: User,
    sender_history: dict[str, list[tuple[datetime, float]]],
    recipient_history: dict[str, list[tuple[datetime, str, float]]],
    scam_counts: dict[str, int],
) -> dict:
    prior_amounts = [a for t, a in sender_history[txn.sender_id] if t < ts]
    z_score = _zscore(float(txn.amount), prior_amounts)

    prior_to_recipient = [
        (t, sid, a) for t, sid, a in recipient_history[txn.recipient_id] if t < ts
    ]
    prior_count = sum(1 for _, sid, _ in prior_to_recipient if sid == txn.sender_id)

    cutoff_2h = ts - timedelta(hours=2)
    velocity = len({sid for t, sid, _ in prior_to_recipient if t >= cutoff_2h})

    age_days = max(0, (ts - (recipient.created_at or ts)).days)

    time_anomaly = 1.0 if 0 <= ts.hour < 5 else 0.0

    cutoff_24h = ts - timedelta(hours=24)
    recent_inbound = [a for t, _, a in prior_to_recipient if t >= cutoff_24h]
    structuring = 1.0 if (
        len(recent_inbound) >= _STRUCTURING_MIN_PARTS
        and sum(recent_inbound) > _BNM_THRESHOLD
        and all(a < _BNM_THRESHOLD for a in recent_inbound)
    ) else 0.0

    return {
        "recipient_mule_likelihood": float(recipient.mule_likelihood or 0.0),
        "velocity_cluster_size": float(velocity),
        "recipient_account_age_days": float(age_days),
        "scam_report_count": float(scam_counts.get(txn.recipient_id, 0)),
        "recipient_in_contacts": float(prior_count >= 3),
        "amount_zscore": float(z_score),
        "amount_raw": float(txn.amount),
        "new_recipient": float(prior_count == 0),
        "prior_transfer_count": float(prior_count),
        "time_of_day_anomaly": time_anomaly,
        "structuring_pattern": structuring,
    }


def _zscore(x: float, history: list[float]) -> float:
    if len(history) < 2:
        return 0.0
    m = mean(history)
    sd = stdev(history)
    if sd == 0:
        return 0.0
    return (x - m) / sd


if __name__ == "__main__":
    main()
