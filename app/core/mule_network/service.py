"""
Layer 3 — Mule Network Intelligence service orchestrator.

Responsibilities
----------------
1. Build the transaction graph (NetworkX, hackathon) or fetch from Neptune (prod).
2. Extract node feature vectors for ML inference.
3. Invoke the best available predictor (SageMaker GNN → Fraud Detector → NetworkX).
4. Run graph analytics: pattern detection, laundering paths, risk propagation.
5. Persist results back to the DB (PatternDetection, MuleCluster, User.mule_likelihood).
6. Serve read API for L2 scoring to consume at transaction time.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.mule_network.graph_analytics import (
    apply_temporal_attention,
    detect_fresh_account_fan_in,
    detect_offramp_proximity,
    detect_structuring,
    detect_velocity_clusters,
    extract_node_features,
    find_laundering_paths,
    propagate_risk_scores,
)
from app.core.mule_network.ml_engine import MulePrediction, get_predictor
from app.graph.builder import build_graph
from app.logger import get_logger
from app.models import MuleCluster, MuleClusterMembership, PatternDetection, User
from app.schemas.mule_network import (
    ExplainabilityResponse,
    GraphRefreshResponse,
    LaunderingPathResponse,
    MuleLikelihoodBatchResponse,
    MuleLikelihoodScore,
    NodeFeatureVector,
    PatternDetectionResult,
)

log = get_logger(__name__)

_predictor = None


def _get_predictor():
    global _predictor
    if _predictor is None:
        _predictor = get_predictor()
    return _predictor


# ---------------------------------------------------------------------------
# 1. Compute mule likelihood for a single account (L2 consumes this)
# ---------------------------------------------------------------------------


def compute_mule_likelihood(account_id: str, db: Session) -> MuleLikelihoodScore | None:
    """
    Real-time API for L2 scoring.
    Returns a MuleLikelihoodScore that L2 reads as 'recipient_mule_likelihood'.
    """
    start_ms = time.perf_counter()

    try:
        features = extract_node_features(db, account_id)
    except ValueError:
        log.warning("mule_network.unknown_account", account_id=account_id)
        return None

    # Compute off-ramp proximity lazily (needs graph)
    G = build_graph(db, within_days=7)
    proximity = detect_offramp_proximity(G, account_id, max_hops=3)
    if proximity:
        features.offramp_proximity_hops = proximity["hops"]

    pred = _get_predictor().predict(features)
    if pred is None:
        return None

    # Blend with graph-propagation risk if available
    pr_scores = propagate_risk_scores(apply_temporal_attention(G))
    graph_risk = pr_scores.get(account_id, 0.0)
    blended = min(1.0, 0.7 * pred.mule_likelihood + 0.3 * graph_risk)

    latency = int((time.perf_counter() - start_ms) * 1000)
    log.info(
        "mule_network.score",
        account_id=account_id,
        ml_score=round(pred.mule_likelihood, 3),
        graph_risk=round(graph_risk, 3),
        blended=round(blended, 3),
        source=pred.model_source,
        latency_ms=latency,
    )

    # Persist to user record for caching
    user = db.query(User).filter(User.id == account_id).first()
    if user:
        user.mule_likelihood = blended
        db.commit()

    return MuleLikelihoodScore(
        account_id=account_id,
        mule_likelihood=round(blended, 4),
        confidence=pred.confidence,
        model_source=pred.model_source,
        top_contributors=pred.top_contributors + ([f"graph_risk={graph_risk:.2f}"] if graph_risk > 0.3 else []),
        refreshed_at=pred.refreshed_at,
    )


# ---------------------------------------------------------------------------
# 2. Batch refresh — scheduled job (Alibaba Function Compute cron)
# ---------------------------------------------------------------------------


def refresh_graph_scores(db: Session) -> GraphRefreshResponse:
    """
    Scheduled refresh that recomputes mule-likelihood for ALL accounts.
    Intended to run as a cron job every 15-30 minutes.
    """
    start_ms = time.perf_counter()
    G = build_graph(db, within_days=30)
    H = apply_temporal_attention(G)
    pr_scores = propagate_risk_scores(H)

    predictor = _get_predictor()
    users = db.query(User).all()
    refreshed = 0
    new_detections = 0

    for user in users:
        try:
            features = extract_node_features(db, user.id)
        except Exception:
            continue

        features.offramp_proximity_hops = None
        proximity = detect_offramp_proximity(G, user.id, max_hops=3)
        if proximity:
            features.offramp_proximity_hops = proximity["hops"]

        pred = predictor.predict(features)
        if pred is None:
            continue

        graph_risk = pr_scores.get(user.id, 0.0)
        blended = min(1.0, 0.7 * pred.mule_likelihood + 0.3 * graph_risk)

        if blended != user.mule_likelihood:
            user.mule_likelihood = blended
            refreshed += 1

        # Persist pattern detections
        patterns = _run_pattern_detections(db, G, user.id)
        for p in patterns:
            _upsert_pattern_detection(db, user.id, p)
            new_detections += 1

    db.commit()
    latency = int((time.perf_counter() - start_ms) * 1000)
    log.info("mule_network.refresh", refreshed=refreshed, new_detections=new_detections, latency_ms=latency)

    return GraphRefreshResponse(
        refreshed_nodes=refreshed,
        new_detections=new_detections,
        model_version=predictor.model_version,
        latency_ms=latency,
    )


# ---------------------------------------------------------------------------
# 3. Laundering path API
# ---------------------------------------------------------------------------


def get_laundering_paths(account_id: str, db: Session) -> list[LaunderingPathResponse]:
    """
    Returns detected money-laundering chains starting from account_id.
    """
    G = build_graph(db, within_days=30)
    raw_paths = find_laundering_paths(G, account_id, max_length=5, min_amount=500.0)

    results: list[LaunderingPathResponse] = []
    for idx, path in enumerate(raw_paths):
        risk_score = min(100.0, path["total_weight"] / 50.0 + path["length"] * 10.0)
        nodes = [
            {
                "account_id": n["account_id"],
                "layer": n["layer"],
                "mule_likelihood": n["mule_likelihood"],
                "amount": path["total_weight"] / max(1, len(path["nodes"]) - 1),
            }
            for n in path["nodes"]
        ]
        results.append(
            LaunderingPathResponse(
                path_id=f"path-{account_id}-{idx}",
                source_id=account_id,
                target_id=path["target_offramp"],
                nodes=nodes,
                total_amount=round(path["total_weight"], 2),
                path_length=path["length"],
                risk_score=round(risk_score, 1),
            )
        )
    return results


# ---------------------------------------------------------------------------
# 4. Explainability — graph-based SHAP-style attribution
# ---------------------------------------------------------------------------


def explain_mule_score(account_id: str, db: Session) -> ExplainabilityResponse | None:
    """
    Returns WHY an account has its mule-likelihood score.
    Breaks down contribution by: graph neighbors, laundering paths, tabular features.
    """
    user = db.query(User).filter(User.id == account_id).first()
    if user is None:
        return None

    G = build_graph(db, within_days=30)
    H = apply_temporal_attention(G)

    # Neighbor attribution
    neighbor_attribution: list[dict] = []
    if account_id in H:
        for pred in list(H.predecessors(account_id))[:5]:
            weight = float(H[pred][account_id].get("weight", 0.0))
            ml = float(H.nodes[pred].get("mule_likelihood", 0.0))
            neighbor_attribution.append({
                "neighbor_id": pred,
                "edge_weight": round(weight, 2),
                "neighbor_mule_likelihood": round(ml, 3),
                "contribution": round(weight * ml / 1000.0, 3),
            })

    # Path attribution
    path_attribution: list[dict] = []
    paths = find_laundering_paths(G, account_id, max_length=4, min_amount=100.0)[:3]
    for p in paths:
        path_attribution.append({
            "path_length": p["length"],
            "total_amount": round(p["total_weight"], 2),
            "contribution": round(min(25.0, p["total_weight"] / 500.0), 2),
        })

    # Feature attribution (heuristic based on extracted features)
    feature_attribution: list[dict] = []
    try:
        features = extract_node_features(db, account_id)
        if features.account_age_days <= 7:
            feature_attribution.append({"feature": "account_age_days", "value": features.account_age_days, "contribution": 0.15})
        if features.fan_in_velocity_1h >= 8:
            feature_attribution.append({"feature": "fan_in_velocity_1h", "value": features.fan_in_velocity_1h, "contribution": 0.20})
        if features.scam_report_count > 0:
            feature_attribution.append({"feature": "scam_report_count", "value": features.scam_report_count, "contribution": min(0.25, features.scam_report_count * 0.05)})
        if features.structuring_flag:
            feature_attribution.append({"feature": "structuring_flag", "value": True, "contribution": 0.20})
    except Exception:
        pass

    overall = float(user.mule_likelihood or 0.0)
    return ExplainabilityResponse(
        account_id=account_id,
        overall_score=round(overall, 4),
        neighbor_attribution=neighbor_attribution,
        path_attribution=path_attribution,
        feature_attribution=feature_attribution,
    )


# ---------------------------------------------------------------------------
# 5. Pattern detection helpers
# ---------------------------------------------------------------------------


def _run_pattern_detections(db: Session, G: "nx.DiGraph", account_id: str) -> list[dict]:
    """Run all pattern detectors for a single account."""
    results: list[dict] = []

    # Off-ramp proximity
    prox = detect_offramp_proximity(G, account_id, max_hops=3)
    if prox:
        results.append(prox)

    # Structuring
    struct = detect_structuring(db, account_id)
    if struct:
        results.append(struct)

    return results


def _upsert_pattern_detection(db: Session, node_id: str, pattern: dict) -> None:
    """Insert or update a PatternDetection row."""
    existing = (
        db.query(PatternDetection)
        .filter(
            PatternDetection.node_id == node_id,
            PatternDetection.pattern_type == pattern["pattern_type"],
        )
        .order_by(PatternDetection.detected_at.desc())
        .first()
    )
    if existing and (datetime.now(timezone.utc) - existing.detected_at).total_seconds() < 3600:
        # Update within 1h window
        existing.value = pattern["score_contribution"]
        existing.detected_at = datetime.now(timezone.utc)
    else:
        db.add(
            PatternDetection(
                id=f"pd-{uuid4().hex[:12]}",
                node_id=node_id,
                pattern_type=pattern["pattern_type"],
                value=pattern["score_contribution"],
                detected_at=datetime.now(timezone.utc),
            )
        )
