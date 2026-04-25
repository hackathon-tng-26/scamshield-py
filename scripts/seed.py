from __future__ import annotations

import random
from datetime import datetime, timedelta
from uuid import uuid4

from app.db import SessionLocal, init_db
from app.logger import get_logger
from app.models import (
    DemoScenario,
    Device,
    DeviceCooldown,
    MuleCluster,
    MuleClusterMembership,
    OtpEvent,
    RebindAttempt,
    ScamReport,
    SmsLure,
    Transaction,
    User,
)

# ---------------------------------------------------------------------------
# Deterministic baseline — guarantees identical output across runs
# ---------------------------------------------------------------------------
random.seed(42)

# ---------------------------------------------------------------------------
# Malaysian name pools (Faker ms_MY is not always available)
# ---------------------------------------------------------------------------
_MALAY_FIRST = [
    "Ahmad", "Mohd", "Nurul", "Siti", "Aminah", "Wafi", "Hafiz", "Aisyah",
    "Farid", "Zulkifli", "Nurain", "Amir", "Fatin", "Syafiq", "Hana",
    "Irfan", "Diana", "Azman", "Khairul", "Nadia", "Rashid", "Mira",
    "Faiz", "Liyana", "Shafiq", "Aina", "Imran", "Sya", "Adib", "Balqis",
]
_MALAY_LAST = [
    "Abdullah", "Ahmad", "Ismail", "Yusof", "Hassan", "Rahman", "Ali",
    "Othman", "Ibrahim", "Musa", "Salleh", "Taib", "Rahim", "Samad",
    "Hamzah", "Daud", "Jusoh", "Mat", "Long", "Ariffin",
]
_CHINESE_FIRST = [
    "Wei Ming", "Jia Hui", "Xin Yee", "Chee Keong", "Mei Ling", "Kok Weng",
    "Siew Fen", "Boon Hock", "Yen Ling", "Chun Wai", "Li Na", "Kah Wai",
    "Shu Fen", "Tze Yong", "Pei Shan", "Hock Lai", "Cynthia", "Desmond",
    "Evelyn", "Felix", "Gerald", "Hannah", "Isaac", "Jasmine",
]
_CHINESE_LAST = [
    "Tan", "Lim", "Lee", "Ng", "Chong", "Wong", "Goh", "Chan", "Yeoh",
    "Teoh", "Liew", "Koh", "Low", "Ong", "Cheah", "Foong", "Heng",
]
_INDIAN_FIRST = [
    "Rajesh", "Priya", "Kumar", "Lakshmi", "Vijay", "Anitha", "Suresh",
    "Devi", "Ravi", "Kavitha", "Manoj", "Shanti", "Arun", "Indira",
    "Senthil", "Vani", "Ganesh", "Padma", "Dinesh", "Revathi",
]
_INDIAN_LAST = [
    "Suppiah", "Raj", "Nair", "Menon", "Rao", "Iyer", "Chettiar",
    "Muthu", "Krishnan", "Ramachandran", "Subramaniam", "Govindasamy",
    "Perumal", "Velu", "Sinniah", "Kuppusamy", "Muniandy", "Rengasamy",
]


def _malaysian_name() -> str:
    eth = random.choices(
        ["malay", "chinese", "indian"],
        weights=[55, 30, 15],
        k=1,
    )[0]
    if eth == "malay":
        first = random.choice(_MALAY_FIRST)
        last = random.choice(_MALAY_LAST)
        return f"{first} {last}"
    if eth == "chinese":
        first = random.choice(_CHINESE_FIRST)
        last = random.choice(_CHINESE_LAST)
        return f"{last} {first}"
    first = random.choice(_INDIAN_FIRST)
    last = random.choice(_INDIAN_LAST)
    return f"{first} a/l {last}" if random.random() < 0.5 else f"{first} a/p {last}"

log = get_logger("seed")

# ---------------------------------------------------------------------------
# Volume constants — locked for demo determinism
# ---------------------------------------------------------------------------
NORMAL_USER_COUNT = 1_000
# 48 generated + 2 special mules (recipient_mule_01, scammer_device_02) = 50 total
MULE_USER_COUNT = 48
NORMAL_TXN_COUNT = 19_400
MULE_TXN_COUNT = 400
SCAM_REPORT_COUNT = 200
SMS_LURE_COUNT = 50
RECENT_ALERT_COUNT = 50

# ---------------------------------------------------------------------------
# Special users — DO NOT change IDs, phones, or names after Saturday noon
# ---------------------------------------------------------------------------
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

