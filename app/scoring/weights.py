from dataclasses import dataclass, field
from enum import StrEnum


class Feature(StrEnum):
    RECIPIENT_MULE_LIKELIHOOD = "recipient_mule_likelihood"
    VELOCITY_CLUSTER_SIZE = "velocity_cluster_size"
    RECIPIENT_ACCOUNT_AGE_DAYS = "recipient_account_age_days"
    SCAM_REPORT_COUNT = "scam_report_count"
    RECIPIENT_IN_CONTACTS = "recipient_in_contacts"

    AMOUNT_ZSCORE = "amount_zscore"
    AMOUNT_RAW = "amount_raw"
    NEW_RECIPIENT = "new_recipient"
    PRIOR_TRANSFER_COUNT = "prior_transfer_count"
    TIME_OF_DAY_ANOMALY = "time_of_day_anomaly"
    GEO_IP_SHIFT = "geo_ip_shift"

    THIRD_PARTY_TOKENISATION = "third_party_tokenisation"
    CARD_BOUND_RECENTLY = "card_bound_recently"
    WALLET_REBOUND_RECENTLY = "wallet_rebound_recently"
    STRUCTURING_PATTERN = "structuring_pattern"

    NEW_DEVICE_LOGIN = "new_device_login"
    DEVICE_TRUSTED = "device_trusted"
    DEVICE_IN_COOLDOWN = "device_in_cooldown"
    OTP_ISSUED_WITHIN_5MIN = "otp_issued_within_5min"
    OTP_CONTEXT_IGNORED = "otp_context_ignored"
    PASSWORD_CHANGED_WITHIN_24H = "password_changed_within_24h"
    ACCESSIBILITY_SERVICE_DETECTED = "accessibility_service_detected"
    REBIND_IN_PROGRESS = "rebind_in_progress"


GROUP_MAX: float = 25.0


@dataclass(frozen=True)
class GroupAWeights:
    mule_likelihood_scale: float = 18.0
    velocity_threshold: int = 5
    velocity_pts_per_sender: float = 1.5
    velocity_max: float = 7.0
    new_account_days_threshold: int = 30
    new_account_pts: float = 6.0
    scam_report_pts_each: float = 0.5
    scam_report_max: float = 5.0
    in_contacts_discount: float = 10.0


@dataclass(frozen=True)
class GroupBWeights:
    amount_zscore_scale: float = 8.0
    amount_zscore_max: float = 13.0
    new_recipient_pts: float = 12.0
    time_anomaly_pts: float = 5.0
    time_in_pattern_discount: float = 2.0
    geo_ip_shift_pts: float = 7.0
    high_amount_threshold_myr: float = 500.0
    high_amount_pts: float = 5.0
    repeat_transfer_threshold: int = 3
    repeat_transfer_discount: float = 3.0


@dataclass(frozen=True)
class GroupCWeights:
    third_party_pts: float = 10.0
    card_bound_pts: float = 8.0
    wallet_rebound_pts: float = 12.0
    structuring_pts: float = 15.0


@dataclass(frozen=True)
class GroupDWeights:
    new_device_pts: float = 6.0
    device_untrusted_pts: float = 5.0
    device_in_cooldown_pts: float = 10.0
    otp_within_5min_pts: float = 5.0
    otp_context_ignored_pts: float = 15.0
    password_changed_pts: float = 7.0
    accessibility_pts: float = 12.0
    rebind_pts: float = 8.0


@dataclass(frozen=True)
class HardFailRules:
    mule_high_threshold: float = 0.8
    velocity_high_threshold: int = 15
    mule_velocity_new_min_score: int = 75
    otp_ignored_accessibility_min_score: int = 55
    session_compromise_signal_count: int = 3
    session_compromise_min_score: int = 60
    rebind_new_device_new_recipient_min_score: int = 75


@dataclass(frozen=True)
class ScoringWeights:
    group_a: GroupAWeights = field(default_factory=GroupAWeights)
    group_b: GroupBWeights = field(default_factory=GroupBWeights)
    group_c: GroupCWeights = field(default_factory=GroupCWeights)
    group_d: GroupDWeights = field(default_factory=GroupDWeights)
    hard_fail: HardFailRules = field(default_factory=HardFailRules)
    group_max: float = GROUP_MAX


DEFAULT_WEIGHTS = ScoringWeights()
