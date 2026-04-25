"""
ML-enhanced graph analytics for Layer 3 — Mule Network Intelligence.

Capabilities
------------
1. Temporal Graph Attention   — edge weights decay exponentially by age.
2. Laundering Path Detection  — shortest path from victim → offramp via T1/T2/T3.
3. Graph Feature Extraction   — builds NodeFeatureVector for ML models.
4. Pattern Detection          — fresh-account fan-in, velocity clusters, structuring.

Why these patterns matter (Cybersecurity perspective):
- Fresh-account fan-in:  T1 mules are recruited specifically to receive victim funds.
                         8+ unrelated senders in 1 hour is physically impossible for a
                         legitimate new account.
- Velocity cluster:      Scammers create batches of accounts together.  If N accounts
                         created in the same week all transact identically, they share
                         a single threat actor.
- Off-ramp proximity:    T3 mules are 1-2 hops from crypto/USDT off-ramps.  Detecting
                         proximity lets us freeze funds before conversion.
- Structuring:           BNM AMLA threshold is RM10,000.  Splitting RM15k into two
                         RM7.5k transfers is deliberate evasion.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import networkx as nx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.logger import get_logger
from app.models import Device, MuleCluster, PatternDetection, Transaction, User

if TYPE_CHECKING:
    from app.schemas.mule_network import NodeFeatureVector

log = get_logger(__name__)

_HOUR_SECONDS = 3600.0
_DECAY_LAMBDA = 0.693 / 24.0  # half-life = 24 hours


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# 1. Temporal Graph Attention — exponentially decay edge weights
# ---------------------------------------------------------------------------


def apply_temporal_attention(G: nx.DiGraph) -> nx.DiGraph:
    """
    Returns a weighted copy of G where each edge weight = amount * exp(-lambda * age_hours).
    Recent transactions dominate; old transactions fade.
    """
    now = _utcnow()
    H = G.copy()
    for u, v, data in H.edges(data=True):
        ts = data.get("timestamp")
        if isinstance(ts, datetime):
            age_h = max(0.0, (now - ts).total_seconds() / _HOUR_SECONDS)
            decay = math.exp(-_DECAY_LAMBDA * age_h)
        else:
            decay = 1.0
        amount = float(data.get("amount", 0.0))
        H[u][v]["weight"] = amount * decay
        H[u][v]["decay"] = decay
    return H


# ---------------------------------------------------------------------------
# 2. Laundering Path Detection
# ---------------------------------------------------------------------------


def find_laundering_paths(
    G: nx.DiGraph,
    source_id: str,
    max_length: int = 5,
    min_amount: float = 1000.0,
) -> list[dict]:
    """
    Find all simple paths from source_id to any offramp node within max_length hops.
    Returns paths sorted by total weighted amount descending.
    """
    offramps = [n for n, attrs in G.nodes(data=True) if attrs.get("layer") == "offramp"]
    if source_id not in G or not offramps:
        return []

    H = apply_temporal_attention(G)
    paths: list[dict] = []

    for target in offramps:
        try:
            for path in nx.all_simple_paths(H, source=source_id, target=target, cutoff=max_length):
                total_weight = sum(
                    float(H[u][v].get("weight", 0.0)) for u, v in zip(path, path[1:])
                )
                if total_weight >= min_amount:
                    nodes_meta = [
                        {
                            "account_id": node,
                            "layer": H.nodes[node].get("layer", "unknown"),
                            "mule_likelihood": float(H.nodes[node].get("mule_likelihood", 0.0)),
                        }
                        for node in path
                    ]
                    paths.append({
                        "nodes": nodes_meta,
                        "total_weight": total_weight,
                        "length": len(path) - 1,
                        "target_offramp": target,
                    })
        except nx.NetworkXNoPath:
            continue

    paths.sort(key=lambda p: p["total_weight"], reverse=True)
    return paths[:10]  # cap at 10 highest-value paths


# ---------------------------------------------------------------------------
# 3. Graph Feature Extraction — build NodeFeatureVector for ML
# ---------------------------------------------------------------------------


def extract_node_features(db: Session, account_id: str) -> "NodeFeatureVector":
    """
    Extracts a 17-dimensional feature vector for a single account.
    This vector is fed into SageMaker GNN or AWS Fraud Detector.
    """
    from app.schemas.mule_network import NodeFeatureVector

    user = db.query(User).filter(User.id == account_id).first()
    if user is None:
        raise ValueError(f"User {account_id} not found")

    cutoff_30d = _utcnow() - timedelta(days=30)
    cutoff_1h = _utcnow() - timedelta(hours=1)

    inbound_30d = (
        db.query(Transaction)
        .filter(Transaction.recipient_id == account_id, Transaction.timestamp >= cutoff_30d)
        .all()
    )
    outbound_30d = (
        db.query(Transaction)
        .filter(Transaction.sender_id == account_id, Transaction.timestamp >= cutoff_30d)
        .all()
    )

    inbound_1h = [t for t in inbound_30d if t.timestamp and t.timestamp >= cutoff_1h]
    outbound_1h = [t for t in outbound_30d if t.timestamp and t.timestamp >= cutoff_1h]

    inbound_amounts = [float(t.amount) for t in inbound_30d]
    outbound_amounts = [float(t.amount) for t in outbound_30d]

    unique_senders_30d = len({t.sender_id for t in inbound_30d})
    unique_recipients_30d = len({t.recipient_id for t in outbound_30d})

    devices = db.query(Device).filter(Device.user_id == account_id).all()
    geo_regions = {d.geo_ip_region for d in devices if d.geo_ip_region}

    scam_report_count = (
        db.query(func.count(PatternDetection.id))
        .filter(PatternDetection.node_id == account_id, PatternDetection.pattern_type == "scam_report")
        .scalar()
        or 0
    )

    # Structuring flag: received >RM10k total, then sent multiple sub-RM10k chunks
    structuring_flag = False
    total_inbound = sum(inbound_amounts)
    if total_inbound >= 10_000.0:
        recent_outbound = [
            float(t.amount)
            for t in outbound_30d
            if t.timestamp and t.timestamp >= (_utcnow() - timedelta(hours=24))
        ]
        if len(recent_outbound) >= 3 and all(a < 10_000.0 for a in recent_outbound):
            structuring_flag = True

    # Off-ramp proximity (computed lazily from graph)
    offramp_hops = None

    age_days = 0
    if user.created_at:
        age_days = max(0, (_utcnow() - user.created_at).days)

    return NodeFeatureVector(
        account_id=account_id,
        account_age_days=age_days,
        inbound_volume_30d=round(total_inbound, 2),
        outbound_volume_30d=round(sum(outbound_amounts), 2),
        unique_senders_30d=unique_senders_30d,
        unique_recipients_30d=unique_recipients_30d,
        geo_region_diversity=len(geo_regions),
        device_count=len(devices),
        scam_report_count=int(scam_report_count),
        avg_inbound_amount=round(sum(inbound_amounts) / len(inbound_amounts), 2) if inbound_amounts else 0.0,
        avg_outbound_amount=round(sum(outbound_amounts) / len(outbound_amounts), 2) if outbound_amounts else 0.0,
        max_single_inbound=round(max(inbound_amounts), 2) if inbound_amounts else 0.0,
        max_single_outbound=round(max(outbound_amounts), 2) if outbound_amounts else 0.0,
        fan_in_velocity_1h=len(inbound_1h),
        fan_out_velocity_1h=len(outbound_1h),
        structuring_flag=structuring_flag,
        offramp_proximity_hops=offramp_hops,
    )


# ---------------------------------------------------------------------------
# 4. Pattern Detectors
# ---------------------------------------------------------------------------


def detect_fresh_account_fan_in(
    db: Session,
    G: nx.DiGraph | None = None,
    threshold_senders: int = 8,
    window_hours: int = 1,
) -> list[dict]:
    """
    Detect accounts created <=7 days ago that receive from threshold_senders+
    distinct senders within window_hours.
    """
    results: list[dict] = []
    cutoff_age = _utcnow() - timedelta(days=7)
    cutoff_window = _utcnow() - timedelta(hours=window_hours)

    fresh_accounts = db.query(User).filter(User.created_at >= cutoff_age).all()

    for user in fresh_accounts:
        senders = (
            db.query(func.count(func.distinct(Transaction.sender_id)))
            .filter(
                Transaction.recipient_id == user.id,
                Transaction.timestamp >= cutoff_window,
            )
            .scalar()
            or 0
        )
        if senders >= threshold_senders:
            results.append({
                "account_id": user.id,
                "pattern_type": "fresh_account_fan_in",
                "distinct_senders": int(senders),
                "severity": "critical" if senders >= 15 else "high",
                "score_contribution": min(25.0, senders * 1.5),
            })
    return results


def detect_velocity_clusters(
    db: Session,
    time_window_hours: int = 24,
    min_cluster_size: int = 5,
) -> list[dict]:
    """
    DBSCAN-inspired clustering: find groups of accounts that all received funds
    and forwarded them within the same short time window.
    """
    from collections import defaultdict

    cutoff = _utcnow() - timedelta(hours=time_window_hours)
    txns = (
        db.query(Transaction)
        .filter(Transaction.timestamp >= cutoff)
        .order_by(Transaction.timestamp)
        .all()
    )

    # Build a quick lookup: recipient -> list of (sender, timestamp, amount)
    recv_map: dict[str, list[tuple[str, datetime, float]]] = defaultdict(list)
    for t in txns:
        recv_map[t.recipient_id].append((t.sender_id, t.timestamp, float(t.amount)))

    # Find recipients with high in-out velocity
    flagged: list[dict] = []
    for recip, records in recv_map.items():
        if len(records) < min_cluster_size:
            continue
        # Check if they also sent out shortly after receiving
        outbound = (
            db.query(Transaction)
            .filter(
                Transaction.sender_id == recip,
                Transaction.timestamp >= cutoff,
            )
            .all()
        )
        if len(outbound) >= 3:
            flagged.append({
                "account_id": recip,
                "pattern_type": "velocity_cluster",
                "inbound_count": len(records),
                "outbound_count": len(outbound),
                "severity": "high",
                "score_contribution": min(25.0, len(records) * 2.0),
            })

    return flagged


def detect_offramp_proximity(
    G: nx.DiGraph,
    account_id: str,
    max_hops: int = 3,
) -> dict | None:
    """
    Returns proximity info if account_id is within max_hops of an offramp node.
    """
    if account_id not in G:
        return None

    offramps = [n for n, attrs in G.nodes(data=True) if attrs.get("layer") == "offramp"]
    best_hops: int | None = None
    best_offramp: str | None = None

    for off in offramps:
        try:
            hops = nx.shortest_path_length(G, source=account_id, target=off)
            if best_hops is None or hops < best_hops:
                best_hops = hops
                best_offramp = off
        except nx.NetworkXNoPath:
            continue

    if best_hops is not None and best_hops <= max_hops:
        return {
            "account_id": account_id,
            "pattern_type": "offramp_proximity",
            "hops": best_hops,
            "nearest_offramp": best_offramp,
            "severity": "critical" if best_hops == 1 else "high" if best_hops == 2 else "medium",
            "score_contribution": (max_hops - best_hops + 1) * 8.0,
        }
    return None


def detect_structuring(
    db: Session,
    account_id: str,
    bnm_threshold: float = 10_000.0,
    window_hours: int = 24,
) -> dict | None:
    """
    BNM AMLA threshold evasion: inbound >= threshold, then outbound split into
    multiple sub-threshold chunks.
    """
    cutoff = _utcnow() - timedelta(hours=window_hours)

    inbound_total = (
        db.query(func.sum(Transaction.amount))
        .filter(Transaction.recipient_id == account_id, Transaction.timestamp >= cutoff)
        .scalar()
        or 0.0
    )

    if inbound_total < bnm_threshold:
        return None

    outbound = (
        db.query(Transaction.amount)
        .filter(Transaction.sender_id == account_id, Transaction.timestamp >= cutoff)
        .all()
    )
    outbound_amounts = [float(a[0]) for a in outbound]

    if len(outbound_amounts) >= 3 and all(a < bnm_threshold for a in outbound_amounts):
        return {
            "account_id": account_id,
            "pattern_type": "structuring",
            "inbound_total": round(float(inbound_total), 2),
            "outbound_chunks": len(outbound_amounts),
            "severity": "critical",
            "score_contribution": 20.0,
        }
    return None


# ---------------------------------------------------------------------------
# 5. Multi-hop Risk Propagation (PageRank-style)
# ---------------------------------------------------------------------------


def propagate_risk_scores(G: nx.DiGraph, alpha: float = 0.85, max_iter: int = 100) -> dict[str, float]:
    """
    Personalized PageRank where known mule nodes are the personalization vector.
    Returns a risk score (0-1) for every node in the graph.
    """
    if len(G) == 0:
        return {}

    # Seed vector: known mules get high weight
    personalization: dict[str, float] = {}
    for node, attrs in G.nodes(data=True):
        ml = float(attrs.get("mule_likelihood", 0.0))
        personalization[node] = 0.1 + ml  # baseline + known score

    try:
        pr = nx.pagerank(
            G,
            alpha=alpha,
            personalization=personalization,
            weight="weight",
            max_iter=max_iter,
        )
    except Exception:
        pr = {n: 0.0 for n in G.nodes()}

    # Normalize to 0-1
    max_pr = max(pr.values()) if pr else 1.0
    if max_pr > 0:
        pr = {k: min(1.0, v / max_pr) for k, v in pr.items()}
    return pr