MULE_CLUSTER_CONFIG = {
    "MP-047": {"label": "Macau Scam Syndicate A", "tier": "t1", "count": 20},
    "MP-023": {"label": "Investment Scam Ring B", "tier": "t2", "count": 15},
    "MP-011": {"label": "Love Scam Cluster C", "tier": "t3", "count": 15},
}

SMS_LURE_TEMPLATES = [
    # Bantuan / Government
    ("Tahniah! Anda layak menerima RM500 dari Bantuan Rahmah. Semak sekarang: bit.ly/str-kelayakan", "B40", "BM"),
    ("MySejahtera: RM800 credit ready to claim. Click here within 24h: tng-rewards.co/claim", "MySejahtera", "EN"),
    ("JPJ: Saman anda boleh dibayar dengan diskaun 50% hari ini. Bayar di: jpj-saman.my.co", "JPJ", "BM"),
    ("LHDN refund RM{amount} siap dituntut. Sila maklum nombor bank: lhdn-refund.com", "LHDN", "BM"),
    ("Rahmah Raya: Ang pow RM250 dari kerajaan. Tekan untuk tuntut sekarang.", "political", "BM"),
    ("RON95 petrol subsidy cashback RM150 ready. Claim via tng-subsidy.my", "RON95", "rojak"),
    ("e-MADANI: RM100 credit masih ada. Tuntut sebelum 31 Disember: e-madani.my/claim", "eMADANI", "BM"),
    ("Bantuan Sara Hidup: Anda layak RM300. Klik untuk pengesahan: bsh-verify.co", "BSH", "BM"),
    # Account / Banking
    ("Your TNG eWallet account will be suspended. Verify now: tng-digital.my.co", "account-suspend", "EN"),
    ("Maybank2u: Akaun anda dikunci. Sila sahkan di: mb2u-secure.my", "bank-phish", "BM"),
    ("CIMB Clicks: Suspicious login detected. Verify identity: cimb-secure.co", "bank-phish", "EN"),
    ("RHB Bank: Your OTP was requested. If not you, click: rhb-verify.my", "bank-phish", "EN"),
    ("Public Bank: Card ending 1234 blocked. Unblock at: pbe-secure.my", "bank-phish", "EN"),
    ("Ambank: RM1,200 deducted from your account. Dispute: amb-dispute.co", "bank-phish", "EN"),
    # Parcel / Delivery
    ("Pos Laju: Parcel pending customs duty RM35. Pay now: poslaju-customs.my", "parcel", "rojak"),
    ("J&T Express: Package on hold. Pay shipping fee RM12: jnt-shipping.my", "parcel", "EN"),
    ("DHL: Import tax RM48 unpaid. Parcel will return to sender: dhl-tax.my", "parcel", "EN"),
    ("Shopee Xpress: Failed delivery attempt #2. Reschedule: spx-reschedule.co", "parcel", "EN"),
    # Investment / Crypto
    ("Peluang emas! Pelaburan emas 999.9 pulangan 15% sebulan. Daftar: emas-bernilai.my", "investment", "BM"),
    ("Forex signals group: 95% win rate. Join VIP for RM199/month: forex-vip.co", "investment", "EN"),
    ("Bitcoin giveaway! Send 0.01 BTC get 0.02 BTC back. Limited slots: btc-double.my", "crypto", "EN"),
    ("Unit Trust Amanah Saham: Dividen istimewa 12%. Daftar segera: asnb-special.my", "investment", "BM"),
    ("Crypto arbitrage bot: Guaranteed 8% daily returns. Deposit now: crypto-arb.co", "crypto", "EN"),
    # Love / Social
    ("Hi sayang, ini nombor baru saya. Simpan ya. Nanti saya call: +6012-XXX-XXXX", "love-scam", "BM"),
    ("Dr. Ahmad dari KKM: Anda terpilih untuk ujian khas. Hadiah RM5,000 menanti.", "lottery", "BM"),
    ("TNG eWallet: You won RM10,000! Claim within 24 hours: tng-winner.my", "lottery", "EN"),
    ("Magnum 4D: Your number matched! Collect RM50,000: magnum-claim.co", "lottery", "EN"),
    ("Grand Dragon Lottery: Consolation prize RM88,888. Verify identity: gdl-prize.my", "lottery", "EN"),
    # Job / Part-time
    ("Kerja dari rumah! Gaji RM3,500/seminggu. Hanya perlu like & share: kerja-mudah.my", "job-scam", "BM"),
    ("Part-time data entry: RM150/hour. No experience needed. Apply: data-entry-job.co", "job-scam", "EN"),
    ("Amazon reviewer wanted: Free products + RM50/review. Register: amazon-review.my", "job-scam", "EN"),
    ("TikTok moderator hiring: RM8,000/month. Work from home: tiktok-hire.co", "job-scam", "EN"),
    # Utility / Telecom
    ("TNB: Bil elektrik tertunggak RM450. Pengecualian disambung jika tidak bayar: tnb-overdue.my", "utility", "BM"),
    ("Syabas: Air akan dipotong esok. Bayar RM120 sekarang: syabas-pay.my", "utility", "BM"),
    ("Maxis: Your bill RM299 is overdue. Pay now to avoid suspension: maxis-bill.co", "telecom", "EN"),
    ("Digi: Unlimited data plan RM0 for 30 days. Claim: digi-free.my", "telecom", "EN"),
    ("Celcom: You've been selected for FREE iPhone 15. Confirm shipping: celcom-gift.co", "telecom", "EN"),
    # E-wallet / Fintech
    ("GrabPay: RM200 cashback expired today. Activate: grab-cashback.my", "fintech", "EN"),
    ("Boost: Ang pow RM88 awaiting collection. Open: boost-redpacket.my", "fintech", "EN"),
    ("ShopeePay: Refund RM350 processed. Confirm bank details: shopeepay-refund.co", "fintech", "EN"),
    ("Touch n Go: RFID toll rebate RM200. Claim before expiry: tng-rfid.my", "fintech", "rojak"),
    ("MAE by Maybank: Spend RM50 get RM50 back. Register card: mae-promo.my", "fintech", "EN"),
    # Fake Support
    ("WhatsApp Support: Your account will be deleted in 24h. Verify: whatsapp-support.co", "support", "EN"),
    ("Facebook Security: Unusual login from China. Secure account: fb-security.my", "support", "EN"),
    ("Instagram: Copyright violation detected. Appeal within 48h: ig-appeal.co", "support", "EN"),
    ("TikTok: Account flagged for community violation. Verify: tiktok-verify.my", "support", "EN"),
    # Insurance / Medical
    ("Great Eastern: Polisi insurans anda tamat. Bayaran RM650: ge-renewal.my", "insurance", "BM"),
    ("Prudential: Critical illness payout RM150,000 approved. Confirm IC: pru-claim.my", "insurance", "EN"),
    ("KKM: Vaksin COVID-19 booster RM50. Daftar di: kkm-vaksin.my", "medical", "BM"),
    ("Pharmacy Online: Ubat kurus 70% off. Order: pharmacy-deal.my", "medical", "BM"),
    # Property / Vehicle
    ("Rumah murah KL! RM150,000 sahaja. Booking fee RM500: rumah-murah-kl.my", "property", "BM"),
    ("Car auction: Toyota Vios 2022 RM25,000. Bid now: car-auction.my", "vehicle", "EN"),
]


