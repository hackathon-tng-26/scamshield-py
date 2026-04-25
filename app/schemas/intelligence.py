from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


ClusterTier = Literal["t1", "t2", "t3"]
PatternType = Literal["fan_in", "velocity_cluster", "offramp_proximity", "structuring"]
ModelType = Literal["gbdt", "rules"]
FlagEntityType = Literal["user", "transaction"]
FlagSeverity = Literal["low", "medium", "high", "critical"]


class MuleClusterOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str | None
    tier: ClusterTier
    member_count: int
    avg_mule_likelihood: float
    last_refreshed_at: datetime


class MuleClusterMembershipOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    cluster_id: str
    user_id: str
    joined_at: datetime


class PatternDetectionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    node_id: str
    pattern_type: PatternType
    value: float
    detected_at: datetime
    cluster_id: str | None


class TransactionContextOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    transaction_id: str
    third_party_tokenisation: str | None
    card_bound_recently: bool
    wallet_rebound_recently: bool
    merchant_category: str | None


class AiModelVersionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    model_type: ModelType
    version_tag: str
    artifact_path: str | None
    deployed_at: datetime
    is_active: bool


class AiRiskFlagOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    entity_id: str
    entity_type: FlagEntityType
    flag_type: str
    severity: FlagSeverity
    score_contribution: float
    rationale: str | None
    flagged_at: datetime
    model_version_id: str | None
