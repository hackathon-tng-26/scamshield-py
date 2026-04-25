from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


OtpAction = Literal["login", "transfer", "rebind"]
OtpResolved = Literal["allowed", "blocked"]
CooldownReason = Literal["new_device", "suspicious_session"]
RebindOutcome = Literal["pending", "approved", "blocked"]
RebindFriction = Literal["video_verify", "support_call"]


class OtpEventOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    device_id: str | None
    action: OtpAction
    geo_ip_region: str | None
    device_label: str | None
    issued_at: datetime
    resolved: OtpResolved | None


class DeviceSessionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    device_id: str | None
    started_at: datetime
    last_active_at: datetime
    otp_issued_at: datetime | None
    password_changed_at: datetime | None
    accessibility_service_detected: bool
    is_active: bool


class DeviceCooldownOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    device_id: str | None
    cooldown_until: datetime
    reason: CooldownReason
    created_at: datetime


class RebindAttemptOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    device_id: str | None
    attempted_at: datetime
    outcome: RebindOutcome | None
    friction_method: RebindFriction | None