def seed() -> None:
    init_db(drop_first=True)
    with SessionLocal() as s:
        log.info("seed.special_users.begin")
        special_ids = seed_special_users(s)

        log.info("seed.normal_users.begin", target=NORMAL_USER_COUNT)
        normal_user_ids = generate_normal_users(s, n=NORMAL_USER_COUNT)

        log.info("seed.mule_users.begin", target=MULE_USER_COUNT)
        mule_ids = generate_mule_users(s, n=MULE_USER_COUNT)

        log.info("seed.mule_clusters.begin")
        seed_mule_clusters(s)
        link_mules_to_clusters(s, mule_ids)

        log.info("seed.devices.begin")
        seed_devices(s, normal_user_ids, mule_ids)

        log.info("seed.normal_txns.begin", target=NORMAL_TXN_COUNT)
        generate_normal_transactions(s, normal_user_ids, n=NORMAL_TXN_COUNT)

        log.info("seed.mule_txns.begin", target=MULE_TXN_COUNT)
        generate_mule_transactions(s, normal_user_ids, mule_ids, n=MULE_TXN_COUNT)

        log.info("seed.recipient_mule_01_fan_in.begin")
        seed_recipient_mule_01_fan_in(s, normal_user_ids)

        log.info("seed.scam_reports.begin", target=SCAM_REPORT_COUNT)
        seed_scam_reports(s, normal_user_ids, mule_ids, n=SCAM_REPORT_COUNT)

        log.info("seed.demo_scenarios.begin")
        seed_demo_scenarios(s)

        log.info("seed.sms_lures.begin", target=SMS_LURE_COUNT)
        seed_sms_lures(s, n=SMS_LURE_COUNT)

        log.info("seed.l1_devices.begin")
        seed_l1_devices(s)

        log.info("seed.l1_otp_sessions.begin")
        seed_l1_otp_and_sessions(s)

        log.info("seed.recent_alerts.begin", target=RECENT_ALERT_COUNT)
        seed_recent_alerts(s, normal_user_ids + mule_ids, n=RECENT_ALERT_COUNT)

        s.commit()

        log.info("seed.validate.begin")
        validate(s)

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


