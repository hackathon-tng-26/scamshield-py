"""
AWS ML-powered mule likelihood prediction engine.

CTO Architecture Decision
-------------------------
Primary:   GraphSAGE on Amazon SageMaker (DGL) — graph-based node classification.
Fallback:  AWS Fraud Detector — tabular scoring for cold-start accounts.
Prod path: Amazon Neptune ML — real-time GNN inference at query time.

Why GraphSAGE (not XGBoost or a CNN):
- Inductive: generalises to unseen nodes.  Mule accounts are created fresh daily.
- Neighbour aggregation: propagates risk through transaction edges naturally.
- Sampling: scales to millions of accounts without loading the whole graph in RAM.

Why AWS Fraud Detector as fallback:
- Cold-start: a 1-hour-old account has zero graph neighbours.
- Fraud Detector needs only tabular features (age, device, geo) — no graph history.
- Managed service → no training infra to maintain for the fallback path.

Dataset
-------
Nodes: accounts with 14 behavioural features (age, volume, geo diversity, etc.)
Edges: transactions weighted by amount, recency, and frequency.
Labels: binary is_mule (>=2 scam reports OR law-enforcement confirmed tag).
Window: 90-day rolling graph snapshot, retrained weekly on SageMaker.
"""

from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.config import settings
from app.logger import get_logger

if TYPE_CHECKING:
    from app.schemas.mule_network import NodeFeatureVector

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class MulePrediction:
    account_id: str
    mule_likelihood: float
    confidence: float
    model_source: str
    top_contributors: list[str]
    refreshed_at: str


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class MuleLikelihoodPredictor(ABC):
    """Base class for all mule-likelihood prediction backends."""

    @abstractmethod
    def predict(self, features: NodeFeatureVector) -> MulePrediction | None:
        ...

    @abstractmethod
    def predict_batch(self, features_list: list[NodeFeatureVector]) -> list[MulePrediction | None]:
        ...

    @property
    @abstractmethod
    def model_version(self) -> str:
        ...


# ---------------------------------------------------------------------------
# 1. Amazon SageMaker GraphSAGE (primary)
# ---------------------------------------------------------------------------


