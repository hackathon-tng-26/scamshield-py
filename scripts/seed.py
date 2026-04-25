from __future__ import annotations

import random
from datetime import datetime, timedelta
from uuid import uuid4

from faker import Faker

from app.db import SessionLocal, init_db
from app.logger import get_logger
from app.models import (
    Device,
    DemoScenario,
    DeviceCooldown,
    OtpEvent,
    RebindAttempt,
    ScamReport,
    SmsLure,
    Transaction,
    User,
)

fake = Faker("id_ID")
Faker.seed(42)
random.seed(42)

log = get_logger("seed")


SPECIAL_USERS = {
    "demo_user_01": {
        "phone": "+60 12-345 0001",
        "name": "Wafi (demo user)",
        "account_type": "normal",
        "mule_likelihood": 0.02,
        "age_days": 400,
    },
    "contact_siti": {
        "phone": "+60 12-345 6789",
        "name": "Siti Aminah",
        "account_type": "normal",
        "mule_likelihood": 0.02,
        "age_days": 300,
    },
    "recipient_mule_01": {
        "phone": "+60 11-XXXX 8712",
        "name": "(new recipient)",
        "account_type": "mule",
        "mule_likelihood": 0.91,
        "age_days": 3,
        "mule_pattern_tag": "MP-047",
    },
    "new_recipient_22": {
        "phone": "+60 13-777 0022",
        "name": "New Recipient",
        "account_type": "normal",
        "mule_likelihood": 0.18,
        "age_days": 14,
    },
    "usdt_offramp_01": {
        "phone": "+00 00-0000 0001",
        "name": "USDT off-ramp",
        "account_type": "offramp",
        "mule_likelihood": 0.98,
        "age_days": 30,
    },
    "scammer_device_02": {
        "phone": "+60 11-SCAM 0002",
        "name": "Scammer (for L1 demo)",
        "account_type": "mule",
        "mule_likelihood": 0.75,
        "age_days": 1,
        "mule_pattern_tag": "MP-047",
    },
}


def seed() -> None:
    init_db(drop_first=True)
    with SessionLocal() as s:
        log.info("seed.special_users.begin")
        special_ids = seed_special_users(s)

        log.info("seed.normal_users.begin", target=200)
        normal_user_ids = generate_normal_users(s, n=200)

        log.info("seed.mule_cluster.begin", target="MP-047 + others")
        mule_ids = generate_mule_cluster(s, tag="MP-047", n=14)
        mule_ids += generate_mule_cluster(s, tag="MP-023", n=12)
        mule_ids += generate_mule_cluster(s, tag="MP-011", n=10)

        log.info("seed.devices.begin")
        seed_devices(s, list(special_ids) + normal_user_ids + mule_ids)

        log.info("seed.normal_txns.begin", target=1000)
        generate_normal_transactions(s, normal_user_ids, n=1000)

        log.info("seed.mule_txns.begin", target=300)
        generate_mule_transactions(s, normal_user_ids, mule_ids, n=300)

        log.info("seed.recipient_mule_01_fan_in.begin")
        seed_recipient_mule_01_fan_in(s, normal_user_ids)

        log.info("seed.scam_reports.begin", target=200)
        seed_scam_reports(s, normal_user_ids, mule_ids, n=200)

        log.info("seed.demo_scenarios.begin")
        seed_demo_scenarios(s)

        log.info("seed.sms_lures.begin")
        seed_sms_lures(s)

        log.info("seed.l1_devices.begin")
        seed_l1_devices(s)

        log.info("seed.l1_otp_sessions.begin")
        seed_l1_otp_and_sessions(s)

        s.commit()
        log.info(
            "seed.complete",
            users=s.query(User).count(),
            transactions=s.query(Transaction).count(),
            reports=s.query(ScamReport).count(),
            lures=s.query(SmsLure).count(),
        )


def seed_special_users(s) -> list[str]:
    now = datetime.utcnow()
    ids: list[str] = []
    for uid, spec in SPECIAL_USERS.items():
        u = User(
            id=uid,
            phone=spec["phone"],
            name=spec["name"],
            account_type=spec["account_type"],
            mule_likelihood=spec["mule_likelihood"],
            mule_pattern_tag=spec.get("mule_pattern_tag"),
            created_at=now - timedelta(days=int(spec["age_days"])),
        )
        s.add(u)
        ids.append(uid)
    return ids


def generate_normal_users(s, n: int = 200) -> list[str]:
    ids: list[str] = []
    for i in range(n):
        uid = f"user_{i:04d}"
        u = User(
            id=uid,
            phone=f"+60 {random.choice(['11','12','13','14','16','17','18','19'])}-{random.randint(1000,9999)} {random.randint(1000,9999)}",
            name=fake.name(),
            account_type="normal",
            mule_likelihood=round(random.uniform(0.0, 0.12), 3),
            created_at=datetime.utcnow() - timedelta(days=random.randint(30, 600)),
        )
        s.add(u)
        ids.append(uid)
    s.flush()
    return ids


