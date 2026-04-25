from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
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
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
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
    amount: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(String(255), default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
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
    reported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DemoScenario(Base):
    __tablename__ = "demo_scenarios"

    id: Mapped[str] = mapped_column(String(8), primary_key=True)
    sender_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    recipient_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    recipient_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recipient_display_name: Mapped[str] = mapped_column(String(128), default="")
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    expected_verdict: Mapped[str] = mapped_column(String(16))
    moment: Mapped[int] = mapped_column(Integer, default=0)


class SmsLure(Base):
    __tablename__ = "sms_lures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32), index=True)
    language: Mapped[str] = mapped_column(String(8), default="BM")
    active_from: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
