from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.logger import get_logger
from app.models import Device, Transaction, User

log = get_logger("seed.companions")


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


DEMO_USER_ID = "demo_user_01"
DEMO_USER_PHONE = "+60 12-345 0001"
DEMO_USER_NAME = "Wafi (demo user)"

TRUSTED_DEVICE_ID = "dev-trusted-s21"
TRUSTED_DEVICE_FINGERPRINT = "trusted-samsung-s21"


COMPANION_CONTACTS = [
    {
        "id": "contact_brother",
        "phone": "+60 11-234 5678",
        "name": "Ahmad Hafiz bin Omar",
        "account_type": "normal",
        "mule_likelihood": 0.02,
        "age_days": 720,
        "prior_transfer_count": 47,
        "prior_amount_min": 50.0,
        "prior_amount_max": 250.0,
        "prior_window_days": 365,
    },
    {
        "id": "contact_landlord",
        "phone": "+60 17-555 1234",
        "name": "Tan Chee Wei",
        "account_type": "normal",
        "mule_likelihood": 0.02,
        "age_days": 540,
        "prior_transfer_count": 12,
        "prior_amount_min": 1100.0,
        "prior_amount_max": 1300.0,
        "prior_window_days": 365,
    },
]


def seed_companions(drop_first: bool = False) -> None:
    if drop_first:
        log.warning("seed.companions.drop_first.IGNORED — this script is additive only")

    init_db(drop_first=False)

    with SessionLocal() as s:
        ensured_demo_user = _ensure_demo_user(s)
        ensured_trusted_device = _ensure_trusted_device(s, ensured_demo_user)

        added_companions: list[str] = []
        added_history_count: int = 0

        random.seed(42 + len(COMPANION_CONTACTS))

        for spec in COMPANION_CONTACTS:
            companion = _ensure_companion_user(s, spec)
            if companion["created"]:
                added_companions.append(companion["user"].id)

            history_added = _ensure_prior_history(s, ensured_demo_user, companion["user"], spec)
            added_history_count += history_added

        s.commit()

        log.info(
            "seed.companions.complete",
            demo_user_present=ensured_demo_user.id,
            trusted_device_present=ensured_trusted_device.id,
            companions_added=added_companions,
            companion_history_rows_added=added_history_count,
            companions_total=len(COMPANION_CONTACTS),
        )

        _validate(s)


def _ensure_demo_user(s: Session) -> User:
    user = s.query(User).filter(User.id == DEMO_USER_ID).first()
    if user is not None:
        return user

    user = User(
        id=DEMO_USER_ID,
        phone=DEMO_USER_PHONE,
        name=DEMO_USER_NAME,
        account_type="normal",
        mule_likelihood=0.02,
        created_at=_utcnow_naive() - timedelta(days=400),
    )
    s.add(user)
    s.flush()
    log.info("seed.companions.demo_user.created", user_id=user.id)
    return user


def _ensure_trusted_device(s: Session, demo_user: User) -> Device:
    existing = (
        s.query(Device)
        .filter(
            Device.user_id == demo_user.id,
            Device.fingerprint == TRUSTED_DEVICE_FINGERPRINT,
        )
        .first()
    )
    if existing is not None:
        if not existing.trusted:
            existing.trusted = True
            log.info("seed.companions.device.trust_restored", device_id=existing.id)
        return existing

    device = Device(
        id=TRUSTED_DEVICE_ID,
        user_id=demo_user.id,
        fingerprint=TRUSTED_DEVICE_FINGERPRINT,
        first_seen=_utcnow_naive() - timedelta(days=180),
        geo_ip_region="Kuala Lumpur",
        trusted=True,
    )
    s.add(device)
    s.flush()

    if demo_user.trusted_device_id is None:
        demo_user.trusted_device_id = device.id

    log.info("seed.companions.device.created", device_id=device.id)
    return device


