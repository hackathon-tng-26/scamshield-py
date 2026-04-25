from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Verdict = Literal["GREEN", "YELLOW", "RED"]
Direction = Literal["positive", "negative"]


class FeatureContribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: str
    contribution: int
    direction: Direction


class ScoreTransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender_id: str
    recipient_id: str
    recipient_phone: str
    amount: float = Field(ge=0.0)
    device_fingerprint: str
    timestamp_ms: int
    otp_issued_within_5min: bool = False
    password_changed_within_24h: bool = False
    accessibility_service_detected: bool = False
    card_bound_recently: bool = False
    wallet_rebound_recently: bool = False
    third_party_tokenisation: str | None = None


class ScoreTransferResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    score: int = Field(ge=0, le=100)
    verdict: Verdict
    attribution: list[FeatureContribution] = Field(default_factory=list)
    latency_ms: int
    explanation_highlights: list[str] = Field(default_factory=list)


class ExecuteTransferResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    transaction_id: str
