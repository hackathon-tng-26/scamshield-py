import time
from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import settings
from app.logger import get_logger
from app.schemas.transfer import FeatureContribution, ScoreTransferRequest, ScoreTransferResponse
from app.core.ai_engine.engine import AiAssessment, run_ai_assessment
from app.core.scoring.demo_overrides import check_demo_override
from app.core.scoring.features import extract_features
from app.core.scoring.model import get_model, score_from_model
from app.core.scoring.rules import apply_rules, verdict_from_score

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

    score, verdict, attribution = _apply_gbdt_blend(score, verdict, attribution, features)

    if settings.ai_scoring_enabled:
        ai = run_ai_assessment(
            features,
            rule_score=score,
            rule_verdict=verdict,
            model=settings.ai_model,
            timeout_seconds=settings.ai_scoring_timeout_seconds,
        )
        if ai is not None and ai.confidence >= 0.4:
            score, verdict, attribution, highlights = _apply_ai_assessment(
                ai, score, attribution, highlights
            )

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


def _apply_gbdt_blend(
    rule_score: int,
    rule_verdict: str,
    attribution: list[FeatureContribution],
    features: dict,
) -> tuple[int, str, list[FeatureContribution]]:
    if rule_score >= 70:
        return rule_score, rule_verdict, attribution

    bundle = get_model()
    if bundle is None:
        return rule_score, rule_verdict, attribution

    gbdt_score = score_from_model(bundle, features)
    if gbdt_score is None:
        return rule_score, rule_verdict, attribution

    w = settings.model_blend_weight
    blended = max(0, min(100, int(round(w * gbdt_score + (1.0 - w) * rule_score))))

    if blended == rule_score:
        return rule_score, rule_verdict, attribution

    delta = blended - rule_score
    attribution = attribution + [
        FeatureContribution(
            feature="GBDT model calibration",
            contribution=abs(delta),
            direction="positive" if delta > 0 else "negative",
        )
    ]

    log.debug(
        "score.gbdt_blend",
        rule_score=rule_score,
        gbdt_score=gbdt_score,
        blended=blended,
        weight=w,
    )

    return blended, verdict_from_score(blended), attribution


def _apply_ai_assessment(
    ai: AiAssessment,
    score: int,
    attribution: list[FeatureContribution],
    highlights: list[str],
) -> tuple[int, str, list[FeatureContribution], list[str]]:
    adj = max(-15, min(15, ai.score_adjustment))
    new_score = max(0, min(100, score + adj))
    new_verdict = verdict_from_score(new_score)

    if adj != 0:
        label = ai.scam_type.replace("_", " ")
        semakmule_tag = ai.semakmule_pattern_signal.replace("_", " ")
        attribution = attribution + [
            FeatureContribution(
                feature=f"AI intelligence: {label} [{semakmule_tag}]",
                contribution=abs(adj),
                direction="positive" if adj > 0 else "negative",
            )
        ]

    merged_highlights = highlights + [h for h in ai.additional_highlights if h not in highlights]

    return new_score, new_verdict, attribution, merged_highlights
