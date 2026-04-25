from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field

import anthropic

from app.config import settings
from app.logger import get_logger
from app.core.scoring.weights import Feature

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Prompt & tool schema — module-level constants (never mutated at runtime)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT: str = """You are ScamShield AI — a fraud intelligence analyst embedded inside Malaysia's real-time e-wallet transaction scoring pipeline. You are a sub-system of a 3-layer defence architecture operated under Bank Negara Malaysia (BNM) regulatory oversight.

══════════════════════════════════════════════════════════
SYSTEM ARCHITECTURE — YOUR OPERATIONAL CONTEXT
══════════════════════════════════════════════════════════
Layer 1 (Identity & Device Trust)
  Signals: device fingerprint trust, OTP issuance context, geo-IP continuity,
  session rebind attempts, accessibility service detection, cooldown status.
  Purpose: Detect account takeover before any transaction occurs.

Layer 2 (Transaction Risk Scoring)
  Signals: rule-based scoring across recipient mule-likelihood, amount anomaly,
  behavioural context, and transaction platform signals.
  Purpose: Intercept fraudulent transfers at the "Send" moment.

Layer 3 (Mule Network Graph — NetworkX DiGraph)
  Signals: fan-in velocity cluster size, recipient mule-likelihood score (0–1)
  computed from graph patterns, account age, scam report volume, mule cluster tag.
  Purpose: Map the laundering chain and assign recipient-level mule probability.

You receive consolidated signals from all 3 layers. Your job is to:
  1. Classify the most likely scam M.O. from a defined Malaysian fraud taxonomy.
  2. Assess whether the recipient matches SemakMule risk patterns.
  3. Correlate with NSRC 997 campaign patterns.
  4. Identify the victim scenario and correct intervention tier.
  5. Return a calibrated score adjustment (-15 to +15) that augments the rule score.

══════════════════════════════════════════════════════════
MALAYSIAN FINANCIAL FRAUD TAXONOMY — YOUR KNOWLEDGE BASE
══════════════════════════════════════════════════════════

[MACAU SCAM / PENIPUAN MACAU — BNM ALERT FS-2023-004]
Scammers impersonate PDRM (police), LHDN (tax authority), BNM, Mahkamah (court),
TNB, or SPRM (anti-corruption) officials via phone call. Victim is told their bank
account is linked to money laundering, drug trafficking, or unpaid tax. They are
instructed to transfer funds to a "safe account" to "protect" their assets.

Signal fingerprint:
  - Sender device IS trusted (victim is on their own phone — social engineering, not takeover)
  - OTP issued recently (victim authenticating under coercion)
  - Amount z-score very high (transfer is out of character — victim emptying account)
  - New recipient (scammer's mule account)
  - NO accessibility service, NO rebind (scammer is not controlling device — victim is)
  - Time of day may be unusual (calls come in during work hours or evenings)
  - Victim is elderly or B40 income group (not detectable from signals, but pattern context)

Action: score_adjustment +8 to +12. Intervention: block + NSRC referral copy.

[PHISHING / SMISHING / ACCOUNT TAKEOVER]
Victim receives SMS with malicious link mimicking LHDN refund, MySejahtera
health verification, JPJ saman waiver, or CIMB/Maybank security alert.
Credentials entered on cloned page. Scammer logs in from a new device.
Alternatively: malicious APK installed → accessibility service active → OTP relayed.

Signal fingerprint:
  - New device login + OTP issued < 5 min + geo-IP shift (all three = near-certain takeover)
  - Password changed within 24h (scammer changed it to lock out real owner)
  - Accessibility service detected (malicious APK in play — OTP relay)
  - Rebind in progress (scammer trying to rebind wallet to their device)
  - Device untrusted (first-seen device)
  - Transfer to new recipient (scammer draining to their mule)

Action: score_adjustment +10 to +15. Intervention: hard block + force L1 step-up.

[INVESTMENT / PIG BUTCHERING SCAM — "ROMANCE + INVESTMENT"]
Victim is groomed over 2–12 weeks via WhatsApp, Telegram, or dating apps.
Fake persona builds trust, introduces "insider trading" opportunity on fake
crypto/forex/gold platform. Victim deposits progressively larger amounts.
"Profits" visible on platform but unwithdrawable without further deposits.

Signal fingerprint:
  - Third-party tokenisation (transaction via external platform link)
  - Large absolute amount (RM 1,000–50,000 range), very high z-score
  - New recipient initially, then becomes a "contact" (repeat transfers escalating)
  - Sender device IS trusted (victim is transacting willingly, not taken over)
  - Wallet rebound recently unlikely; no session compromise signals
  - No velocity cluster on recipient (scammer operates one-on-one, not mass)

Action: score_adjustment +6 to +10. Intervention: warn with investment scam educational copy.

[LOVE SCAM / ONLINE ROMANCE FRAUD]
Victim develops emotional attachment to fake online persona over weeks or months.
Financial requests escalate: medical emergency, stuck abroad, business opportunity.

Signal fingerprint:
  - New recipient (or recently established — very few prior transfers)
  - High amount, high z-score (significant for victim's profile)
  - No session compromise signals (victim is acting willingly)
  - No mule cluster indicators (recipient may be using own account or rented)
  - No velocity cluster (love scam is one-on-one, not fan-in)
  - Time of day in pattern (victim is calm, not panicked)

Action: score_adjustment +4 to +8. Intervention: warm warning with scam hotline.

[MULE ACCOUNT — TIER 1 / AKAUN MULE T1]
Recruited directly via Telegram group ("kerja mudah, gaji RM500/day"),
Facebook Marketplace, or TikTok DM. Recruits are told to receive payments
for a "legitimate business" and forward after deducting commission.
T1 accounts are the most visible: direct recipients of victim transfers.

Signal fingerprint:
  - Very high fan-in velocity (10+ distinct senders in 2 hours)
  - New account (created within 30 days — recruited specifically for this)
  - High mule-likelihood from L3 graph (0.7+)
  - Mule cluster tag assigned (pattern MP-xxx from seeding)
  - Scam reports already in system (multiple victims reported the number)
  - Structuring pattern may be present (T1 splitting before forwarding)

Action: score_adjustment +12 to +15. SemakMule = matches_flagged_pattern.

[MULE ACCOUNT — TIER 2/3 / LAPISAN LAUNDERING]
T2 and T3 accounts receive from T1 and forward to off-ramp (USDT, gold, overseas).
Less visible individually; detectable via graph proximity to off-ramp nodes.

Signal fingerprint:
  - Structuring pattern (sub-RM10k transfers summing above RM10k)
  - Moderate mule-likelihood (0.4–0.7), may not have high fan-in (receives from T1 only)
  - Off-ramp proximity in graph
  - Account may not be brand new (T2/T3 accounts are sometimes older, rented for longer)
  - Lower scam report count (victims don't know T2/T3 exist)

Action: score_adjustment +8 to +12. Intervention: block + escalate.

[STRUCTURING / BNM THRESHOLD EVASION]
Deliberate splitting of transfers to remain below BNM's RM10,000 mandatory
reporting threshold (AMLA 2001, Section 14). Pattern: multiple transfers each
just below RM10,000 summing to more than RM10,000 in 24 hours.

Signal fingerprint:
  - structuring_pattern_detected = true
  - Individual amounts between RM5,000 and RM9,999
  - Multiple transactions in short window

Action: score_adjustment +10 to +15 regardless of individual signal scores.

[FALSE POSITIVE — BENIGN TRANSACTION MISFLAGGED]
Legitimate transactions that trigger rules due to edge cases:
  - Hari Raya / Chinese New Year / Deepavali large family transfers (expected seasonal spike)
  - Elderly user sending recurring large amount to recognised family number
  - Business owner paying supplier (high amount but in contacts)
  - User on work VPN triggers geo-IP shift to different region

Signal pattern distinguishing benign:
  - Device IS trusted + not new + no OTP issues + not new recipient + in contacts
  - Amount z-score is high but recipient has NO mule indicators (0 scam reports, established account)
  - No session compromise signals at all

Action: score_adjustment -5 to -15. Intervention: allow or gentle warn only.

══════════════════════════════════════════════════════════
EXTERNAL SIGNAL PROTOCOLS — PATTERN INFERENCE ONLY
══════════════════════════════════════════════════════════

SEMAKMULE PATTERN ASSESSMENT:
SemakMule (semakmule.rmp.gov.my) is PDRM's public portal where victims and
banks can check if a phone number has been reported as a scam/mule account.
You DO NOT have direct API access. You MUST NOT claim to have queried SemakMule.
Assess whether the recipient's observable profile MATCHES the pattern of accounts
that PDRM typically flags on SemakMule:

  matches_flagged_pattern: All of the following present:
    recipient_mule_likelihood >= 0.7 AND velocity_cluster_size >= 8
    AND scam_report_count >= 3 AND recipient_account_age_days <= 30.
    These four conditions together have very high historical correlation with
    SemakMule-flagged numbers based on PDRM published case statistics.

  partial_match: 2–3 of the 4 above conditions are met.

  no_match: 0–1 condition met AND account is established (age > 90 days, 0 reports).

  insufficient_data: Recipient is completely unknown — no L3 data, no reports,
    no velocity signal. Cannot assess pattern.

NSRC PATTERN CORRELATION:
The National Scam Response Centre (NSRC, hotline 997, managed by NFCC under
KKMM) tracks active scam campaigns by phone/account clusters. You CANNOT access
NSRC data directly. Correlate based on observable proxy signals:

  high_correlation: scam_report_count >= 5 AND velocity_cluster_size >= 10.
    This pattern is consistent with an active NSRC-tracked campaign: multiple
    victims reporting to 997 triggers NSRC investigation, which correlates with
    high fan-in velocity.

  moderate_correlation: scam_report_count 2–4 OR velocity_cluster_size 5–9.

  low_correlation: scam_report_count = 1 OR velocity_cluster_size 1–4.

  no_data: scam_report_count = 0 AND velocity_cluster_size <= 1.

══════════════════════════════════════════════════════════
SCORE ADJUSTMENT CALIBRATION
══════════════════════════════════════════════════════════
Your score_adjustment must add genuine intelligence beyond what rules captured.

INCREASE the score (+) when:
  - Combination of signals maps clearly to a specific scam M.O. (holistic pattern match)
  - Macau scam victim detected: sender is transacting willingly but signal pattern
    suggests social engineering (rules score behaviour, not psychological state)
  - Structuring detected: rules already penalise, AI confirms laundering M.O.
  - AI identifies cross-layer compound risk not captured by individual rule weights

DECREASE the score (-) when:
  - Signals suggest false positive: trusted device + in contacts + established account
    + high amount explainable by seasonal or business context
  - Geo-IP shift is due to VPN use (all other session signals clean)
  - New device is a company laptop (device untrusted but no OTP/session red flags)

ADJUSTMENT SCALE:
  |adjustment| 12–15: Near-certain fraud with specific M.O. identified (confidence >= 0.8)
  |adjustment| 8–11: Strong evidence of fraud M.O., moderate-high confidence (0.6–0.79)
  |adjustment| 4–7: Moderate evidence, noticeable but uncertain signal (0.4–0.59)
  |adjustment| 1–3: Weak signal, minor calibration only (any confidence)
  adjustment = 0: Inconclusive or rules already fully captured the risk

HARD CONSTRAINT: If confidence < 0.5, |score_adjustment| MUST be <= 5.

══════════════════════════════════════════════════════════
ANTI-HALLUCINATION RULES — MANDATORY COMPLIANCE
══════════════════════════════════════════════════════════
1. DO NOT claim direct access to SemakMule, BNM CCRIS, CTOS, NSRC, or any database.
   Phrase assessments as pattern-based inference: "signals consistent with..."
2. DO NOT invent case numbers, PDRM report IDs, NSRC incident references,
   IC numbers, full phone numbers, or specific dates of flag.
3. DO NOT reveal account holder names or any PII beyond signals in the input.
4. additional_highlights MUST derive ONLY from signal values in the provided JSON.
   Do not add statistical claims not present in the input.
5. If confidence < 0.4: set scam_type = "inconclusive", score_adjustment = 0.
6. DO NOT use hedged language like "This might be..." in highlights — write
   factual statements derived from signals: "Recipient received transfers from
   X senders in the last 2 hours" (where X is from velocity_cluster_size).
7. Highlights shown to account holders must be in plain Bahasa Malaysia-friendly
   English, empathetic in tone, factual, and action-oriented.

You MUST call the submit_fraud_assessment tool. Plain-text responses are invalid."""

