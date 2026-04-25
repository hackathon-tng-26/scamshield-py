from app.schemas.transfer import FeatureContribution, Verdict
from app.scoring.weights import (
    DEFAULT_WEIGHTS,
    Feature,
    GroupAWeights,
    GroupBWeights,
    GroupCWeights,
    GroupDWeights,
    HardFailRules,
    ScoringWeights,
)


def apply_rules(
    features: dict,
    weights: ScoringWeights = DEFAULT_WEIGHTS,
) -> tuple[int, list[FeatureContribution], list[str]]:
    a_score, a_contribs, a_highlights = _score_group_a(features, weights.group_a, weights.group_max)
    b_score, b_contribs, b_highlights = _score_group_b(features, weights.group_b, weights.group_max)
    c_score, c_contribs, c_highlights = _score_group_c(features, weights.group_c, weights.group_max)
    d_score, d_contribs, d_highlights = _score_group_d(features, weights.group_d, weights.group_max)

    raw = a_score + b_score + c_score + d_score

    final, hf_contribs, hf_highlights = _apply_hard_fail_rules(raw, features, weights.hard_fail)

    contribs = a_contribs + b_contribs + c_contribs + d_contribs + hf_contribs
    highlights = a_highlights + b_highlights + c_highlights + d_highlights + hf_highlights

    return max(0, min(100, int(round(final)))), contribs, highlights


def _score_group_a(
    features: dict,
    w: GroupAWeights,
    group_max: float,
) -> tuple[float, list[FeatureContribution], list[str]]:
    raw: float = 0.0
    contribs: list[FeatureContribution] = []
    highlights: list[str] = []

    mule_likelihood = float(features.get(Feature.RECIPIENT_MULE_LIKELIHOOD, 0.0))
    if mule_likelihood > 0.0:
        pts = mule_likelihood * w.mule_likelihood_scale
        raw += pts
        contribs.append(FeatureContribution(
            feature="recipient mule-likelihood (L3)",
            contribution=int(pts),
            direction="positive",
        ))
        tag = features.get("recipient_mule_pattern_tag")
        if tag:
            highlights.append(f"Matches mule-account pattern {tag}")

    velocity = int(features.get(Feature.VELOCITY_CLUSTER_SIZE, 0))
    if velocity > w.velocity_threshold:
        pts = min((velocity - w.velocity_threshold) * w.velocity_pts_per_sender, w.velocity_max)
        raw += pts
        contribs.append(FeatureContribution(
            feature=f"velocity cluster ({velocity} senders/2h)",
            contribution=int(pts),
            direction="positive",
        ))
        highlights.append(f"{velocity} users transferred to this number in the last 2 hours")

    age_days = int(features.get(Feature.RECIPIENT_ACCOUNT_AGE_DAYS, 999))
    if age_days <= w.new_account_days_threshold:
        raw += w.new_account_pts
        contribs.append(FeatureContribution(
            feature="recipient account created recently",
            contribution=int(w.new_account_pts),
            direction="positive",
        ))
        highlights.append(f"Account created {age_days} days ago")

    scam_count = int(features.get(Feature.SCAM_REPORT_COUNT, 0))
    if scam_count > 0:
        pts = min(scam_count * w.scam_report_pts_each, w.scam_report_max)
        raw += pts
        contribs.append(FeatureContribution(
            feature="scam reports against recipient",
            contribution=int(pts),
            direction="positive",
        ))
        highlights.append(f"{scam_count} users reported this recipient as a scam")

    if features.get(Feature.RECIPIENT_IN_CONTACTS, False):
        raw -= w.in_contacts_discount
        contribs.append(FeatureContribution(
            feature="recipient in sender contacts",
            contribution=int(w.in_contacts_discount),
            direction="negative",
        ))

    clamped = max(0.0, min(group_max, raw))
    return clamped, contribs, highlights