def generate_mule_cluster(s, tag: str, n: int) -> list[str]:
    ids: list[str] = []
    for i in range(n):
        uid = f"mule_{tag}_{i:02d}"
        u = User(
            id=uid,
            phone=f"+60 1{random.randint(1,9)}-MULE {random.randint(1000,9999)}",
            name=f"Mule {tag} #{i}",
            account_type="mule",
            mule_pattern_tag=tag,
            mule_likelihood=round(random.uniform(0.70, 0.95), 3),
            created_at=datetime.utcnow() - timedelta(days=random.randint(1, 14)),
        )
        s.add(u)
        ids.append(uid)
    s.flush()
    return ids


def seed_devices(s, user_ids: list[str]) -> None:
    for uid in user_ids:
        d = Device(
            id=f"dev_{uid}",
            user_id=uid,
            fingerprint=f"fp-{uuid4().hex[:16]}",
            first_seen=datetime.utcnow() - timedelta(days=random.randint(1, 500)),
            geo_ip_region=random.choice(
                ["Kuala Lumpur", "Selangor", "Penang", "Johor Bahru", "Ipoh", "Melaka"]
            ),
            trusted=True,
        )
        s.add(d)


def generate_normal_transactions(s, user_ids: list[str], n: int = 1000) -> None:
    for _ in range(n):
        sender = random.choice(user_ids)
        recipient = random.choice([u for u in user_ids if u != sender])
        amount = round(abs(random.lognormvariate(mu=3.5, sigma=1.2)), 2)
        if amount > 5_000:
            amount = round(random.uniform(5.0, 500.0), 2)
        score = random.randint(5, 30)
        ts = datetime.utcnow() - timedelta(minutes=random.randint(1, 30 * 24 * 60))
        txn = Transaction(
            id=f"tx-{uuid4().hex[:12]}",
            sender_id=sender,
            recipient_id=recipient,
            amount=amount,
            timestamp=ts,
            risk_score=score,
            verdict="GREEN",
        )
        s.add(txn)


def generate_mule_transactions(s, normal_user_ids: list[str], mule_ids: list[str], n: int = 300) -> None:
    for _ in range(n):
        sender = random.choice(normal_user_ids)
        recipient = random.choice(mule_ids)
        amount = round(random.uniform(50.0, 2_500.0), 2)
        score = random.randint(60, 95)
        verdict = "RED" if score >= 70 else "YELLOW"
        ts = datetime.utcnow() - timedelta(minutes=random.randint(1, 48 * 60))
        txn = Transaction(
            id=f"tx-{uuid4().hex[:12]}",
            sender_id=sender,
            recipient_id=recipient,
            amount=amount,
            timestamp=ts,
            risk_score=score,
            verdict=verdict,
            top_feature="recipient mule-likelihood (L3)",
        )
        s.add(txn)


def seed_recipient_mule_01_fan_in(s, normal_user_ids: list[str]) -> None:
    chosen = random.sample(normal_user_ids, k=min(19, len(normal_user_ids)))
    now = datetime.utcnow()
    for i, sender in enumerate(chosen):
        ts = now - timedelta(minutes=random.randint(1, 110))
        txn = Transaction(
            id=f"tx-fanin-{i:02d}",
            sender_id=sender,
            recipient_id="recipient_mule_01",
            amount=round(random.uniform(80.0, 2_200.0), 2),
            timestamp=ts,
            risk_score=random.randint(78, 92),
            verdict="RED",
            top_feature="velocity cluster (19 senders/2h)",
        )
        s.add(txn)


def seed_scam_reports(s, normal_user_ids: list[str], mule_ids: list[str], n: int = 200) -> None:
    reporters = random.sample(normal_user_ids, k=min(7, len(normal_user_ids)))
    for i, reporter in enumerate(reporters):
        r = ScamReport(
            id=f"report-mule01-{i:02d}",
            reporter_id=reporter,
            reported_user_id="recipient_mule_01",
            txn_id=None,
            reported_at=datetime.utcnow() - timedelta(hours=random.randint(1, 72)),
        )
        s.add(r)

    for i in range(n - 7):
        reporter = random.choice(normal_user_ids)
        reported = random.choice(mule_ids)
        r = ScamReport(
            id=f"report-{i:03d}",
            reporter_id=reporter,
            reported_user_id=reported,
            reported_at=datetime.utcnow() - timedelta(days=random.randint(0, 30)),
        )
        s.add(r)