class SageMakerGNNEngine(MuleLikelihoodPredictor):
    """
    Invokes a GraphSAGE endpoint hosted on Amazon SageMaker.

    Expected endpoint contract (JSON):
      Input:  {"node_features": {...}, "neighbor_ids": [...]}
      Output: {"mule_probability": 0.82, "confidence": 0.91,
               "top_contributors": ["neighbor_abc", "neighbor_def"]}
    """

    def __init__(
        self,
        endpoint_name: str | None = None,
        region: str | None = None,
        timeout_seconds: float = 2.0,
    ):
        self.endpoint_name = endpoint_name or os.environ.get("SAGEMAKER_MULE_ENDPOINT", "")
        self.region = region or os.environ.get("AWS_REGION", "ap-southeast-1")
        self.timeout_s = timeout_seconds
        self._client = None
        self._version = "sagemaker-gnn-unknown"

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3
            self._client = boto3.client("sagemaker-runtime", region_name=self.region)
            log.info("ml_engine.sagemaker.init", endpoint=self.endpoint_name, region=self.region)
        except Exception as exc:
            log.error("ml_engine.sagemaker.init_failed", error=str(exc))
            self._client = None
        return self._client

    def predict(self, features: NodeFeatureVector) -> MulePrediction | None:
        client = self._get_client()
        if client is None or not self.endpoint_name:
            return None
        payload = json.dumps({
            "node_features": features.model_dump(),
            "neighbor_ids": [],  # populated by caller if available
        })
        try:
            start = time.perf_counter()
            response = client.invoke_endpoint(
                EndpointName=self.endpoint_name,
                ContentType="application/json",
                Body=payload,
            )
            body = json.loads(response["Body"].read())
            latency = int((time.perf_counter() - start) * 1000)
            log.info(
                "ml_engine.sagemaker.predict",
                account_id=features.account_id,
                latency_ms=latency,
                probability=body.get("mule_probability"),
            )
            return MulePrediction(
                account_id=features.account_id,
                mule_likelihood=float(body.get("mule_probability", 0.0)),
                confidence=float(body.get("confidence", 0.0)),
                model_source="sagemaker_gnn",
                top_contributors=list(body.get("top_contributors", [])),
                refreshed_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            log.error("ml_engine.sagemaker.error", error=str(exc)[:200])
            return None

    def predict_batch(self, features_list: list[NodeFeatureVector]) -> list[MulePrediction | None]:
        # SageMaker endpoints typically accept single records or mini-batches.
        # For simplicity we loop; in production use SageMaker batch transform.
        return [self.predict(f) for f in features_list]

    @property
    def model_version(self) -> str:
        return self._version


# ---------------------------------------------------------------------------
# 2. AWS Fraud Detector (cold-start fallback)
# ---------------------------------------------------------------------------


class FraudDetectorEngine(MuleLikelihoodPredictor):
    """
    AWS Fraud Detector for accounts with insufficient graph history.

    Expected detector: 'scamshield_mule_detector'
    Event type:       'account_registration_event'
    """

    def __init__(
        self,
        detector_id: str | None = None,
        event_type: str | None = None,
        region: str | None = None,
    ):
        self.detector_id = detector_id or os.environ.get("FRAUD_DETECTOR_ID", "scamshield_mule_detector")
        self.event_type = event_type or os.environ.get("FRAUD_DETECTOR_EVENT_TYPE", "account_registration_event")
        self.region = region or os.environ.get("AWS_REGION", "ap-southeast-1")
        self._client = None
        self._version = "fraud-detector-unknown"

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3
            self._client = boto3.client("frauddetector", region_name=self.region)
            log.info("ml_engine.frauddetector.init", detector=self.detector_id)
        except Exception as exc:
            log.error("ml_engine.frauddetector.init_failed", error=str(exc))
            self._client = None
        return self._client

    def predict(self, features: NodeFeatureVector) -> MulePrediction | None:
        client = self._get_client()
        if client is None:
            return None
        try:
            start = time.perf_counter()
            response = client.get_event_prediction(
                detectorId=self.detector_id,
                eventId=f"evt-{features.account_id}-{int(time.time())}",
                eventTypeName=self.event_type,
                eventTimestamp=datetime.now(timezone.utc).isoformat(),
                entities=[{"entityType": "account", "entityId": features.account_id}],
                eventVariables={
                    "account_age_days": str(features.account_age_days),
                    "inbound_volume_30d": str(features.inbound_volume_30d),
                    "outbound_volume_30d": str(features.outbound_volume_30d),
                    "unique_senders_30d": str(features.unique_senders_30d),
                    "unique_recipients_30d": str(features.unique_recipients_30d),
                    "geo_region_diversity": str(features.geo_region_diversity),
                    "device_count": str(features.device_count),
                    "scam_report_count": str(features.scam_report_count),
                    "structuring_flag": str(features.structuring_flag).lower(),
                },
            )
            latency = int((time.perf_counter() - start) * 1000)
            outcomes = response.get("modelScores", [])
            if not outcomes:
                return None
            score = outcomes[0].get("scores", {}).get("scamshield_mule_model", 0.0)
            log.info(
                "ml_engine.frauddetector.predict",
                account_id=features.account_id,
                latency_ms=latency,
                score=score,
            )
            return MulePrediction(
                account_id=features.account_id,
                mule_likelihood=min(1.0, max(0.0, float(score))),
                confidence=0.75,
                model_source="fraud_detector",
                top_contributors=["tabular_cold_start_fallback"],
                refreshed_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            log.error("ml_engine.frauddetector.error", error=str(exc)[:200])
            return None

    def predict_batch(self, features_list: list[NodeFeatureVector]) -> list[MulePrediction | None]:
        return [self.predict(f) for f in features_list]

    @property
    def model_version(self) -> str:
        return self._version


# ---------------------------------------------------------------------------
# 3. NetworkX heuristic fallback (hackathon / offline mode)
# ---------------------------------------------------------------------------


class NetworkXFallbackEngine(MuleLikelihoodPredictor):
    """
    Deterministic heuristic engine used when:
    - boto3 is not installed
    - AWS credentials are absent
    - SageMaker endpoint is unreachable

    This is the 'offline brain' that keeps L3 alive without cloud spend.
    """

    def __init__(self):
        self._version = "networkx-v1.0.0"

    def predict(self, features: NodeFeatureVector) -> MulePrediction | None:
        raw = 0.0
        contributors: list[str] = []

        # Fresh account + high fan-in = strong mule signal
        if features.account_age_days <= 7:
            raw += 0.25
            contributors.append("account_age<=7_days")
        if features.account_age_days <= 1 and features.fan_in_velocity_1h >= 3:
            raw += 0.30
            contributors.append("fresh_account_high_fan_in")

        # Velocity clusters
        if features.fan_in_velocity_1h >= 8:
            raw += 0.20
            contributors.append("fan_in_velocity>=8/hr")
        if features.fan_out_velocity_1h >= 5:
            raw += 0.15
            contributors.append("fan_out_velocity>=5/hr")

        # Scam reports
        if features.scam_report_count >= 2:
            raw += 0.25
            contributors.append(f"scam_reports={features.scam_report_count}")
        elif features.scam_report_count == 1:
            raw += 0.10
            contributors.append("scam_report=1")

        # Structuring
        if features.structuring_flag:
            raw += 0.20
            contributors.append("structuring_detected")

        # Off-ramp proximity
        if features.offramp_proximity_hops is not None and features.offramp_proximity_hops <= 2:
            raw += 0.15
            contributors.append(f"offramp_proximity={features.offramp_proximity_hops}_hops")

        # Geo diversity (mules often receive from many regions)
        if features.geo_region_diversity >= 3:
            raw += 0.10
            contributors.append("high_geo_diversity")

        likelihood = min(1.0, raw)
        confidence = 0.60 if contributors else 0.30

        return MulePrediction(
            account_id=features.account_id,
            mule_likelihood=likelihood,
            confidence=confidence,
            model_source="networkx_fallback",
            top_contributors=contributors,
            refreshed_at=datetime.now(timezone.utc).isoformat(),
        )

    def predict_batch(self, features_list: list[NodeFeatureVector]) -> list[MulePrediction | None]:
        return [self.predict(f) for f in features_list]

    @property
    def model_version(self) -> str:
        return self._version


# ---------------------------------------------------------------------------
# Factory — auto-select best available engine
# ---------------------------------------------------------------------------


def get_predictor() -> MuleLikelihoodPredictor:
    """
    Priority:
      1. SageMaker GNN   (if endpoint configured & reachable)
      2. Fraud Detector  (if detector configured & reachable)
      3. NetworkX fallback (always works, zero cloud cost)
    """
    sagemaker_endpoint = os.environ.get("SAGEMAKER_MULE_ENDPOINT", "")
    if sagemaker_endpoint:
        engine = SageMakerGNNEngine(endpoint_name=sagemaker_endpoint)
        if engine._get_client() is not None:
            log.info("ml_engine.selected", source="sagemaker_gnn")
            return engine

    fraud_detector = os.environ.get("FRAUD_DETECTOR_ID", "")
    if fraud_detector:
        engine = FraudDetectorEngine(detector_id=fraud_detector)
        if engine._get_client() is not None:
            log.info("ml_engine.selected", source="fraud_detector")
            return engine

    log.info("ml_engine.selected", source="networkx_fallback")
    return NetworkXFallbackEngine()
