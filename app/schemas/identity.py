from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class OtpIssueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    action: Literal["login", "transfer", "rebind"]
    device_fingerprint: str
    geo_ip_region: str = "Kuala Lumpur"
    device_label: str = ""


class OtpIssueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    otp_id: str
    otp_code: str
    sms_copy: str
    expires_at: datetime


class OtpVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    otp_id: str
    otp_code: str


class OtpVerifyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    otp_id: str
    message: str


class OtpResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    otp_id: str
    resolution: Literal["allowed", "blocked"]


class OtpResolveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    otp_id: str
    resolution: str


class DeviceEnrollRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    device_fingerprint: str
    geo_ip_region: str = "Kuala Lumpur"
    device_label: str = ""


class DeviceTrustResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    trusted: bool
    cooldown_active: bool
    cooldown_until: datetime | None
    cooldown_hours_remaining: float | None


class RebindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    new_device_fingerprint: str


class RebindResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rebind_id: str
    status: Literal["approved", "pending", "blocked"]
    friction_required: bool
    friction_method: Literal["video_verify", "support_call"] | None


class CooldownStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    cooldown_active: bool
    cooldown_until: datetime | None
    reason: str | None
    banner_message: str | None
