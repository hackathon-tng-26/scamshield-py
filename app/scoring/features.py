from datetime import datetime, timedelta, timezone
from statistics import mean, stdev


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Device, OtpEvent, RebindAttempt, ScamReport, Transaction, User
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

    cutoff_2h = _utcnow() - timedelta(hours=2)
    velocity_count = (
        db.query(func.count(func.distinct(Transaction.sender_id)))
        .filter(Transaction.recipient_id == recipient.id, Transaction.timestamp >= cutoff_2h)
        .scalar()
        or 0
    )

    user_history = [
        float(row[0])
        for row in db.query(Transaction.amount)
        .filter(Transaction.sender_id == sender.id)
        .limit(100)
        .all()
    ]

    amount_zscore = _zscore(req.amount, user_history) if user_history else 0.0
    new_recipient = prior_count == 0
    recipient_in_contacts = prior_count >= 3

    scam_report_count = (
        db.query(ScamReport)
        .filter(ScamReport.reported_user_id == recipient.id)
        .count()
    )

    structuring_pattern = _detect_structuring_pattern(db, recipient.id)
    time_of_day_anomaly = _detect_time_anomaly(req.timestamp_ms, db, sender.id)

    l1_signals = _extract_l1_signals(req, db)

    return {
        "recipient_mule_likelihood": float(recipient.mule_likelihood or 0.0),
        "recipient_mule_pattern_tag": recipient.mule_pattern_tag,
        "velocity_cluster_size": int(velocity_count),
        "recipient_account_age_days": _account_age_days(recipient),
        "scam_report_count": int(scam_report_count),
        "recipient_in_contacts": recipient_in_contacts,
        "amount_zscore": float(amount_zscore),
        "amount_raw": float(req.amount),
        "new_recipient": new_recipient,
        "prior_transfer_count": int(prior_count),
        "time_of_day_anomaly": time_of_day_anomaly,
        "structuring_pattern": structuring_pattern,
        "third_party_tokenisation": bool(req.third_party_tokenisation),
        "card_bound_recently": req.card_bound_recently,
        "wallet_rebound_recently": req.wallet_rebound_recently,
        **l1_signals,
    }


def _extract_l1_signals(req: ScoreTransferRequest, db: Session) -> dict:
    device = (
        db.query(Device)
        .filter(Device.user_id == req.sender_id, Device.fingerprint == req.device_fingerprint)
        .first()
    )

    device_trusted = False
    new_device_login = False
    device_in_cooldown = False
    geo_ip_shift = False

    if device:
        device_trusted = device.trusted
        cutoff_1h = _utcnow() - timedelta(hours=1)
        new_device_login = device.first_seen > cutoff_1h

        from app.core.identity.service import is_device_in_cooldown
        device_in_cooldown, _ = is_device_in_cooldown(db, req.sender_id, req.device_fingerprint)

        other_regions = [
            r[0]
            for r in db.query(Device.geo_ip_region)
            .filter(Device.user_id == req.sender_id, Device.fingerprint != req.device_fingerprint)
            .all()
        ]
        if other_regions:
            geo_ip_shift = all(r != device.geo_ip_region for r in other_regions)

    latest_otp = (
        db.query(OtpEvent)
        .filter(OtpEvent.user_id == req.sender_id)
        .order_by(OtpEvent.issued_at.desc())
        .first()
    )
    otp_context_ignored = latest_otp.resolved == "blocked" if latest_otp else False

    recent_rebind = (
        db.query(RebindAttempt)
        .filter(
            RebindAttempt.user_id == req.sender_id,
            RebindAttempt.attempted_at >= _utcnow() - timedelta(hours=1),
            RebindAttempt.outcome == "pending",
        )
        .first()
    )
    rebind_in_progress = recent_rebind is not None

    return {
        "device_trusted": device_trusted,
        "new_device_login": new_device_login,
        "device_in_cooldown": device_in_cooldown,
        "otp_context_ignored": otp_context_ignored,
        "rebind_in_progress": rebind_in_progress,
        "geo_ip_shift": geo_ip_shift,
        "otp_issued_within_5min": req.otp_issued_within_5min,
        "password_changed_within_24h": req.password_changed_within_24h,
        "accessibility_service_detected": req.accessibility_service_detected,
    }


def _detect_structuring_pattern(db: Session, recipient_id: str) -> bool:
    cutoff_24h = _utcnow() - timedelta(hours=24)
    recent_inbound = [
        float(row[0])
        for row in db.query(Transaction.amount)
        .filter(Transaction.recipient_id == recipient_id, Transaction.timestamp >= cutoff_24h)
        .all()
    ]
    bnm_threshold = 10_000.0
    return (
        len(recent_inbound) >= 3
        and sum(recent_inbound) > bnm_threshold
        and all(a < bnm_threshold for a in recent_inbound)
    )


def _detect_time_anomaly(timestamp_ms: int, db: Session, sender_id: str) -> bool:
    txn_dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    txn_hour = txn_dt.hour

    if 0 <= txn_hour < 5:
        return True

    historical_hours = [
        row[0].hour
        for row in db.query(Transaction.timestamp)
        .filter(Transaction.sender_id == sender_id)
        .limit(50)
        .all()
        if row[0] is not None
    ]
    if len(historical_hours) >= 5:
        avg_hour = mean(historical_hours)
        return abs(txn_hour - avg_hour) > 8

    return False


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
    return max(0, (_utcnow() - user.created_at).days)


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
