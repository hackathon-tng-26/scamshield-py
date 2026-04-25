import time
from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import settings
from app.logger import get_logger
from app.schemas.transfer import ScoreTransferRequest, ScoreTransferResponse
from app.scoring.demo_overrides import check_demo_override
from app.scoring.features import extract_features
from app.scoring.rules import apply_rules, verdict_from_score

log = get_logger(__name__)


def score_transfer(req: ScoreTransferRequest, db: Session) -> ScoreTransferResponse:
    start_ms = time.perf_counter()

    if settings.demo_overrides_enabled:
        override = check_demo_override(req)
        if override is not None:
            override.latency_ms = int((time.perf_counter() - start_ms) * 1000) or override.latency_ms
            log.info(
                "score.override",
                recipient_phone=req.recipient_phone,
                verdict=override.verdict,
                score=override.score,
            )
            return override

    features = extract_features(req, db)
    score, attribution, highlights = apply_rules(features)
    verdict = verdict_from_score(score)

    latency = int((time.perf_counter() - start_ms) * 1000)
    log.info(
        "score.computed",
        sender_id=req.sender_id,
        recipient_phone=req.recipient_phone,
        amount=req.amount,
        score=score,
        verdict=verdict,
        latency_ms=latency,
    )

    return ScoreTransferResponse(
        transaction_id=f"tx-{uuid4().hex[:12]}",
        score=score,
        verdict=verdict,
        attribution=attribution,
        latency_ms=latency,
        explanation_highlights=highlights,
    )
