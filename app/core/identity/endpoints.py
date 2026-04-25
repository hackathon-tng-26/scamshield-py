from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.core.identity import service as identity_service
from app.schemas.identity import (
    CooldownStatusResponse,
    DeviceEnrollRequest,
    DeviceTrustResult,
    OtpIssueRequest,
    OtpIssueResponse,
    OtpResolveRequest,
    OtpResolveResponse,
    OtpVerifyRequest,
    OtpVerifyResponse,
    RebindRequest,
    RebindResponse,
)

router = APIRouter(prefix="/identity", tags=["Layer 1 — Identity & Device Trust"])


@router.post("/otp/issue", response_model=OtpIssueResponse)
def otp_issue(req: OtpIssueRequest, db: Session = Depends(get_db)) -> OtpIssueResponse:
    otp, sms_copy = identity_service.issue_otp(
        db, req.user_id, req.action, req.device_fingerprint, req.geo_ip_region, req.device_label
    )
    return OtpIssueResponse(
        otp_id=otp.id,
        otp_code=otp.otp_code,
        sms_copy=sms_copy,
        expires_at=otp.expires_at,
    )


@router.post("/otp/verify", response_model=OtpVerifyResponse)
def otp_verify(req: OtpVerifyRequest, db: Session = Depends(get_db)) -> OtpVerifyResponse:
    otp, status = identity_service.verify_otp(db, req.otp_id, req.otp_code)
    if otp is None:
        return OtpVerifyResponse(success=False, otp_id=req.otp_id, message=status)
    return OtpVerifyResponse(success=True, otp_id=otp.id, message=status)


@router.post("/otp/resolve", response_model=OtpResolveResponse)
def otp_resolve(req: OtpResolveRequest, db: Session = Depends(get_db)) -> OtpResolveResponse:
    otp = identity_service.resolve_otp(db, req.otp_id, req.resolution)
    if not otp:
        raise HTTPException(status_code=404, detail="OTP not found")
    return OtpResolveResponse(success=True, otp_id=otp.id, resolution=req.resolution)


@router.post("/device/check", response_model=DeviceTrustResult)
def device_check(req: DeviceEnrollRequest, db: Session = Depends(get_db)) -> DeviceTrustResult:
    result = identity_service.check_device_trust(db, req.user_id, req.device_fingerprint)
    return DeviceTrustResult(**result)


@router.post("/rebind", response_model=RebindResponse)
def rebind(req: RebindRequest, db: Session = Depends(get_db)) -> RebindResponse:
    result = identity_service.request_rebind(db, req.user_id, req.new_device_fingerprint)
    return RebindResponse(**result)


@router.get("/cooldown/{user_id}", response_model=CooldownStatusResponse)
def cooldown_status(user_id: str, db: Session = Depends(get_db)) -> CooldownStatusResponse:
    result = identity_service.get_cooldown_status(db, user_id)
    return CooldownStatusResponse(**result)
