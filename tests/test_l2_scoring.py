from __future__ import annotations

import pytest

from app.schemas.transfer import FeatureContribution
from app.core.scoring.rules import (
    _apply_hard_fail_rules,
    _score_group_a,
    _score_group_b,
    _score_group_c,
    _score_group_d,
    apply_rules,
    verdict_from_score,
)
from app.core.scoring.weights import (
    DEFAULT_WEIGHTS,
    GROUP_MAX,
    Feature,
    GroupAWeights,
    GroupBWeights,
    GroupCWeights,
    GroupDWeights,
    HardFailRules,
    ScoringWeights,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _features(**overrides) -> dict:
    base: dict = {
        Feature.RECIPIENT_MULE_LIKELIHOOD: 0.0,
        Feature.VELOCITY_CLUSTER_SIZE: 0,
        Feature.RECIPIENT_ACCOUNT_AGE_DAYS: 365,
        Feature.SCAM_REPORT_COUNT: 0,
        Feature.RECIPIENT_IN_CONTACTS: False,
        Feature.AMOUNT_ZSCORE: 0.0,
        Feature.AMOUNT_RAW: 50.0,
        Feature.NEW_RECIPIENT: False,
        Feature.PRIOR_TRANSFER_COUNT: 5,
        Feature.TIME_OF_DAY_ANOMALY: False,
        Feature.GEO_IP_SHIFT: False,
        Feature.THIRD_PARTY_TOKENISATION: False,
        Feature.CARD_BOUND_RECENTLY: False,
        Feature.WALLET_REBOUND_RECENTLY: False,
        Feature.STRUCTURING_PATTERN: False,
        Feature.NEW_DEVICE_LOGIN: False,
        Feature.DEVICE_TRUSTED: True,
        Feature.DEVICE_IN_COOLDOWN: False,
        Feature.OTP_ISSUED_WITHIN_5MIN: False,
        Feature.OTP_CONTEXT_IGNORED: False,
        Feature.PASSWORD_CHANGED_WITHIN_24H: False,
        Feature.ACCESSIBILITY_SERVICE_DETECTED: False,
        Feature.REBIND_IN_PROGRESS: False,
        "recipient_mule_pattern_tag": None,
    }
    base.update(overrides)
    return base


def _w() -> ScoringWeights:
    return DEFAULT_WEIGHTS


# ---------------------------------------------------------------------------
# verdict_from_score
# ---------------------------------------------------------------------------

class TestVerdictFromScore:
    def test_zero_is_green(self):
        assert verdict_from_score(0) == "GREEN"

    def test_29_is_green(self):
        assert verdict_from_score(29) == "GREEN"

    def test_30_is_yellow(self):
        assert verdict_from_score(30) == "YELLOW"

    def test_69_is_yellow(self):
        assert verdict_from_score(69) == "YELLOW"

    def test_70_is_red(self):
        assert verdict_from_score(70) == "RED"

    def test_100_is_red(self):
        assert verdict_from_score(100) == "RED"


# ---------------------------------------------------------------------------
# Group A — Recipient mule-likelihood
# ---------------------------------------------------------------------------

class TestGroupA:
    def _score(self, **overrides) -> float:
        score, _, _ = _score_group_a(_features(**overrides), _w().group_a, GROUP_MAX)
        return score

    def _contribs(self, **overrides) -> list[FeatureContribution]:
        _, contribs, _ = _score_group_a(_features(**overrides), _w().group_a, GROUP_MAX)
        return contribs

    def _highlights(self, **overrides) -> list[str]:
        _, _, hl = _score_group_a(_features(**overrides), _w().group_a, GROUP_MAX)
        return hl

    def test_zero_signals_gives_zero(self):
        assert self._score() == 0.0

    def test_mule_likelihood_scales_proportionally(self):
        w = _w().group_a
        score_half = self._score(**{Feature.RECIPIENT_MULE_LIKELIHOOD: 0.5})
        score_full = self._score(**{Feature.RECIPIENT_MULE_LIKELIHOOD: 1.0})
        assert score_half == pytest.approx(0.5 * w.mule_likelihood_scale, abs=1)
        assert score_full == pytest.approx(w.mule_likelihood_scale, abs=1)

    def test_mule_likelihood_zero_adds_no_contribution(self):
        contribs = self._contribs(**{Feature.RECIPIENT_MULE_LIKELIHOOD: 0.0})
        assert not any("mule" in c.feature for c in contribs)

    def test_velocity_below_threshold_adds_nothing(self):
        w = _w().group_a
        score = self._score(**{Feature.VELOCITY_CLUSTER_SIZE: w.velocity_threshold})
        assert score == 0.0

    def test_velocity_above_threshold_adds_points(self):
        w = _w().group_a
        score = self._score(**{Feature.VELOCITY_CLUSTER_SIZE: w.velocity_threshold + 10})
        assert score > 0.0

    def test_velocity_capped_at_velocity_max(self):
        w = _w().group_a
        score_large = self._score(**{Feature.VELOCITY_CLUSTER_SIZE: 1000})
        score_max = self._score(**{Feature.VELOCITY_CLUSTER_SIZE: w.velocity_threshold + 100})
        assert score_large == score_max

    def test_new_account_within_threshold_adds_points(self):
        w = _w().group_a
        score = self._score(**{Feature.RECIPIENT_ACCOUNT_AGE_DAYS: w.new_account_days_threshold - 1})
        assert score >= w.new_account_pts

    def test_old_account_adds_no_age_points(self):
        w = _w().group_a
        score_with_old = self._score(**{Feature.RECIPIENT_ACCOUNT_AGE_DAYS: w.new_account_days_threshold + 1})
        score_baseline = self._score()
        assert score_with_old == score_baseline

    def test_scam_reports_add_proportional_points(self):
        w = _w().group_a
        score_one = self._score(**{Feature.SCAM_REPORT_COUNT: 1})
        assert score_one == pytest.approx(w.scam_report_pts_each, abs=1)

    def test_scam_reports_capped(self):
        w = _w().group_a
        score_many = self._score(**{Feature.SCAM_REPORT_COUNT: 1000})
        assert score_many == pytest.approx(w.scam_report_max, abs=1)

    def test_in_contacts_applies_discount(self):
        w = _w().group_a
        score_no_contact = self._score(**{Feature.RECIPIENT_MULE_LIKELIHOOD: 0.5})
        score_contact = self._score(**{
            Feature.RECIPIENT_MULE_LIKELIHOOD: 0.5,
            Feature.RECIPIENT_IN_CONTACTS: True,
        })
        assert score_contact < score_no_contact

    def test_in_contacts_with_no_risk_clamps_to_zero(self):
        score = self._score(**{Feature.RECIPIENT_IN_CONTACTS: True})
        assert score == 0.0

    def test_group_capped_at_group_max(self):
        score = self._score(**{
            Feature.RECIPIENT_MULE_LIKELIHOOD: 1.0,
            Feature.VELOCITY_CLUSTER_SIZE: 1000,
            Feature.RECIPIENT_ACCOUNT_AGE_DAYS: 0,
            Feature.SCAM_REPORT_COUNT: 1000,
        })
        assert score == GROUP_MAX

    def test_mule_pattern_tag_adds_highlight(self):
        hl = self._highlights(**{
            Feature.RECIPIENT_MULE_LIKELIHOOD: 0.9,
            "recipient_mule_pattern_tag": "MP-047",
        })
        assert any("MP-047" in h for h in hl)

    def test_velocity_adds_highlight(self):
        hl = self._highlights(**{Feature.VELOCITY_CLUSTER_SIZE: 20})
        assert any("20 users" in h for h in hl)

    def test_new_account_adds_highlight(self):
        hl = self._highlights(**{Feature.RECIPIENT_ACCOUNT_AGE_DAYS: 3})
        assert any("3 days" in h for h in hl)

    def test_scam_report_adds_highlight(self):
        hl = self._highlights(**{Feature.SCAM_REPORT_COUNT: 7})
        assert any("7 users" in h for h in hl)

    def test_all_contribs_have_valid_direction(self):
        contribs = self._contribs(**{
            Feature.RECIPIENT_MULE_LIKELIHOOD: 0.8,
            Feature.VELOCITY_CLUSTER_SIZE: 20,
            Feature.RECIPIENT_ACCOUNT_AGE_DAYS: 5,
            Feature.SCAM_REPORT_COUNT: 5,
        })
        for c in contribs:
            assert c.direction in ("positive", "negative")
            assert isinstance(c.contribution, int)


# ---------------------------------------------------------------------------
# Group B — User behaviour anomaly
# ---------------------------------------------------------------------------

class TestGroupB:
    def _score(self, **overrides) -> float:
        score, _, _ = _score_group_b(_features(**overrides), _w().group_b, GROUP_MAX)
        return score

    def _contribs(self, **overrides) -> list[FeatureContribution]:
        _, contribs, _ = _score_group_b(_features(**overrides), _w().group_b, GROUP_MAX)
        return contribs

    def _highlights(self, **overrides) -> list[str]:
        _, _, hl = _score_group_b(_features(**overrides), _w().group_b, GROUP_MAX)
        return hl

    def test_all_normal_clamps_to_zero_or_small_negative_discount(self):
        score = self._score()
        assert score == 0.0

    def test_positive_zscore_adds_points(self):
        score = self._score(**{Feature.AMOUNT_ZSCORE: 1.0})
        assert score > 0.0

    def test_negative_zscore_adds_nothing(self):
        w = _w().group_b
        score_neg = self._score(**{Feature.AMOUNT_ZSCORE: -2.0})
        score_zero = self._score(**{Feature.AMOUNT_ZSCORE: 0.0})
        assert score_neg == score_zero

    def test_zscore_capped_at_max(self):
        w = _w().group_b
        score_large = self._score(**{Feature.AMOUNT_ZSCORE: 100.0})
        assert score_large <= GROUP_MAX

    def test_new_recipient_adds_points(self):
        w = _w().group_b
        score = self._score(**{Feature.NEW_RECIPIENT: True, Feature.PRIOR_TRANSFER_COUNT: 0})
        assert score >= w.new_recipient_pts - w.time_in_pattern_discount

    def test_time_anomaly_adds_points_and_removes_discount(self):
        w = _w().group_b
        score_normal = self._score()
        score_anomaly = self._score(**{Feature.TIME_OF_DAY_ANOMALY: True})
        assert score_anomaly > score_normal

    def test_geo_ip_shift_adds_points(self):
        w = _w().group_b
        score = self._score(**{Feature.GEO_IP_SHIFT: True})
        assert score > 0.0

    def test_high_amount_above_threshold_adds_points(self):
        w = _w().group_b
        score_high = self._score(**{Feature.AMOUNT_RAW: w.high_amount_threshold_myr + 1, Feature.PRIOR_TRANSFER_COUNT: 0})
        score_low = self._score(**{Feature.AMOUNT_RAW: w.high_amount_threshold_myr - 1, Feature.PRIOR_TRANSFER_COUNT: 0})
        assert score_high > score_low

    def test_high_amount_below_threshold_adds_nothing(self):
        w = _w().group_b
        score = self._score(**{Feature.AMOUNT_RAW: w.high_amount_threshold_myr - 1})
        assert score == 0.0

    def test_repeat_transfer_applies_discount(self):
        w = _w().group_b
        score_repeat = self._score(**{Feature.PRIOR_TRANSFER_COUNT: w.repeat_transfer_threshold})
        score_baseline = self._score(**{Feature.PRIOR_TRANSFER_COUNT: 0})
        assert score_repeat <= score_baseline

    def test_group_capped_at_group_max(self):
        score = self._score(**{
            Feature.AMOUNT_ZSCORE: 100.0,
            Feature.NEW_RECIPIENT: True,
            Feature.TIME_OF_DAY_ANOMALY: True,
            Feature.GEO_IP_SHIFT: True,
            Feature.AMOUNT_RAW: 100_000.0,
        })
        assert score == GROUP_MAX

    def test_geo_ip_shift_adds_highlight(self):
        hl = self._highlights(**{Feature.GEO_IP_SHIFT: True})
        assert any("geographic" in h.lower() for h in hl)

    def test_time_anomaly_adds_highlight(self):
        hl = self._highlights(**{Feature.TIME_OF_DAY_ANOMALY: True})
        assert any("unusual time" in h.lower() for h in hl)

    def test_repeat_transfer_adds_highlight(self):
        w = _w().group_b
        hl = self._highlights(**{Feature.PRIOR_TRANSFER_COUNT: w.repeat_transfer_threshold + 1})
        assert any("previous transfers" in h for h in hl)


# ---------------------------------------------------------------------------
# Group C — Transaction context
# ---------------------------------------------------------------------------

class TestGroupC:
    def _score(self, **overrides) -> float:
        score, _, _ = _score_group_c(_features(**overrides), _w().group_c, GROUP_MAX)
        return score

    def _contribs(self, **overrides) -> list[FeatureContribution]:
        _, contribs, _ = _score_group_c(_features(**overrides), _w().group_c, GROUP_MAX)
        return contribs

    def _highlights(self, **overrides) -> list[str]:
        _, _, hl = _score_group_c(_features(**overrides), _w().group_c, GROUP_MAX)
        return hl

    def test_no_context_signals_gives_zero(self):
        assert self._score() == 0.0

    def test_third_party_tokenisation_adds_points(self):
        w = _w().group_c
        score = self._score(**{Feature.THIRD_PARTY_TOKENISATION: True})
        assert score == pytest.approx(w.third_party_pts)

    def test_third_party_tokenisation_false_adds_nothing(self):
        assert self._score(**{Feature.THIRD_PARTY_TOKENISATION: False}) == 0.0

    def test_card_bound_recently_adds_points(self):
        w = _w().group_c
        score = self._score(**{Feature.CARD_BOUND_RECENTLY: True})
        assert score == pytest.approx(w.card_bound_pts)

    def test_wallet_rebound_recently_adds_points(self):
        w = _w().group_c
        score = self._score(**{Feature.WALLET_REBOUND_RECENTLY: True})
        assert score == pytest.approx(w.wallet_rebound_pts)

    def test_structuring_pattern_adds_heavy_points(self):
        w = _w().group_c
        score = self._score(**{Feature.STRUCTURING_PATTERN: True})
        assert score == pytest.approx(w.structuring_pts)

    def test_all_context_signals_capped_at_group_max(self):
        score = self._score(**{
            Feature.THIRD_PARTY_TOKENISATION: True,
            Feature.CARD_BOUND_RECENTLY: True,
            Feature.WALLET_REBOUND_RECENTLY: True,
            Feature.STRUCTURING_PATTERN: True,
        })
        assert score == GROUP_MAX

    def test_structuring_adds_highlight(self):
        hl = self._highlights(**{Feature.STRUCTURING_PATTERN: True})
        assert any("BNM" in h for h in hl)

    def test_wallet_rebound_adds_highlight(self):
        hl = self._highlights(**{Feature.WALLET_REBOUND_RECENTLY: True})
        assert any("rebound" in h.lower() for h in hl)

    def test_third_party_adds_highlight(self):
        hl = self._highlights(**{Feature.THIRD_PARTY_TOKENISATION: True})
        assert any("external platform" in h.lower() for h in hl)

    def test_structuring_alone_reaches_60pct_of_group_max(self):
        w = _w().group_c
        score = self._score(**{Feature.STRUCTURING_PATTERN: True})
        assert score >= 0.6 * GROUP_MAX

    def test_all_contribs_are_positive_direction(self):
        contribs = self._contribs(**{
            Feature.THIRD_PARTY_TOKENISATION: True,
            Feature.CARD_BOUND_RECENTLY: True,
        })
        assert all(c.direction == "positive" for c in contribs)


# ---------------------------------------------------------------------------
# Group D — Session signals
# ---------------------------------------------------------------------------

class TestGroupD:
    def _score(self, **overrides) -> float:
        score, _, _ = _score_group_d(_features(**overrides), _w().group_d, GROUP_MAX)
        return score

    def _contribs(self, **overrides) -> list[FeatureContribution]:
        _, contribs, _ = _score_group_d(_features(**overrides), _w().group_d, GROUP_MAX)
        return contribs

    def _highlights(self, **overrides) -> list[str]:
        _, _, hl = _score_group_d(_features(**overrides), _w().group_d, GROUP_MAX)
        return hl

    def test_clean_session_gives_zero(self):
        assert self._score() == 0.0

    def test_trusted_device_gives_zero(self):
        assert self._score(**{Feature.DEVICE_TRUSTED: True}) == 0.0

    def test_untrusted_device_adds_points(self):
        w = _w().group_d
        score = self._score(**{Feature.DEVICE_TRUSTED: False})
        assert score == pytest.approx(w.device_untrusted_pts)

    def test_new_device_login_adds_points(self):
        w = _w().group_d
        score = self._score(**{Feature.NEW_DEVICE_LOGIN: True})
        assert score == pytest.approx(w.new_device_pts)

    def test_device_in_cooldown_adds_heavy_points(self):
        w = _w().group_d
        score = self._score(**{Feature.DEVICE_IN_COOLDOWN: True})
        assert score == pytest.approx(w.device_in_cooldown_pts)

    def test_otp_within_5min_adds_points(self):
        w = _w().group_d
        score = self._score(**{Feature.OTP_ISSUED_WITHIN_5MIN: True})
        assert score == pytest.approx(w.otp_within_5min_pts)

    def test_otp_context_ignored_is_heaviest_single_signal(self):
        w = _w().group_d
        score = self._score(**{Feature.OTP_CONTEXT_IGNORED: True})
        assert score == pytest.approx(w.otp_context_ignored_pts)
        assert w.otp_context_ignored_pts >= w.new_device_pts
        assert w.otp_context_ignored_pts >= w.otp_within_5min_pts
        assert w.otp_context_ignored_pts >= w.password_changed_pts

    def test_password_changed_recently_adds_points(self):
        w = _w().group_d
        score = self._score(**{Feature.PASSWORD_CHANGED_WITHIN_24H: True})
        assert score == pytest.approx(w.password_changed_pts)

    def test_accessibility_adds_heavy_points(self):
        w = _w().group_d
        score = self._score(**{Feature.ACCESSIBILITY_SERVICE_DETECTED: True})
        assert score == pytest.approx(w.accessibility_pts)

    def test_rebind_in_progress_adds_points(self):
        w = _w().group_d
        score = self._score(**{Feature.REBIND_IN_PROGRESS: True})
        assert score == pytest.approx(w.rebind_pts)

    def test_all_session_signals_capped_at_group_max(self):
        score = self._score(**{
            Feature.NEW_DEVICE_LOGIN: True,
            Feature.DEVICE_TRUSTED: False,
            Feature.DEVICE_IN_COOLDOWN: True,
            Feature.OTP_ISSUED_WITHIN_5MIN: True,
            Feature.OTP_CONTEXT_IGNORED: True,
            Feature.PASSWORD_CHANGED_WITHIN_24H: True,
            Feature.ACCESSIBILITY_SERVICE_DETECTED: True,
            Feature.REBIND_IN_PROGRESS: True,
        })
        assert score == GROUP_MAX

    def test_device_in_cooldown_adds_highlight(self):
        hl = self._highlights(**{Feature.DEVICE_IN_COOLDOWN: True})
        assert any("cooldown" in h.lower() for h in hl)

    def test_otp_ignored_adds_highlight(self):
        hl = self._highlights(**{Feature.OTP_CONTEXT_IGNORED: True})
        assert any("OTP" in h for h in hl)

    def test_accessibility_adds_highlight(self):
        hl = self._highlights(**{Feature.ACCESSIBILITY_SERVICE_DETECTED: True})
        assert any("accessibility" in h.lower() for h in hl)

    def test_all_contribs_have_int_contribution(self):
        contribs = self._contribs(**{
            Feature.NEW_DEVICE_LOGIN: True,
            Feature.OTP_CONTEXT_IGNORED: True,
        })
        assert all(isinstance(c.contribution, int) for c in contribs)


# ---------------------------------------------------------------------------
# Hard-fail rules
# ---------------------------------------------------------------------------

class TestHardFailRules:
    def _run(self, raw_score: float, **feature_overrides) -> tuple[float, list, list]:
        return _apply_hard_fail_rules(
            raw_score,
            _features(**feature_overrides),
            _w().hard_fail,
        )

    def test_no_conditions_score_unchanged(self):
        score, contribs, _ = self._run(30.0)
        assert score == 30.0
        assert contribs == []

    def test_mule_velocity_new_recipient_triggers_min_score(self):
        rules = _w().hard_fail
        score, contribs, _ = self._run(
            10.0,
            **{
                Feature.RECIPIENT_MULE_LIKELIHOOD: rules.mule_high_threshold,
                Feature.VELOCITY_CLUSTER_SIZE: rules.velocity_high_threshold,
                Feature.NEW_RECIPIENT: True,
            },
        )
        assert score == rules.mule_velocity_new_min_score
        assert any("hard-fail" in c.feature for c in contribs)

    def test_mule_velocity_new_recipient_does_not_lower_higher_score(self):
        rules = _w().hard_fail
        already_high = float(rules.mule_velocity_new_min_score + 10)
        score, _, _ = self._run(
            already_high,
            **{
                Feature.RECIPIENT_MULE_LIKELIHOOD: rules.mule_high_threshold,
                Feature.VELOCITY_CLUSTER_SIZE: rules.velocity_high_threshold,
                Feature.NEW_RECIPIENT: True,
            },
        )
        assert score == already_high

    def test_mule_below_threshold_does_not_trigger(self):
        rules = _w().hard_fail
        score, contribs, _ = self._run(
            10.0,
            **{
                Feature.RECIPIENT_MULE_LIKELIHOOD: rules.mule_high_threshold - 0.01,
                Feature.VELOCITY_CLUSTER_SIZE: rules.velocity_high_threshold,
                Feature.NEW_RECIPIENT: True,
            },
        )
        assert score == 10.0
        assert contribs == []

    def test_velocity_below_threshold_does_not_trigger(self):
        rules = _w().hard_fail
        score, contribs, _ = self._run(
            10.0,
            **{
                Feature.RECIPIENT_MULE_LIKELIHOOD: rules.mule_high_threshold,
                Feature.VELOCITY_CLUSTER_SIZE: rules.velocity_high_threshold - 1,
                Feature.NEW_RECIPIENT: True,
            },
        )
        assert score == 10.0

    def test_known_recipient_prevents_mule_velocity_trigger(self):
        rules = _w().hard_fail
        score, contribs, _ = self._run(
            10.0,
            **{
                Feature.RECIPIENT_MULE_LIKELIHOOD: rules.mule_high_threshold,
                Feature.VELOCITY_CLUSTER_SIZE: rules.velocity_high_threshold,
                Feature.NEW_RECIPIENT: False,
            },
        )
        assert score == 10.0

    def test_rebind_new_device_new_recipient_triggers(self):
        rules = _w().hard_fail
        score, contribs, _ = self._run(
            5.0,
            **{
                Feature.REBIND_IN_PROGRESS: True,
                Feature.NEW_DEVICE_LOGIN: True,
                Feature.NEW_RECIPIENT: True,
            },
        )
        assert score == rules.rebind_new_device_new_recipient_min_score
        assert any("rebind" in c.feature.lower() for c in contribs)

    def test_rebind_without_new_device_does_not_trigger(self):
        score, contribs, _ = self._run(
            5.0,
            **{
                Feature.REBIND_IN_PROGRESS: True,
                Feature.NEW_DEVICE_LOGIN: False,
                Feature.NEW_RECIPIENT: True,
            },
        )
        assert score == 5.0

    def test_otp_ignored_plus_accessibility_triggers(self):
        rules = _w().hard_fail
        score, contribs, _ = self._run(
            10.0,
            **{
                Feature.OTP_CONTEXT_IGNORED: True,
                Feature.ACCESSIBILITY_SERVICE_DETECTED: True,
            },
        )
        assert score == rules.otp_ignored_accessibility_min_score
        assert any("hard-fail" in c.feature for c in contribs)

    def test_otp_ignored_alone_does_not_trigger_hard_fail(self):
        rules = _w().hard_fail
        score, contribs, _ = self._run(
            10.0,
            **{Feature.OTP_CONTEXT_IGNORED: True},
        )
        assert score == 10.0

    def test_three_session_compromise_signals_trigger(self):
        rules = _w().hard_fail
        score, contribs, _ = self._run(
            5.0,
            **{
                Feature.OTP_ISSUED_WITHIN_5MIN: True,
                Feature.PASSWORD_CHANGED_WITHIN_24H: True,
                Feature.NEW_DEVICE_LOGIN: True,
            },
        )
        assert score == rules.session_compromise_min_score
        assert any("session compromise" in c.feature.lower() for c in contribs)

    def test_two_session_signals_does_not_trigger_compromise_rule(self):
        score, contribs, _ = self._run(
            5.0,
            **{
                Feature.OTP_ISSUED_WITHIN_5MIN: True,
                Feature.PASSWORD_CHANGED_WITHIN_24H: True,
            },
        )
        assert score == 5.0

    def test_five_session_signals_triggers_with_correct_count_in_message(self):
        rules = _w().hard_fail
        score, contribs, hl = self._run(
            5.0,
            **{
                Feature.OTP_ISSUED_WITHIN_5MIN: True,
                Feature.PASSWORD_CHANGED_WITHIN_24H: True,
                Feature.NEW_DEVICE_LOGIN: True,
                Feature.DEVICE_IN_COOLDOWN: True,
                Feature.REBIND_IN_PROGRESS: True,
            },
        )
        assert score >= rules.session_compromise_min_score
        assert any("5" in c.feature for c in contribs if "session compromise" in c.feature)

    def test_hard_fail_contribution_direction_is_positive(self):
        rules = _w().hard_fail
        _, contribs, _ = self._run(
            5.0,
            **{
                Feature.RECIPIENT_MULE_LIKELIHOOD: rules.mule_high_threshold,
                Feature.VELOCITY_CLUSTER_SIZE: rules.velocity_high_threshold,
                Feature.NEW_RECIPIENT: True,
            },
        )
        assert all(c.direction == "positive" for c in contribs)


# ---------------------------------------------------------------------------
# apply_rules — end-to-end scenario tests
# ---------------------------------------------------------------------------

class TestApplyRules:
    def test_returns_int_score_clamped_0_100(self):
        score, _, _ = apply_rules(_features())
        assert isinstance(score, int)
        assert 0 <= score <= 100

    def test_attribution_list_is_not_empty(self):
        _, contribs, _ = apply_rules(_features(**{
            Feature.RECIPIENT_MULE_LIKELIHOOD: 0.5,
        }))
        assert len(contribs) > 0

    def test_all_attribution_items_have_valid_shape(self):
        _, contribs, _ = apply_rules(_features(**{
            Feature.RECIPIENT_MULE_LIKELIHOOD: 0.5,
            Feature.NEW_RECIPIENT: True,
        }))
        for c in contribs:
            assert isinstance(c.feature, str)
            assert isinstance(c.contribution, int)
            assert c.direction in ("positive", "negative")

    def test_g1_profile_scores_green(self):
        features = _features(**{
            Feature.RECIPIENT_MULE_LIKELIHOOD: 0.05,
            Feature.VELOCITY_CLUSTER_SIZE: 0,
            Feature.RECIPIENT_ACCOUNT_AGE_DAYS: 365,
            Feature.SCAM_REPORT_COUNT: 0,
            Feature.RECIPIENT_IN_CONTACTS: True,
            Feature.AMOUNT_ZSCORE: 0.1,
            Feature.AMOUNT_RAW: 50.0,
            Feature.NEW_RECIPIENT: False,
            Feature.PRIOR_TRANSFER_COUNT: 8,
            Feature.TIME_OF_DAY_ANOMALY: False,
            Feature.GEO_IP_SHIFT: False,
            Feature.DEVICE_TRUSTED: True,
        })
        score, _, _ = apply_rules(features)
        assert score < 30, f"G1-like profile should be GREEN but got {score}"

    def test_r1_profile_scores_red_via_hard_fail(self):
        rules = _w().hard_fail
        features = _features(**{
            Feature.RECIPIENT_MULE_LIKELIHOOD: 0.92,
            Feature.VELOCITY_CLUSTER_SIZE: 19,
            Feature.RECIPIENT_ACCOUNT_AGE_DAYS: 3,
            Feature.SCAM_REPORT_COUNT: 7,
            Feature.NEW_RECIPIENT: True,
            Feature.RECIPIENT_IN_CONTACTS: False,
            Feature.AMOUNT_ZSCORE: 3.5,
            Feature.AMOUNT_RAW: 2000.0,
            Feature.DEVICE_TRUSTED: True,
            "recipient_mule_pattern_tag": "MP-047",
        })
        score, contribs, highlights = apply_rules(features)
        assert score >= 70, f"R1-like profile should be RED but got {score}"
        assert score >= rules.mule_velocity_new_min_score
        assert any("mule" in c.feature.lower() for c in contribs)

    def test_y1_profile_scores_yellow(self):
        features = _features(**{
            Feature.RECIPIENT_MULE_LIKELIHOOD: 0.15,
            Feature.VELOCITY_CLUSTER_SIZE: 0,
            Feature.RECIPIENT_ACCOUNT_AGE_DAYS: 5,
            Feature.SCAM_REPORT_COUNT: 0,
            Feature.NEW_RECIPIENT: True,
            Feature.RECIPIENT_IN_CONTACTS: False,
            Feature.AMOUNT_ZSCORE: 3.0,
            Feature.AMOUNT_RAW: 800.0,
            Feature.DEVICE_TRUSTED: True,
        })
        score, _, _ = apply_rules(features)
        assert 30 <= score < 70, f"Y1-like profile should be YELLOW but got {score}"

    def test_session_compromise_scenario_scores_yellow_minimum(self):
        rules = _w().hard_fail
        features = _features(**{
            Feature.NEW_DEVICE_LOGIN: True,
            Feature.OTP_ISSUED_WITHIN_5MIN: True,
            Feature.PASSWORD_CHANGED_WITHIN_24H: True,
        })
        score, _, _ = apply_rules(features)
        assert score >= rules.session_compromise_min_score

    def test_full_takeover_scenario_scores_red(self):
        features = _features(**{
            Feature.RECIPIENT_MULE_LIKELIHOOD: 0.9,
            Feature.VELOCITY_CLUSTER_SIZE: 20,
            Feature.NEW_RECIPIENT: True,
            Feature.OTP_CONTEXT_IGNORED: True,
            Feature.ACCESSIBILITY_SERVICE_DETECTED: True,
            Feature.REBIND_IN_PROGRESS: True,
            Feature.NEW_DEVICE_LOGIN: True,
        })
        score, _, _ = apply_rules(features)
        assert score >= 70

    def test_structuring_pattern_pushes_score_up(self):
        base_score, _, _ = apply_rules(_features())
        struct_score, _, _ = apply_rules(_features(**{Feature.STRUCTURING_PATTERN: True}))
        assert struct_score > base_score

    def test_wallet_rebound_plus_new_device_is_high_risk(self):
        features = _features(**{
            Feature.WALLET_REBOUND_RECENTLY: True,
            Feature.NEW_DEVICE_LOGIN: True,
            Feature.NEW_RECIPIENT: True,
            Feature.AMOUNT_RAW: 800.0,
        })
        score, _, _ = apply_rules(features)
        assert score >= 30

    def test_custom_weights_respected(self):
        zero_weights = ScoringWeights(
            group_a=GroupAWeights(mule_likelihood_scale=0.0),
            group_b=GroupBWeights(new_recipient_pts=0.0, amount_zscore_scale=0.0),
            group_c=GroupCWeights(),
            group_d=GroupDWeights(),
            hard_fail=HardFailRules(
                mule_high_threshold=2.0,
                velocity_high_threshold=10000,
                mule_velocity_new_min_score=0,
                otp_ignored_accessibility_min_score=0,
                session_compromise_signal_count=100,
                session_compromise_min_score=0,
                rebind_new_device_new_recipient_min_score=0,
            ),
        )
        score, _, _ = apply_rules(
            _features(**{
                Feature.RECIPIENT_MULE_LIKELIHOOD: 1.0,
                Feature.NEW_RECIPIENT: True,
            }),
            weights=zero_weights,
        )
        assert score == 0

    def test_score_is_stable_across_identical_calls(self):
        features = _features(**{
            Feature.RECIPIENT_MULE_LIKELIHOOD: 0.6,
            Feature.NEW_RECIPIENT: True,
            Feature.AMOUNT_ZSCORE: 2.0,
        })
        score1, _, _ = apply_rules(features)
        score2, _, _ = apply_rules(features)
        assert score1 == score2

    def test_highlights_list_is_returned(self):
        _, _, highlights = apply_rules(_features(**{
            Feature.RECIPIENT_MULE_LIKELIHOOD: 0.9,
            Feature.VELOCITY_CLUSTER_SIZE: 20,
            Feature.NEW_RECIPIENT: True,
            "recipient_mule_pattern_tag": "MP-047",
        }))
        assert isinstance(highlights, list)
        assert len(highlights) > 0


# ---------------------------------------------------------------------------
# Group weight symmetry — each group contributes equally
# ---------------------------------------------------------------------------

class TestGroupWeightSymmetry:
    def test_each_group_maxes_at_group_max(self):
        a_max, _, _ = _score_group_a(
            _features(**{
                Feature.RECIPIENT_MULE_LIKELIHOOD: 1.0,
                Feature.VELOCITY_CLUSTER_SIZE: 1000,
                Feature.RECIPIENT_ACCOUNT_AGE_DAYS: 0,
                Feature.SCAM_REPORT_COUNT: 1000,
            }),
            _w().group_a,
            GROUP_MAX,
        )
        b_max, _, _ = _score_group_b(
            _features(**{
                Feature.AMOUNT_ZSCORE: 100.0,
                Feature.NEW_RECIPIENT: True,
                Feature.TIME_OF_DAY_ANOMALY: True,
                Feature.GEO_IP_SHIFT: True,
                Feature.AMOUNT_RAW: 1_000_000.0,
            }),
            _w().group_b,
            GROUP_MAX,
        )
        c_max, _, _ = _score_group_c(
            _features(**{
                Feature.THIRD_PARTY_TOKENISATION: True,
                Feature.CARD_BOUND_RECENTLY: True,
                Feature.WALLET_REBOUND_RECENTLY: True,
                Feature.STRUCTURING_PATTERN: True,
            }),
            _w().group_c,
            GROUP_MAX,
        )
        d_max, _, _ = _score_group_d(
            _features(**{
                Feature.NEW_DEVICE_LOGIN: True,
                Feature.DEVICE_TRUSTED: False,
                Feature.DEVICE_IN_COOLDOWN: True,
                Feature.OTP_ISSUED_WITHIN_5MIN: True,
                Feature.OTP_CONTEXT_IGNORED: True,
                Feature.PASSWORD_CHANGED_WITHIN_24H: True,
                Feature.ACCESSIBILITY_SERVICE_DETECTED: True,
                Feature.REBIND_IN_PROGRESS: True,
            }),
            _w().group_d,
            GROUP_MAX,
        )
        assert a_max == GROUP_MAX
        assert b_max == GROUP_MAX
        assert c_max == GROUP_MAX
        assert d_max == GROUP_MAX

    def test_all_groups_max_gives_100(self):
        features = _features(**{
            Feature.RECIPIENT_MULE_LIKELIHOOD: 1.0,
            Feature.VELOCITY_CLUSTER_SIZE: 1000,
            Feature.RECIPIENT_ACCOUNT_AGE_DAYS: 0,
            Feature.SCAM_REPORT_COUNT: 1000,
            Feature.AMOUNT_ZSCORE: 100.0,
            Feature.NEW_RECIPIENT: True,
            Feature.TIME_OF_DAY_ANOMALY: True,
            Feature.GEO_IP_SHIFT: True,
            Feature.AMOUNT_RAW: 1_000_000.0,
            Feature.THIRD_PARTY_TOKENISATION: True,
            Feature.CARD_BOUND_RECENTLY: True,
            Feature.WALLET_REBOUND_RECENTLY: True,
            Feature.STRUCTURING_PATTERN: True,
            Feature.NEW_DEVICE_LOGIN: True,
            Feature.DEVICE_TRUSTED: False,
            Feature.DEVICE_IN_COOLDOWN: True,
            Feature.OTP_ISSUED_WITHIN_5MIN: True,
            Feature.OTP_CONTEXT_IGNORED: True,
            Feature.PASSWORD_CHANGED_WITHIN_24H: True,
            Feature.ACCESSIBILITY_SERVICE_DETECTED: True,
            Feature.REBIND_IN_PROGRESS: True,
        })
        score, _, _ = apply_rules(features)
        assert score == 100