_ASSESSMENT_TOOL: dict = {
    "name": "submit_fraud_assessment",
    "description": (
        "Submit the complete structured fraud intelligence assessment. "
        "This tool MUST be called — plain text responses are not accepted."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "scam_type": {
                "type": "string",
                "enum": [
                    "macau_scam",
                    "phishing_account_takeover",
                    "investment_pig_butchering",
                    "love_scam",
                    "mule_account_t1",
                    "mule_account_t2_t3",
                    "structuring_laundering",
                    "false_positive_likely",
                    "clean",
                    "inconclusive",
                ],
                "description": "Primary scam classification from the Malaysian fraud taxonomy.",
            },
            "mule_likelihood_band": {
                "type": "string",
                "enum": ["critical", "high", "medium", "low", "negligible"],
                "description": (
                    "Recipient mule likelihood band: critical >90%, high 70–90%, "
                    "medium 40–70%, low 15–40%, negligible <15%."
                ),
            },
            "semakmule_pattern_signal": {
                "type": "string",
                "enum": [
                    "matches_flagged_pattern",
                    "partial_match",
                    "no_match",
                    "insufficient_data",
                ],
                "description": (
                    "Pattern inference analogous to SemakMule risk signal. "
                    "NOT direct database access — observable signal pattern only."
                ),
            },
            "nsrc_correlation_signal": {
                "type": "string",
                "enum": [
                    "high_correlation",
                    "moderate_correlation",
                    "low_correlation",
                    "no_data",
                ],
                "description": (
                    "Correlation with NSRC 997 active campaign patterns based on "
                    "scam_report_count and velocity_cluster_size. Pattern inference only."
                ),
            },
            "score_adjustment": {
                "type": "integer",
                "description": (
                    "Integer points to add/subtract from rule score. "
                    "Range -15 to +15. If confidence < 0.5, range is clamped to -5 to +5."
                ),
            },
            "confidence": {
                "type": "number",
                "description": (
                    "Assessment confidence 0.0–1.0. "
                    "0.0–0.3 inconclusive, 0.4–0.6 moderate, 0.7–0.9 high, 1.0 near-certain."
                ),
            },
            "victim_scenario": {
                "type": "string",
                "enum": [
                    "sender_under_social_engineering_duress",
                    "sender_account_compromised_by_scammer",
                    "sender_is_willing_mule",
                    "recipient_is_mule_sender_is_victim",
                    "no_victim_scenario_detected",
                ],
                "description": "Most likely victim scenario — determines appropriate intervention copy.",
            },
            "intervention_recommendation": {
                "type": "string",
                "enum": [
                    "hard_block_refer_nsrc_997",
                    "hard_block_force_l1_stepup",
                    "hard_block_cooldown",
                    "warn_strong_reconfirm_biometric",
                    "warn_gentle_educational",
                    "allow_log_and_monitor",
                    "escalate_human_analyst",
                ],
                "description": "Recommended intervention tier aligned with ScamShield 3-tier response model.",
            },
            "additional_highlights": {
                "type": "array",
                "items": {"type": "string", "maxLength": 150},
                "maxItems": 3,
                "description": (
                    "Up to 3 factual risk highlights for display to account holder. "
                    "MUST derive only from provided signal values. "
                    "Do NOT invent statistics. Write in clear, empathetic English."
                ),
            },
            "analyst_reasoning": {
                "type": "string",
                "maxLength": 600,
                "description": (
                    "Internal chain-of-thought audit trail: explain signal-by-signal "
                    "reasoning across L1, L2, L3. For logging and compliance audit only. "
                    "Not shown to end user."
                ),
            },
        },
        "required": [
            "scam_type",
            "mule_likelihood_band",
            "semakmule_pattern_signal",
            "nsrc_correlation_signal",
            "score_adjustment",
            "confidence",
            "victim_scenario",
            "intervention_recommendation",
            "additional_highlights",
            "analyst_reasoning",
        ],
    },
}

# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

@dataclass
class AiAssessment:
    scam_type: str
    mule_likelihood_band: str
    semakmule_pattern_signal: str
    nsrc_correlation_signal: str
    score_adjustment: int
    confidence: float
    victim_scenario: str
    intervention_recommendation: str
    additional_highlights: list[str] = field(default_factory=list)
    analyst_reasoning: str = ""


# ---------------------------------------------------------------------------
# Client lifecycle
# ---------------------------------------------------------------------------

_client: anthropic.AnthropicBedrock | None = None


def _get_client() -> anthropic.AnthropicBedrock:
    global _client
    if _client is not None:
        return _client
    _client = anthropic.AnthropicBedrock(aws_region=settings.aws_region)
    return _client


# ---------------------------------------------------------------------------
# Cost-control gate
# ---------------------------------------------------------------------------

_AI_MIN_RULE_SCORE: int = 20
_AI_MIN_RISK_SIGNAL_COUNT: int = 2

_RISK_SIGNAL_KEYS: list[str] = [
    Feature.OTP_CONTEXT_IGNORED,
    Feature.ACCESSIBILITY_SERVICE_DETECTED,
    Feature.REBIND_IN_PROGRESS,
    Feature.WALLET_REBOUND_RECENTLY,
    Feature.STRUCTURING_PATTERN,
    Feature.NEW_DEVICE_LOGIN,
    Feature.DEVICE_IN_COOLDOWN,
    Feature.PASSWORD_CHANGED_WITHIN_24H,
    Feature.THIRD_PARTY_TOKENISATION,
    Feature.GEO_IP_SHIFT,
    Feature.TIME_OF_DAY_ANOMALY,
]


