from pydantic import BaseModel, ConfigDict, Field


class NodeFeatureVector(BaseModel):
    """Tabular feature vector for a single account (sent to AWS Fraud Detector or GNN)."""

    model_config = ConfigDict(extra="forbid")

    account_id: str
    account_age_days: int
    inbound_volume_30d: float
    outbound_volume_30d: float
    unique_senders_30d: int
    unique_recipients_30d: int
    geo_region_diversity: int
    device_count: int
    scam_report_count: int
    avg_inbound_amount: float
    avg_outbound_amount: float
    max_single_inbound: float
    max_single_outbound: float
    fan_in_velocity_1h: int
    fan_out_velocity_1h: int
    structuring_flag: bool
    offramp_proximity_hops: int | None


class MuleLikelihoodScore(BaseModel):
    """Single-account mule likelihood result."""

    model_config = ConfigDict(extra="forbid")

    account_id: str
    mule_likelihood: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    model_source: str  # "sagemaker_gnn", "fraud_detector", "networkx_fallback"
    top_contributors: list[str] = Field(default_factory=list)
    refreshed_at: str


class MuleLikelihoodBatchResponse(BaseModel):
    """Batch scoring response for BO dashboard."""

    model_config = ConfigDict(extra="forbid")

    scores: list[MuleLikelihoodScore]
    model_version: str
    latency_ms: int


class LaunderingPathNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str
    layer: str  # victim, t1, t2, t3, offramp
    mule_likelihood: float
    amount: float


class LaunderingPathResponse(BaseModel):
    """Detected money-laundering chain from victim to offramp."""

    model_config = ConfigDict(extra="forbid")

    path_id: str
    source_id: str
    target_id: str
    nodes: list[LaunderingPathNode]
    total_amount: float
    path_length: int
    risk_score: float = Field(ge=0.0, le=100.0)


class PatternDetectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_type: str
    account_id: str
    severity: str  # low, medium, high, critical
    score_contribution: float
    details: dict


class GraphRefreshResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refreshed_nodes: int
    new_detections: int
    model_version: str
    latency_ms: int


class ExplainabilityResponse(BaseModel):
    """Graph-based SHAP-style explanation for a mule score."""

    model_config = ConfigDict(extra="forbid")

    account_id: str
    overall_score: float
    neighbor_attribution: list[dict]
    path_attribution: list[dict]
    feature_attribution: list[dict]