def _ensure_companion_user(s: Session, spec: dict) -> dict:
    by_id = s.query(User).filter(User.id == spec["id"]).first()
    if by_id is not None:
        if by_id.phone != spec["phone"]:
            log.warning(
                "seed.companions.user.phone_drift",
                user_id=by_id.id,
                db_phone=by_id.phone,
                expected_phone=spec["phone"],
            )
        return {"user": by_id, "created": False}

    by_phone = s.query(User).filter(User.phone == spec["phone"]).first()
    if by_phone is not None:
        log.warning(
            "seed.companions.user.phone_collision",
            companion_id=spec["id"],
            existing_user_id=by_phone.id,
            phone=spec["phone"],
        )
        return {"user": by_phone, "created": False}

    user = User(
        id=spec["id"],
        phone=spec["phone"],
        name=spec["name"],
        account_type=spec["account_type"],
        mule_likelihood=spec["mule_likelihood"],
        created_at=_utcnow_naive() - timedelta(days=spec["age_days"]),
    )
    s.add(user)
    s.flush()
    log.info("seed.companions.user.created", user_id=user.id, phone=user.phone)
    return {"user": user, "created": True}


def _ensure_prior_history(
    s: Session, sender: User, recipient: User, spec: dict
) -> int:
    existing_count = (
        s.query(Transaction)
        .filter(
            Transaction.sender_id == sender.id,
            Transaction.recipient_id == recipient.id,
        )
        .count()
    )

    target_count = int(spec["prior_transfer_count"])
    if existing_count >= target_count:
        return 0

    needed = target_count - existing_count
    window_minutes = int(spec["prior_window_days"]) * 24 * 60

    for i in range(needed):
        ts = _utcnow_naive() - timedelta(minutes=random.randint(60, window_minutes))
        amount = round(
            random.uniform(spec["prior_amount_min"], spec["prior_amount_max"]),
            2,
        )
        txn = Transaction(
            id=f"tx-companion-{recipient.id}-{i:03d}-{uuid4().hex[:6]}",
            sender_id=sender.id,
            recipient_id=recipient.id,
            amount=amount,
            timestamp=ts,
            risk_score=random.randint(8, 22),
            verdict="GREEN",
            top_feature="recipient in sender contacts",
            device_id=TRUSTED_DEVICE_FINGERPRINT,
        )
        s.add(txn)

    s.flush()
    log.info(
        "seed.companions.history.created",
        sender_id=sender.id,
        recipient_id=recipient.id,
        rows_added=needed,
        total_after=target_count,
    )
    return needed


def _validate(s: Session) -> None:
    errors: list[str] = []

    demo_user = s.query(User).filter(User.id == DEMO_USER_ID).first()
    if demo_user is None:
        errors.append(f"{DEMO_USER_ID} missing after seed")

    trusted_device = (
        s.query(Device)
        .filter(
            Device.user_id == DEMO_USER_ID,
            Device.fingerprint == TRUSTED_DEVICE_FINGERPRINT,
            Device.trusted.is_(True),
        )
        .first()
    )
    if trusted_device is None:
        errors.append(
            f"trusted device ({DEMO_USER_ID}, {TRUSTED_DEVICE_FINGERPRINT}) missing or untrusted"
        )

    for spec in COMPANION_CONTACTS:
        user = s.query(User).filter(User.phone == spec["phone"]).first()
        if user is None:
            errors.append(f"companion phone {spec['phone']} not resolvable via phone lookup")
            continue

        prior_count = (
            s.query(Transaction)
            .filter(
                Transaction.sender_id == DEMO_USER_ID,
                Transaction.recipient_id == user.id,
            )
            .count()
        )
        if prior_count < 3:
            errors.append(
                f"companion {user.id} has only {prior_count} prior transfers from "
                f"{DEMO_USER_ID} — needs >=3 to trigger recipient_in_contacts rule"
            )

    if errors:
        for e in errors:
            log.error("seed.companions.validation_failed", error=e)
        raise AssertionError(f"Companion seed validation failed: {errors}")

    log.info("seed.companions.validation_ok")


if __name__ == "__main__":
    seed_companions()