def _score_group_b(
    features: dict,
    w: GroupBWeights,
    group_max: float,
) -> tuple[float, list[FeatureContribution], list[str]]:
    raw: float = 0.0
    contribs: list[FeatureContribution] = []
    highlights: list[str] = []

    amount_zscore = float(features.get(Feature.AMOUNT_ZSCORE, 0.0))
    if amount_zscore > 0.0:
        pts = min(amount_zscore * w.amount_zscore_scale, w.amount_zscore_max)
        raw += pts
        contribs.append(FeatureContribution(
            feature="amount vs user history",
            contribution=int(pts),
            direction="positive",
        ))

    if features.get(Feature.NEW_RECIPIENT, False):
        raw += w.new_recipient_pts
        contribs.append(FeatureContribution(
            feature="new recipient",
            contribution=int(w.new_recipient_pts),
            direction="positive",
        ))

    if features.get(Feature.TIME_OF_DAY_ANOMALY, False):
        raw += w.time_anomaly_pts
        contribs.append(FeatureContribution(
            feature="time-of-day anomaly",
            contribution=int(w.time_anomaly_pts),
            direction="positive",
        ))
        highlights.append("Transaction at unusual time for this account")
    else:
        raw -= w.time_in_pattern_discount
        contribs.append(FeatureContribution(
            feature="time-of-day in-pattern",
            contribution=int(w.time_in_pattern_discount),
            direction="negative",
        ))

    if features.get(Feature.GEO_IP_SHIFT, False):
        raw += w.geo_ip_shift_pts
        contribs.append(FeatureContribution(
            feature="geo-IP region shift",
            contribution=int(w.geo_ip_shift_pts),
            direction="positive",
        ))
        highlights.append("Transaction from an unusual geographic region for this account")

    amount_raw = float(features.get(Feature.AMOUNT_RAW, 0.0))
    if amount_raw >= w.high_amount_threshold_myr:
        raw += w.high_amount_pts
        contribs.append(FeatureContribution(
            feature="high absolute amount",
            contribution=int(w.high_amount_pts),
            direction="positive",
        ))

    prior_count = int(features.get(Feature.PRIOR_TRANSFER_COUNT, 0))
    if prior_count >= w.repeat_transfer_threshold:
        raw -= w.repeat_transfer_discount
        contribs.append(FeatureContribution(
            feature="repeat transfer to recipient",
            contribution=int(w.repeat_transfer_discount),
            direction="negative",
        ))
        highlights.append(f"{prior_count} previous transfers to this person")

    clamped = max(0.0, min(group_max, raw))
    return clamped, contribs, highlights


def _score_group_c(
    features: dict,
    w: GroupCWeights,
    group_max: float,
) -> tuple[float, list[FeatureContribution], list[str]]:
    raw: float = 0.0
    contribs: list[FeatureContribution] = []
    highlights: list[str] = []

    if features.get(Feature.THIRD_PARTY_TOKENISATION, False):
        raw += w.third_party_pts
        contribs.append(FeatureContribution(
            feature="third-party tokenisation (external platform)",
            contribution=int(w.third_party_pts),
            direction="positive",
        ))
        highlights.append("Transaction initiated via external platform link")

    if features.get(Feature.CARD_BOUND_RECENTLY, False):
        raw += w.card_bound_pts
        contribs.append(FeatureContribution(
            feature="card bound recently",
            contribution=int(w.card_bound_pts),
            direction="positive",
        ))
        highlights.append("New card was bound to this account recently")

    if features.get(Feature.WALLET_REBOUND_RECENTLY, False):
        raw += w.wallet_rebound_pts
        contribs.append(FeatureContribution(
            feature="wallet rebound recently",
            contribution=int(w.wallet_rebound_pts),
            direction="positive",
        ))
        highlights.append("Wallet was rebound to a new device recently")

    if features.get(Feature.STRUCTURING_PATTERN, False):
        raw += w.structuring_pts
        contribs.append(FeatureContribution(
            feature="structuring pattern detected",
            contribution=int(w.structuring_pts),
            direction="positive",
        ))
        highlights.append("Recipient received multiple sub-RM10k amounts totalling above RM10k (BNM evasion pattern)")

    clamped = max(0.0, min(group_max, raw))
    return clamped, contribs, highlights


def _score_group_d(
    features: dict,
    w: GroupDWeights,
    group_max: float,
) -> tuple[float, list[FeatureContribution], list[str]]:
    raw: float = 0.0
    contribs: list[FeatureContribution] = []
    highlights: list[str] = []

    if features.get(Feature.NEW_DEVICE_LOGIN, False):
        raw += w.new_device_pts
        contribs.append(FeatureContribution(
            feature="new device login",
            contribution=int(w.new_device_pts),
            direction="positive",
        ))

    if not features.get(Feature.DEVICE_TRUSTED, True):
        raw += w.device_untrusted_pts
        contribs.append(FeatureContribution(
            feature="untrusted device",
            contribution=int(w.device_untrusted_pts),
            direction="positive",
        ))

    if features.get(Feature.DEVICE_IN_COOLDOWN, False):
        raw += w.device_in_cooldown_pts
        contribs.append(FeatureContribution(
            feature="device in new-device cooldown (L1)",
            contribution=int(w.device_in_cooldown_pts),
            direction="positive",
        ))
        highlights.append("Device is in new-device cooldown period")

    if features.get(Feature.OTP_ISSUED_WITHIN_5MIN, False):
        raw += w.otp_within_5min_pts
        contribs.append(FeatureContribution(
            feature="OTP issued < 5 min ago",
            contribution=int(w.otp_within_5min_pts),
            direction="positive",
        ))

    if features.get(Feature.OTP_CONTEXT_IGNORED, False):
        raw += w.otp_context_ignored_pts
        contribs.append(FeatureContribution(
            feature="OTP STOP reply detected (L1)",
            contribution=int(w.otp_context_ignored_pts),
            direction="positive",
        ))
        highlights.append("Previous OTP was blocked by account holder")

    if features.get(Feature.PASSWORD_CHANGED_WITHIN_24H, False):
        raw += w.password_changed_pts
        contribs.append(FeatureContribution(
            feature="password changed < 24h ago",
            contribution=int(w.password_changed_pts),
            direction="positive",
        ))

    if features.get(Feature.ACCESSIBILITY_SERVICE_DETECTED, False):
        raw += w.accessibility_pts
        contribs.append(FeatureContribution(
            feature="accessibility service detected",
            contribution=int(w.accessibility_pts),
            direction="positive",
        ))
        highlights.append("Accessibility service active — possible remote-control takeover")

    if features.get(Feature.REBIND_IN_PROGRESS, False):
        raw += w.rebind_pts
        contribs.append(FeatureContribution(
            feature="wallet rebind in progress",
            contribution=int(w.rebind_pts),
            direction="positive",
        ))

    clamped = max(0.0, min(group_max, raw))
    return clamped, contribs, highlights


