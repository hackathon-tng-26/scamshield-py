from uuid import uuid4

from app.schemas.transfer import FeatureContribution, ScoreTransferRequest, ScoreTransferResponse


SITI_PHONE = "+60 12-345 6789"
Y1_PHONE = "+60 13-777 0022"
MULE_R1_PHONE_MARKER = "8712"


Y1_ATTRIBUTION: list[FeatureContribution] = [
    FeatureContribution(feature="baseline (user risk prior)", contribution=50, direction="positive"),
    FeatureContribution(feature="new recipient", contribution=25, direction="positive"),
    FeatureContribution(feature="amount above 90th percentile", contribution=18, direction="positive"),
    FeatureContribution(feature="time-of-day in-pattern", contribution=8, direction="negative"),
]

Y1_HIGHLIGHTS: list[str] = [
    "New recipient — no transfer history",
    "Amount higher than your usual pattern",
    "No mule signals detected yet",
]

R1_ATTRIBUTION: list[FeatureContribution] = [
    FeatureContribution(feature="baseline (user risk prior)", contribution=50, direction="positive"),
    FeatureContribution(feature="recipient mule-likelihood (L3)", contribution=40, direction="positive"),
    FeatureContribution(feature="velocity cluster (19 senders/2h)", contribution=35, direction="positive"),
    FeatureContribution(feature="amount vs user history", contribution=20, direction="positive"),
    FeatureContribution(feature="new recipient", contribution=12, direction="positive"),
    FeatureContribution(feature="time-of-day in-pattern", contribution=8, direction="negative"),
    FeatureContribution(feature="user own risk history", contribution=12, direction="negative"),
]

R1_HIGHLIGHTS: list[str] = [
    "19 users transferred to this number in the last 2 hours",
    "7 of them later reported it as a scam",
    "Account created 3 days ago",
    "Matches mule-account pattern MP-047",
]

G1_ATTRIBUTION: list[FeatureContribution] = [
    FeatureContribution(feature="baseline (user risk prior)", contribution=50, direction="positive"),
    FeatureContribution(feature="recipient in contacts", contribution=22, direction="negative"),
    FeatureContribution(feature="amount in-pattern", contribution=12, direction="negative"),
    FeatureContribution(feature="trusted device", contribution=10, direction="negative"),
    FeatureContribution(feature="time-of-day in-pattern", contribution=8, direction="negative"),
]

G1_HIGHLIGHTS: list[str] = [
    "Recipient in your contacts",
    "8 previous transfers to this person",
    "Amount typical for you",
]


def _y1_response(transaction_id: str) -> ScoreTransferResponse:
    return ScoreTransferResponse(
        transaction_id=transaction_id,
        score=55,
        verdict="YELLOW",
        attribution=Y1_ATTRIBUTION,
        latency_ms=142,
        explanation_highlights=Y1_HIGHLIGHTS,
    )


def _r1_response(transaction_id: str) -> ScoreTransferResponse:
    return ScoreTransferResponse(
        transaction_id=transaction_id,
        score=87,
        verdict="RED",
        attribution=R1_ATTRIBUTION,
        latency_ms=142,
        explanation_highlights=R1_HIGHLIGHTS,
    )


def _g1_response(transaction_id: str) -> ScoreTransferResponse:
    return ScoreTransferResponse(
        transaction_id=transaction_id,
        score=18,
        verdict="GREEN",
        attribution=G1_ATTRIBUTION,
        latency_ms=142,
        explanation_highlights=G1_HIGHLIGHTS,
    )


def check_demo_override(req: ScoreTransferRequest) -> ScoreTransferResponse | None:
    phone = req.recipient_phone
    tx_id = f"demo-{uuid4().hex[:12]}"

    if MULE_R1_PHONE_MARKER in phone:
        return _r1_response(tx_id)

    if phone == Y1_PHONE or req.recipient_id == "new_recipient_22":
        return _y1_response(tx_id)

    if phone == SITI_PHONE or req.recipient_id == "contact_siti":
        return _g1_response(tx_id)

    return None