def generate_normal_users(s, n: int = NORMAL_USER_COUNT) -> list[str]:
    ids: list[str] = []
    now = datetime.utcnow()
    for i in range(n):
        uid = f"user_{i:04d}"
        u = User(
            id=uid,
            phone=f"+60 {random.choice(['11','12','13','14','16','17','18','19'])}-{random.randint(1000,9999)} {random.randint(1000,9999)}",
            name=_malaysian_name(),
            account_type="normal",
            mule_likelihood=round(random.uniform(0.0, 0.12), 3),
            created_at=now - timedelta(days=random.randint(30, 600)),
        )
        s.add(u)
        ids.append(uid)
    s.flush()
    return ids


def generate_mule_users(s, n: int = MULE_USER_COUNT) -> list[str]:
    ids: list[str] = []
    now = datetime.utcnow()
    tag_pool = ["MP-047"] * 20 + ["MP-023"] * 14 + ["MP-011"] * 14
    random.shuffle(tag_pool)

    for i in range(n):
        uid = f"mule_{i:03d}"
        tag = tag_pool[i]
        u = User(
            id=uid,
            phone=f"+60 1{random.randint(1,9)}-MULE {random.randint(1000,9999)}",
            name=f"Mule {tag} #{i}",
            account_type="mule",
            mule_pattern_tag=tag,
            mule_likelihood=round(random.uniform(0.70, 0.95), 3),
            created_at=now - timedelta(days=random.randint(1, 14)),
        )
        s.add(u)
        ids.append(uid)
    s.flush()
    return ids


def seed_mule_clusters(s) -> None:
    now = datetime.utcnow()
    for tag, cfg in MULE_CLUSTER_CONFIG.items():
        s.add(
            MuleCluster(
                id=tag,
                label=cfg["label"],
                tier=cfg["tier"],
                member_count=cfg["count"],
                avg_mule_likelihood=round(random.uniform(0.72, 0.88), 3),
                last_refreshed_at=now,
            )
        )
    s.flush()


def link_mules_to_clusters(s, mule_ids: list[str]) -> None:
    now = datetime.utcnow()
    for uid in mule_ids:
        user = s.query(User).filter(User.id == uid).first()
        if user and user.mule_pattern_tag:
            s.add(
                MuleClusterMembership(
                    id=f"mcm-{uuid4().hex[:12]}",
                    cluster_id=user.mule_pattern_tag,
                    user_id=uid,
                    joined_at=now - timedelta(days=random.randint(1, 10)),
                )
            )
    s.flush()


def seed_devices(s, normal_user_ids: list[str], mule_ids: list[str]) -> None:
    now = datetime.utcnow()
    regions = ["Kuala Lumpur", "Selangor", "Penang", "Johor Bahru", "Ipoh", "Melaka", "Kota Kinabalu", "Kuching"]

    for uid in normal_user_ids:
        d = Device(
            id=f"dev_{uid}",
            user_id=uid,
            fingerprint=f"fp-{uuid4().hex[:16]}",
            first_seen=now - timedelta(days=random.randint(1, 500)),
            geo_ip_region=random.choice(regions),
            trusted=True,
        )
        s.add(d)

    # Mules share a smaller pool of devices (simulating device farms)
    for uid in mule_ids:
        d = Device(
            id=f"dev_{uid}",
            user_id=uid,
            fingerprint=f"fp-mule-{random.randint(1000,9999)}",
            first_seen=now - timedelta(days=random.randint(1, 30)),
            geo_ip_region=random.choice(regions),
            trusted=random.choice([True, False]),
        )
        s.add(d)


def generate_normal_transactions(s, user_ids: list[str], n: int = NORMAL_TXN_COUNT) -> None:
    now = datetime.utcnow()
    for _ in range(n):
        sender = random.choice(user_ids)
        recipient = random.choice([u for u in user_ids if u != sender])
        amount = round(abs(random.lognormvariate(mu=3.5, sigma=1.2)), 2)
        if amount > 5_000:
            amount = round(random.uniform(5.0, 500.0), 2)
        score = random.randint(5, 30)
        ts = now - timedelta(minutes=random.randint(1, 30 * 24 * 60))
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