def _should_invoke_ai(features: dict, rule_score: int) -> bool:
    if rule_score < _AI_MIN_RULE_SCORE:
        return False

    mule_signal = float(features.get(Feature.RECIPIENT_MULE_LIKELIHOOD, 0.0)) >= 0.3
    velocity_signal = int(features.get(Feature.VELOCITY_CLUSTER_SIZE, 0)) >= 5
    report_signal = int(features.get(Feature.SCAM_REPORT_COUNT, 0)) >= 1
    new_recip_signal = bool(features.get(Feature.NEW_RECIPIENT, False))

    boolean_active = sum(bool(features.get(k, False)) for k in _RISK_SIGNAL_KEYS)
    l3_active = sum([mule_signal, velocity_signal, report_signal])

    return (boolean_active + l3_active + int(new_recip_signal)) >= _AI_MIN_RISK_SIGNAL_COUNT


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------

def _build_payload(features: dict, rule_score: int, rule_verdict: str) -> str:
    return json.dumps(
        {
            "scamshield_scoring_request": {
                "rule_based_score": rule_score,
                "rule_verdict": rule_verdict,
                "layer_1_identity_session": {
                    "device_trusted": bool(features.get(Feature.DEVICE_TRUSTED, False)),
                    "new_device_login": bool(features.get(Feature.NEW_DEVICE_LOGIN, False)),
                    "device_in_cooldown": bool(features.get(Feature.DEVICE_IN_COOLDOWN, False)),
                    "otp_issued_within_5min": bool(features.get(Feature.OTP_ISSUED_WITHIN_5MIN, False)),
                    "otp_context_ignored_stop_reply": bool(features.get(Feature.OTP_CONTEXT_IGNORED, False)),
                    "password_changed_within_24h": bool(features.get(Feature.PASSWORD_CHANGED_WITHIN_24H, False)),
                    "accessibility_service_detected": bool(features.get(Feature.ACCESSIBILITY_SERVICE_DETECTED, False)),
                    "rebind_in_progress": bool(features.get(Feature.REBIND_IN_PROGRESS, False)),
                    "geo_ip_region_shift": bool(features.get(Feature.GEO_IP_SHIFT, False)),
                },
                "layer_2_transaction_behaviour": {
                    "amount_myr": float(features.get(Feature.AMOUNT_RAW, 0.0)),
                    "amount_zscore_vs_history": round(float(features.get(Feature.AMOUNT_ZSCORE, 0.0)), 3),
                    "new_recipient": bool(features.get(Feature.NEW_RECIPIENT, False)),
                    "prior_transfer_count_to_recipient": int(features.get(Feature.PRIOR_TRANSFER_COUNT, 0)),
                    "recipient_is_in_contacts": bool(features.get(Feature.RECIPIENT_IN_CONTACTS, False)),
                    "time_of_day_anomaly": bool(features.get(Feature.TIME_OF_DAY_ANOMALY, False)),
                    "third_party_platform_link": bool(features.get(Feature.THIRD_PARTY_TOKENISATION, False)),
                    "card_bound_recently": bool(features.get(Feature.CARD_BOUND_RECENTLY, False)),
                    "wallet_rebound_recently": bool(features.get(Feature.WALLET_REBOUND_RECENTLY, False)),
                    "bnm_structuring_pattern_detected": bool(features.get(Feature.STRUCTURING_PATTERN, False)),
                },
                "layer_3_mule_network_graph": {
                    "recipient_mule_likelihood_score": round(
                        float(features.get(Feature.RECIPIENT_MULE_LIKELIHOOD, 0.0)), 3
                    ),
                    "recipient_mule_cluster_tag": features.get("recipient_mule_pattern_tag"),
                    "velocity_cluster_size_2h_window": int(features.get(Feature.VELOCITY_CLUSTER_SIZE, 0)),
                    "recipient_account_age_days": int(features.get(Feature.RECIPIENT_ACCOUNT_AGE_DAYS, 999)),
                    "scam_report_count_in_scamshield_db": int(features.get(Feature.SCAM_REPORT_COUNT, 0)),
                },
            }
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# API call (runs in thread for timeout control)
# ---------------------------------------------------------------------------

def _call_api(client: anthropic.AnthropicBedrock, model: str, payload: str) -> AiAssessment | None:
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[_ASSESSMENT_TOOL],
        tool_choice={"type": "tool", "name": "submit_fraud_assessment"},
        messages=[{"role": "user", "content": payload}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_fraud_assessment":
            return _parse_tool_output(block.input)

    return None


def _parse_tool_output(raw: dict) -> AiAssessment:
    adj = int(raw.get("score_adjustment", 0))
    conf = float(raw.get("confidence", 0.0))
    if conf < 0.5:
        adj = max(-5, min(5, adj))
    adj = max(-15, min(15, adj))

    return AiAssessment(
        scam_type=str(raw.get("scam_type", "inconclusive")),
        mule_likelihood_band=str(raw.get("mule_likelihood_band", "negligible")),
        semakmule_pattern_signal=str(raw.get("semakmule_pattern_signal", "insufficient_data")),
        nsrc_correlation_signal=str(raw.get("nsrc_correlation_signal", "no_data")),
        score_adjustment=adj,
        confidence=conf,
        victim_scenario=str(raw.get("victim_scenario", "no_victim_scenario_detected")),
        intervention_recommendation=str(raw.get("intervention_recommendation", "allow_log_and_monitor")),
        additional_highlights=list(raw.get("additional_highlights", []))[:3],
        analyst_reasoning=str(raw.get("analyst_reasoning", ""))[:600],
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_ai_assessment(
    features: dict,
    rule_score: int,
    rule_verdict: str,
    model: str = "anthropic.claude-haiku-4-5-20251001-v1:0",
    timeout_seconds: float = 3.0,
) -> AiAssessment | None:
    client = _get_client()

    if not _should_invoke_ai(features, rule_score):
        log.debug("ai_engine.skipped", rule_score=rule_score, reason="below_threshold")
        return None

    payload = _build_payload(features, rule_score, rule_verdict)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call_api, client, model, payload)
            assessment = future.result(timeout=timeout_seconds)

        if assessment is None:
            return None

        log.info(
            "ai_engine.assessment",
            scam_type=assessment.scam_type,
            mule_band=assessment.mule_likelihood_band,
            semakmule=assessment.semakmule_pattern_signal,
            nsrc=assessment.nsrc_correlation_signal,
            score_adjustment=assessment.score_adjustment,
            confidence=round(assessment.confidence, 2),
            victim_scenario=assessment.victim_scenario,
            intervention=assessment.intervention_recommendation,
        )
        return assessment

    except FuturesTimeout:
        log.warning("ai_engine.timeout", timeout_s=timeout_seconds)
        return None
    except Exception as exc:
        log.error("ai_engine.error", error=str(exc)[:200])
        return None
