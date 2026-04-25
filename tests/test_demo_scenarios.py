from __future__ import annotations

import pytest

from app.db import SessionLocal, init_db, is_empty
from app.schemas.transfer import ScoreTransferRequest
from app.core.scoring.service import score_transfer


@pytest.fixture(scope="module", autouse=True)
def _seeded_db():
    init_db(drop_first=True)
    if is_empty():
        from scripts.seed import seed
        seed()
    yield


def _req(sender: str, recipient_id: str, phone: str, amount: float) -> ScoreTransferRequest:
    return ScoreTransferRequest(
        sender_id=sender,
        recipient_id=recipient_id,
        recipient_phone=phone,
        amount=amount,
        device_fingerprint="test-device",
        timestamp_ms=0,
    )


def test_g1_green_via_override():
    with SessionLocal() as db:
        res = score_transfer(_req("demo_user_01", "contact_siti", "+60 12-345 6789", 50.0), db)
    assert res.verdict == "GREEN"
    assert 10 <= res.score <= 30


def test_r1_red_via_override():
    with SessionLocal() as db:
        res = score_transfer(_req("demo_user_01", "recipient_mule_01", "+60 11-XXXX 8712", 2000.0), db)
    assert res.verdict == "RED"
    assert 82 <= res.score <= 92
    top_features = [a.feature for a in res.attribution[:3]]
    assert any("mule-likelihood" in f for f in top_features)


def test_random_low_amount_friend_is_green():
    with SessionLocal() as db:
        res = score_transfer(_req("demo_user_01", "user_0010", "+60 12-0000 0010", 40.0), db)
    assert res.verdict in ("GREEN", "YELLOW")


def test_attribution_shape():
    with SessionLocal() as db:
        res = score_transfer(_req("demo_user_01", "recipient_mule_01", "+60 11-XXXX 8712", 2000.0), db)
    for item in res.attribution:
        assert item.direction in ("positive", "negative")
        assert isinstance(item.contribution, int)
        assert isinstance(item.feature, str)