def generate_mule_transactions(s, normal_user_ids: list[str], mule_ids: list[str], n: int = MULE_TXN_COUNT) -> None:
    now = datetime.utcnow()
    structuring_amounts = [9_500.0, 9_800.0, 9_900.0, 9_950.0, 9_999.0]

    for i in range(n):
        sender = random.choice(normal_user_ids)
        recipient = random.choice(mule_ids)

        # 30% of mule transactions show sub-RM10k structuring
        if i % 3 == 0:
            amount = round(random.choice(structuring_amounts), 2)
        else:
            amount = round(random.uniform(50.0, 2_500.0), 2)

        score = random.randint(60, 95)
        verdict = "RED" if score >= 70 else "YELLOW"
        ts = now - timedelta(minutes=random.randint(1, 48 * 60))
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


def seed_scam_reports(s, normal_user_ids: list[str], mule_ids: list[str], n: int = SCAM_REPORT_COUNT) -> None:
    # Exactly 7 reports on recipient_mule_01 (quoted in pitch script)
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


def seed_sms_lures(s, n: int = SMS_LURE_COUNT) -> None:
    templates = SMS_LURE_TEMPLATES[:n]
    for template, category, lang in templates:
        s.add(SmsLure(template=template, category=category, language=lang))


def seed_l1_devices(s) -> None:
    now = datetime.utcnow()

    trusted_dev = Device(
        id="dev-trusted-s21",
        user_id="demo_user_01",
        fingerprint="trusted-samsung-s21",
        first_seen=now - timedelta(days=180),
        geo_ip_region="Kuala Lumpur",
        trusted=True,
    )
    s.add(trusted_dev)

    user = s.query(User).filter(User.id == "demo_user_01").first()
    if user:
        user.trusted_device_id = trusted_dev.id

    scammer_dev = Device(
        id="dev-scammer-s24",
        user_id="scammer_device_02",
        fingerprint="scammer-samsung-s24",
        first_seen=now,
        geo_ip_region="Johor Bahru",
        trusted=False,
    )
    s.add(scammer_dev)

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


def seed_recent_alerts(s, user_ids: list[str], n: int = RECENT_ALERT_COUNT) -> None:
    now = datetime.utcnow()
    for i in range(n):
        sender = random.choice(user_ids)
        recipient = random.choice([u for u in user_ids if u != sender])
        txn = Transaction(
            id=f"tx-alert-{i:03d}",
            sender_id=sender,
            recipient_id=recipient,
            amount=round(random.uniform(10.0, 500.0), 2),
            timestamp=now - timedelta(seconds=random.randint(0, 180)),
            risk_score=random.randint(5, 95),
            verdict=random.choice(["GREEN", "YELLOW", "RED"]),
        )
        s.add(txn)


def validate(s) -> None:
    errors: list[str] = []

    # 1. Mule count = 50 (48 generated + 2 special)
    mule_count = s.query(User).filter(User.account_type == "mule").count()
    if mule_count != 50:
        errors.append(f"Mule count is {mule_count}, expected 50")

    # 2. Total transactions 19,000–21,000
    txn_count = s.query(Transaction).count()
    if not (19_000 <= txn_count <= 21_000):
        errors.append(f"Transaction count is {txn_count}, expected 19,000–21,000")

    # 3. 7 scam reports point at recipient_mule_01
    report_count = s.query(ScamReport).filter(
        ScamReport.reported_user_id == "recipient_mule_01"
    ).count()
    if report_count != 7:
        errors.append(f"Reports on recipient_mule_01: {report_count}, expected 7")

    # 4. Recent alerts exist (last 8 within 3 minutes)
    recent = s.query(Transaction).filter(
        Transaction.timestamp >= datetime.utcnow() - timedelta(minutes=3)
    ).count()
    if recent < 8:
        errors.append(f"Recent alerts: {recent}, expected at least 8")

    # 5. Demo scenarios exist
    for sid in ["G1", "Y1", "R1", "L1"]:
        if not s.query(DemoScenario).filter(DemoScenario.id == sid).first():
            errors.append(f"Demo scenario {sid} missing")

    # 6. Mule clusters seeded
    cluster_count = s.query(MuleCluster).count()
    if cluster_count != 3:
        errors.append(f"Mule cluster count: {cluster_count}, expected 3")

    # 7. Mule cluster memberships match user count
    membership_count = s.query(MuleClusterMembership).count()
    if membership_count != MULE_USER_COUNT:
        errors.append(f"Cluster memberships: {membership_count}, expected {MULE_USER_COUNT}")

    if errors:
        for e in errors:
            log.error("seed.validation_failed", error=e)
        raise AssertionError(f"Seed validation failed: {errors}")

    log.info("seed.validation_ok")


if __name__ == "__main__":
    seed()
