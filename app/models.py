from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    account_type: Mapped[str] = mapped_column(String(16), default="normal")
    mule_pattern_tag: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    mule_likelihood: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    trusted_device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    devices: Mapped[list["Device"]] = relationship(back_populates="user", cascade="all,delete")
    sent_transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="sender", foreign_keys="Transaction.sender_id",
    )
    received_transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="recipient", foreign_keys="Transaction.recipient_id",
    )


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(128), index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    geo_ip_region: Mapped[str] = mapped_column(String(64), default="Kuala Lumpur")
    trusted: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(back_populates="devices")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_txn_recipient_timestamp", "recipient_id", "timestamp"),
        Index("ix_txn_sender_timestamp", "sender_id", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sender_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    recipient_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    note: Mapped[str] = mapped_column(String(255), default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    feature_attribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    top_feature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    sender: Mapped[User] = relationship(back_populates="sent_transactions", foreign_keys=[sender_id])
    recipient: Mapped[User] = relationship(back_populates="received_transactions", foreign_keys=[recipient_id])


class ScamReport(Base):
    __tablename__ = "scam_reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    reporter_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reported_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    txn_id: Mapped[str | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class DemoScenario(Base):
    __tablename__ = "demo_scenarios"

    id: Mapped[str] = mapped_column(String(8), primary_key=True)
    sender_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    recipient_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    recipient_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recipient_display_name: Mapped[str] = mapped_column(String(128), default="")
    amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0.0)
    expected_verdict: Mapped[str] = mapped_column(String(16))
    moment: Mapped[int] = mapped_column(Integer, default=0)


class SmsLure(Base):
    __tablename__ = "sms_lures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32), index=True)
    language: Mapped[str] = mapped_column(String(8), default="BM")
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class OtpEvent(Base):
    __tablename__ = "otp_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    geo_ip_region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    device_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    resolved: Mapped[str | None] = mapped_column(String(16), nullable=True)

    user: Mapped["User"] = relationship(foreign_keys=[user_id])


class DeviceSession(Base):
    __tablename__ = "device_sessions"
    __table_args__ = (Index("ix_sessions_active", "user_id", "is_active"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    otp_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accessibility_service_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped["User"] = relationship(foreign_keys=[user_id])


class DeviceCooldown(Base):
    __tablename__ = "device_cooldowns"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    cooldown_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    reason: Mapped[str] = mapped_column(String(64), default="new_device")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    user: Mapped["User"] = relationship(foreign_keys=[user_id])


class RebindAttempt(Base):
    __tablename__ = "rebind_attempts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    friction_method: Mapped[str | None] = mapped_column(String(32), nullable=True)

    user: Mapped["User"] = relationship(foreign_keys=[user_id])


class TransactionContext(Base):
    __tablename__ = "transaction_contexts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), unique=True, index=True)
    third_party_tokenisation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    card_bound_recently: Mapped[bool] = mapped_column(Boolean, default=False)
    wallet_rebound_recently: Mapped[bool] = mapped_column(Boolean, default=False)
    merchant_category: Mapped[str | None] = mapped_column(String(32), nullable=True)

    transaction: Mapped["Transaction"] = relationship(foreign_keys=[transaction_id])


class MuleCluster(Base):
    __tablename__ = "mule_clusters"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tier: Mapped[str] = mapped_column(String(8), default="t1")
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_mule_likelihood: Mapped[float] = mapped_column(Float, default=0.0)
    last_refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    memberships: Mapped[list["MuleClusterMembership"]] = relationship(
        back_populates="cluster", cascade="all,delete"
    )


class MuleClusterMembership(Base):
    __tablename__ = "mule_cluster_memberships"
    __table_args__ = (UniqueConstraint("cluster_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cluster_id: Mapped[str] = mapped_column(
        ForeignKey("mule_clusters.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    cluster: Mapped["MuleCluster"] = relationship(back_populates="memberships")
    user: Mapped["User"] = relationship(foreign_keys=[user_id])


class PatternDetection(Base):
    __tablename__ = "pattern_detections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    pattern_type: Mapped[str] = mapped_column(String(32), index=True)
    value: Mapped[float] = mapped_column(Float)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    cluster_id: Mapped[str | None] = mapped_column(
        ForeignKey("mule_clusters.id"), nullable=True, index=True
    )

    node: Mapped["User"] = relationship(foreign_keys=[node_id])
    cluster: Mapped["MuleCluster | None"] = relationship(foreign_keys=[cluster_id])


class AiModelVersion(Base):
    __tablename__ = "ai_model_versions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_type: Mapped[str] = mapped_column(String(32))
    version_tag: Mapped[str] = mapped_column(String(32))
    artifact_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    deployed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    flags: Mapped[list["AiRiskFlag"]] = relationship(back_populates="model_version")


class AiRiskFlag(Base):
    __tablename__ = "ai_risk_flags"
    __table_args__ = (Index("ix_flags_entity", "entity_id", "flagged_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(16))
    flag_type: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(16))
    score_contribution: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    flagged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    model_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("ai_model_versions.id"), nullable=True, index=True
    )

    model_version: Mapped["AiModelVersion | None"] = relationship(back_populates="flags")
