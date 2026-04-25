from app.schemas.transfer import FeatureContribution, Verdict


def apply_rules(features: dict) -> tuple[int, list[FeatureContribution], list[str]]:
    score: float = 50.0
    contribs: list[FeatureContribution] = [
        FeatureContribution(feature="baseline (user risk prior)", contribution=50, direction="positive")
    ]
    highlights: list[str] = []

    mule_likelihood = features.get("recipient_mule_likelihood", 0.0)
    if mule_likelihood >= 0.5:
        delta = int(40 * mule_likelihood)
        score += delta
        contribs.append(
            FeatureContribution(feature="recipient mule-likelihood (L3)", contribution=delta, direction="positive")
        )
        tag = features.get("recipient_mule_pattern_tag")
        if tag:
            highlights.append(f"Matches mule-account pattern {tag}")

    velocity = features.get("velocity_cluster_size", 0)
    if velocity >= 10:
        delta = min(35, int(velocity * 1.5))
        score += delta
        contribs.append(
            FeatureContribution(
                feature=f"velocity cluster ({velocity} senders/2h)", contribution=delta, direction="positive"
            )
        )
        highlights.append(f"{velocity} users transferred to this number in the last 2 hours")

    amount_z = features.get("amount_zscore", 0.0)
    if amount_z >= 1.0:
        delta = int(min(20, amount_z * 10))
        score += delta
        contribs.append(
            FeatureContribution(feature="amount vs user history", contribution=delta, direction="positive")
        )

    if features.get("new_recipient", False):
        score += 12
        contribs.append(FeatureContribution(feature="new recipient", contribution=12, direction="positive"))

    age_days = features.get("recipient_account_age_days", 999)
    if age_days <= 7:
        score += 10
        contribs.append(
            FeatureContribution(feature="recipient account created recently", contribution=10, direction="positive")
        )
        highlights.append(f"Account created {age_days} days ago")

    if features.get("time_of_day_in_pattern", False):
        score -= 8
        contribs.append(
            FeatureContribution(feature="time-of-day in-pattern", contribution=8, direction="negative")
        )

    if features.get("user_risk_history") == "clean":
        score -= 12
        contribs.append(
            FeatureContribution(feature="user own risk history", contribution=12, direction="negative")
        )

    prior = features.get("prior_transfer_count", 0)
    if prior >= 3:
        highlights.append(f"{prior} previous transfers to this person")

    # L1 Session signals (25% quadrant)
    if features.get("device_in_cooldown"):
        delta = 20
        score += delta
        contribs.append(FeatureContribution(feature="device in cooldown (L1)", contribution=delta, direction="positive"))
        highlights.append("Device is in new-device cooldown")

    if features.get("rebind_in_progress") and features.get("new_device_login") and features.get("new_recipient"):
        score = max(score, 85)
        contribs.append(
            FeatureContribution(feature="rebind + new device + new recipient (L1)", contribution=0, direction="positive")
        )
        highlights.append("Rebind in progress from new device to new recipient")

    if not features.get("device_trusted", True):
        delta = 10
        score += delta
        contribs.append(FeatureContribution(feature="untrusted device (L1)", contribution=delta, direction="positive"))

    if features.get("otp_context_ignored"):
        delta = 15
        score += delta
        contribs.append(FeatureContribution(feature="OTP STOP reply detected (L1)", contribution=delta, direction="positive"))
        highlights.append("Previous OTP was blocked by user")

    if features.get("otp_issued_within_5min"):
        delta = 5
        score += delta
        contribs.append(FeatureContribution(feature="OTP issued < 5 min ago", contribution=delta, direction="positive"))

    if features.get("password_changed_within_24h"):
        delta = 8
        score += delta
        contribs.append(FeatureContribution(feature="password changed < 24h ago", contribution=delta, direction="positive"))

    if features.get("accessibility_service_detected"):
        delta = 12
        score += delta
        contribs.append(FeatureContribution(feature="accessibility service detected", contribution=delta, direction="positive"))
        highlights.append("Accessibility service active — possible remote takeover")

    final = max(0, min(100, int(round(score))))
    return final, contribs, highlights


def verdict_from_score(score: int) -> Verdict:
    if score < 30:
        return "GREEN"
    if score < 70:
        return "YELLOW"
    return "RED"
