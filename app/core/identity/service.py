from datetime import datetime, timedelta
from uuid import uuid4
import random

from sqlalchemy.orm import Session

from app.models import Device, DeviceCooldown, OtpEvent, RebindAttempt, User

COOLDOWN_HOURS = 24


def _get_or_create_device(
    db: Session, user_id: str, fingerprint: str, geo_ip_region: str = "Kuala Lumpur", label: str = ""
) -> Device:
    device = db.query(Device).filter(Device.user_id == user_id, Device.fingerprint == fingerprint).first()
    if device:
        return device
    device = Device(
        id=f"dev-{uuid4().hex[:12]}",
        user_id=user_id,
        fingerprint=fingerprint,
        first_seen=datetime.utcnow(),
        geo_ip_region=geo_ip_region,
        trusted=False,
    )
    db.add(device)
    db.flush()
    return device


def issue_otp(
    db: Session, user_id: str, action: str, device_fingerprint: str, geo_ip_region: str, device_label: str
) -> tuple[OtpEvent, str]:
    device = _get_or_create_device(db, user_id, device_fingerprint, geo_ip_region, device_label)
    otp_code = f"{random.randint(100000, 999999)}"
    otp_id = f"otp-{uuid4().hex[:12]}"
    expires_at = datetime.utcnow() + timedelta(minutes=5)

    otp = OtpEvent(
        id=otp_id,
        user_id=user_id,
        device_id=device.id,
        action=action,
        geo_ip_region=geo_ip_region,
        device_label=device_label or "unknown device",
        otp_code=otp_code,
        issued_at=datetime.utcnow(),
        expires_at=expires_at,
    )
    db.add(otp)
    db.flush()

    sms_copy = (
        f"OTP {otp_code} is being used to {action} from {device_label or 'unknown device'} in {geo_ip_region}. "
        "If this isn't you, reply STOP."
    )
    return otp, sms_copy


def verify_otp(db: Session, otp_id: str, otp_code: str) -> tuple[OtpEvent | None, str]:
    otp = db.query(OtpEvent).filter(OtpEvent.id == otp_id).first()
    if not otp:
        return None, "OTP_NOT_FOUND"
    if otp.resolved == "blocked":
        return None, "OTP_BLOCKED"
    if otp.expires_at < datetime.utcnow():
        return None, "OTP_EXPIRED"
    if otp.otp_code != otp_code:
        return None, "OTP_INVALID"
    otp.used_at = datetime.utcnow()
    return otp, "OK"


def resolve_otp(db: Session, otp_id: str, resolution: str) -> OtpEvent | None:
    otp = db.query(OtpEvent).filter(OtpEvent.id == otp_id).first()
    if not otp:
        return None
    otp.resolved = resolution
    if resolution == "blocked" and otp.device_id:
        device = db.query(Device).filter(Device.id == otp.device_id).first()
        if device:
            device.trusted = False
    return otp


def is_device_in_cooldown(db: Session, user_id: str, device_fingerprint: str) -> tuple[bool, datetime | None]:
    device = db.query(Device).filter(Device.user_id == user_id, Device.fingerprint == device_fingerprint).first()
    if not device:
        return True, datetime.utcnow() + timedelta(hours=COOLDOWN_HOURS)

    explicit = (
        db.query(DeviceCooldown)
        .filter(
            DeviceCooldown.user_id == user_id,
            DeviceCooldown.device_id == device.id,
            DeviceCooldown.cooldown_until > datetime.utcnow(),
        )
        .first()
    )
    if explicit:
        return True, explicit.cooldown_until

    if not device.trusted:
        cutoff = datetime.utcnow() - timedelta(hours=COOLDOWN_HOURS)
        if device.first_seen > cutoff:
            return True, device.first_seen + timedelta(hours=COOLDOWN_HOURS)

    return False, None


def check_device_trust(db: Session, user_id: str, device_fingerprint: str) -> dict:
    device = _get_or_create_device(db, user_id, device_fingerprint)
    in_cooldown, until = is_device_in_cooldown(db, user_id, device_fingerprint)
    hours_remaining = None
    if in_cooldown and until:
        hours_remaining = max(0.0, (until - datetime.utcnow()).total_seconds() / 3600)
    return {
        "device_id": device.id,
        "trusted": device.trusted,
        "cooldown_active": in_cooldown,
        "cooldown_until": until,
        "cooldown_hours_remaining": round(hours_remaining, 2) if hours_remaining is not None else None,
    }


def request_rebind(db: Session, user_id: str, new_device_fingerprint: str) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {"rebind_id": "", "status": "blocked", "friction_required": False, "friction_method": None}

    new_device = _get_or_create_device(db, user_id, new_device_fingerprint)
    in_cooldown, _ = is_device_in_cooldown(db, user_id, new_device_fingerprint)

    if in_cooldown or not new_device.trusted:
        rebind = RebindAttempt(
            id=f"rb-{uuid4().hex[:12]}",
            user_id=user_id,
            device_id=new_device.id,
            attempted_at=datetime.utcnow(),
            outcome="pending",
            friction_method="video_verify",
        )
        db.add(rebind)
        db.flush()
        return {
            "rebind_id": rebind.id,
            "status": "pending",
            "friction_required": True,
            "friction_method": "video_verify",
        }

    rebind = RebindAttempt(
        id=f"rb-{uuid4().hex[:12]}",
        user_id=user_id,
        device_id=new_device.id,
        attempted_at=datetime.utcnow(),
        outcome="approved",
        friction_method=None,
    )
    db.add(rebind)
    user.trusted_device_id = new_device.id
    new_device.trusted = True
    db.flush()
    return {
        "rebind_id": rebind.id,
        "status": "approved",
        "friction_required": False,
        "friction_method": None,
    }


def get_cooldown_status(db: Session, user_id: str) -> dict:
    devices = db.query(Device).filter(Device.user_id == user_id).all()
    for device in devices:
        in_cooldown, until = is_device_in_cooldown(db, user_id, device.fingerprint)
        if in_cooldown:
            hours_remaining = max(0.0, (until - datetime.utcnow()).total_seconds() / 3600)
            return {
                "user_id": user_id,
                "cooldown_active": True,
                "cooldown_until": until,
                "reason": "new_device",
                "banner_message": f"Transfers paused on this device for {int(hours_remaining)} more hours for security.",
            }
    return {
        "user_id": user_id,
        "cooldown_active": False,
        "cooldown_until": None,
        "reason": None,
        "banner_message": None,
    }