def _apply_hard_fail_rules(
    raw_score: float,
    features: dict,
    rules: HardFailRules,
) -> tuple[float, list[FeatureContribution], list[str]]:
    score = raw_score
    contribs: list[FeatureContribution] = []
    highlights: list[str] = []

    mule_high = float(features.get(Feature.RECIPIENT_MULE_LIKELIHOOD, 0.0)) >= rules.mule_high_threshold
    velocity_high = int(features.get(Feature.VELOCITY_CLUSTER_SIZE, 0)) >= rules.velocity_high_threshold
    new_recip = bool(features.get(Feature.NEW_RECIPIENT, False))

    if mule_high and velocity_high and new_recip and score < rules.mule_velocity_new_min_score:
        contribs.append(FeatureContribution(
            feature="mule + velocity cluster + new recipient (hard-fail)",
            contribution=int(rules.mule_velocity_new_min_score - score),
            direction="positive",
        ))
        highlights.append("Recipient matches high-confidence mule pattern with active velocity cluster")
        score = rules.mule_velocity_new_min_score

    rebind = bool(features.get(Feature.REBIND_IN_PROGRESS, False))
    new_device = bool(features.get(Feature.NEW_DEVICE_LOGIN, False))

    if rebind and new_device and new_recip and score < rules.rebind_new_device_new_recipient_min_score:
        contribs.append(FeatureContribution(
            feature="rebind + new device + new recipient (hard-fail)",
            contribution=int(rules.rebind_new_device_new_recipient_min_score - score),
            direction="positive",
        ))
        highlights.append("Wallet rebind in progress from new device to new recipient")
        score = rules.rebind_new_device_new_recipient_min_score

    otp_ignored = bool(features.get(Feature.OTP_CONTEXT_IGNORED, False))
    accessibility = bool(features.get(Feature.ACCESSIBILITY_SERVICE_DETECTED, False))

    if otp_ignored and accessibility and score < rules.otp_ignored_accessibility_min_score:
        contribs.append(FeatureContribution(
            feature="OTP blocked + accessibility service (hard-fail)",
            contribution=int(rules.otp_ignored_accessibility_min_score - score),
            direction="positive",
        ))
        highlights.append("Account compromise: OTP blocked and accessibility service active simultaneously")
        score = rules.otp_ignored_accessibility_min_score

    session_signals = sum([
        bool(features.get(Feature.OTP_ISSUED_WITHIN_5MIN, False)),
        bool(features.get(Feature.PASSWORD_CHANGED_WITHIN_24H, False)),
        bool(features.get(Feature.NEW_DEVICE_LOGIN, False)),
        bool(features.get(Feature.DEVICE_IN_COOLDOWN, False)),
        bool(features.get(Feature.REBIND_IN_PROGRESS, False)),
    ])

    if session_signals >= rules.session_compromise_signal_count and score < rules.session_compromise_min_score:
        contribs.append(FeatureContribution(
            feature=f"{session_signals} concurrent session compromise signals (hard-fail)",
            contribution=int(rules.session_compromise_min_score - score),
            direction="positive",
        ))
        highlights.append(f"{session_signals} concurrent session compromise signals detected")
        score = rules.session_compromise_min_score

    return score, contribs, highlights


def verdict_from_score(score: int) -> Verdict:
    if score < 30:
        return "GREEN"
    if score < 70:
        return "YELLOW"
    return "RED"