def seed_demo_scenarios(s) -> None:
    rows = [
        DemoScenario(
            id="G1",
            sender_id="demo_user_01",
            recipient_id="contact_siti",
            recipient_phone="+60 12-345 6789",
            recipient_display_name="Siti Aminah",
            amount=50.0,
            expected_verdict="GREEN",
            moment=1,
        ),
        DemoScenario(
            id="Y1",
            sender_id="demo_user_01",
            recipient_id="new_recipient_22",
            recipient_phone="+60 13-777 0022",
            recipient_display_name="New Recipient",
            amount=800.0,
            expected_verdict="YELLOW",
            moment=1,
        ),
        DemoScenario(
            id="R1",
            sender_id="demo_user_01",
            recipient_id="recipient_mule_01",
            recipient_phone="+60 11-XXXX 8712",
            recipient_display_name="(new recipient)",
            amount=2000.0,
            expected_verdict="RED",
            moment=2,
        ),
        DemoScenario(
            id="L1",
            sender_id="scammer_device_02",
            recipient_id=None,
            recipient_phone=None,
            recipient_display_name="(L1 cooldown demo)",
            amount=0.0,
            expected_verdict="BLOCKED",
            moment=3,
        ),
    ]
    for r in rows:
        s.add(r)


def seed_sms_lures(s) -> None:
    lures = [
        ("Tahniah! Anda layak menerima RM500 dari Bantuan Rahmah. Semak sekarang: bit.ly/str-kelayakan", "B40", "BM"),
        ("MySejahtera: RM800 credit ready to claim. Click here within 24h: tng-rewards.co/claim", "MySejahtera", "EN"),
        ("JPJ: Saman anda boleh dibayar dengan diskaun 50% hari ini. Bayar di: jpj-saman.my.co", "JPJ", "BM"),
        ("LHDN refund RM{amount} siap dituntut. Sila maklum nombor bank: lhdn-refund.com", "LHDN", "BM"),
        ("Rahmah Raya: Ang pow RM250 dari kerajaan. Tekan untuk tuntut sekarang.", "political", "BM"),
        ("Your TNG eWallet account will be suspended. Verify now: tng-digital.my.co", "account-suspend", "EN"),
        ("RON95 petrol subsidy cashback RM150 ready. Claim via tng-subsidy.my", "RON95", "rojak"),
    ]
    for template, category, lang in lures:
        s.add(SmsLure(template=template, category=category, language=lang))


def seed_l1_devices(s) -> None:
    now = datetime.utcnow()

    # Trusted device for demo_user_01 (victim on their own phone)
    trusted_dev = Device(
        id="dev-trusted-s21",
        user_id="demo_user_01",
        fingerprint="trusted-samsung-s21",
        first_seen=now - timedelta(days=180),
        geo_ip_region="Kuala Lumpur",
        trusted=True,
    )
    s.add(trusted_dev)

    # Update user's trusted_device_id
    user = s.query(User).filter(User.id == "demo_user_01").first()
    if user:
        user.trusted_device_id = trusted_dev.id

    # New untrusted device for scammer (simulates scammer's phone)
    scammer_dev = Device(
        id="dev-scammer-s24",
        user_id="scammer_device_02",
        fingerprint="scammer-samsung-s24",
        first_seen=now,
        geo_ip_region="Johor Bahru",
        trusted=False,
    )
    s.add(scammer_dev)

    # Explicit cooldown for scammer device
    s.add(
        DeviceCooldown(
            id="cd-scammer-s24",
            user_id="scammer_device_02",
            device_id=scammer_dev.id,
            cooldown_until=now + timedelta(hours=24),
            reason="new_device",
            created_at=now,
        )
    )


def seed_l1_otp_and_sessions(s) -> None:
    now = datetime.utcnow()

    # OTP for scammer device that was NOT stopped (simulates victim forwarding OTP to fake page)
    s.add(
        OtpEvent(
            id="otp-scammer-login",
            user_id="scammer_device_02",
            device_id="dev-scammer-s24",
            action="login",
            geo_ip_region="Johor Bahru",
            device_label="Samsung S24",
            otp_code="654321",
            issued_at=now - timedelta(minutes=10),
            expires_at=now - timedelta(minutes=5),
            used_at=now - timedelta(minutes=8),
            resolved="allowed",
        )
    )

    # OTP that WAS stopped (for L1-STOP demo scenario)
    s.add(
        OtpEvent(
            id="otp-stopped-demo",
            user_id="demo_user_01",
            device_id="dev-trusted-s21",
            action="login",
            geo_ip_region="Kuala Lumpur",
            device_label="Samsung S21",
            otp_code="111111",
            issued_at=now - timedelta(minutes=30),
            expires_at=now - timedelta(minutes=25),
            used_at=None,
            resolved="blocked",
        )
    )

    # Pending rebind attempt for scammer
    s.add(
        RebindAttempt(
            id="rb-scammer-01",
            user_id="scammer_device_02",
            device_id="dev-scammer-s24",
            attempted_at=now - timedelta(minutes=5),
            outcome="pending",
            friction_method="video_verify",
        )
    )


if __name__ == "__main__":
    seed()
