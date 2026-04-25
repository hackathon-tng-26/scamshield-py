# ScamShield Backend

FastAPI + scikit-learn + NetworkX backend for the ScamShield mobile demo.

## Stack

- Python 3.11+
- FastAPI · Pydantic v2 · SQLAlchemy 2.0 · SQLite
- scikit-learn (GBDT) · NetworkX (L3 graph) · Faker (synthetic data)
- Package manager: [uv](https://docs.astral.sh/uv/) (pip works too)

## Quick start (uv)

```bash
# 1. Install deps
uv sync

# 2. Copy env config
cp .env.example .env

# 3. Run the server — DB auto-seeds on first start
uv run uvicorn app.main:app --reload --port 8000

# 4. Verify
curl http://localhost:8000/health
curl http://localhost:8000/scenarios
```

## Quick start (pip fallback)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness check |
| POST | `/transfer/score` | score a transfer (L2), returns score/verdict/attribution |
| POST | `/transfer/execute` | persist a scored transfer |
| GET | `/alerts?limit=50` | recent scored transactions for BO feed |
| GET | `/graph/cluster/{id}` | mule-network subgraph with spring layout |
| GET | `/scenarios` | demo scenarios (G1/Y1/R1/L1) |

## Mobile wire contract

Pydantic schemas in `app/schemas/transfer.py` match the KMP DTOs byte-for-byte. If you change a field name here, change it on mobile too.

## Demo scenarios (LOCKED)

See `/plan/05_data_seeding.docx` §4. Summary:

- **G1**: `demo_user_01` → Siti Aminah (`+60 12-345 6789`) RM 50 → GREEN 15–25
- **R1**: `demo_user_01` → `recipient_mule_01` (`+60 11-XXXX 8712`) RM 2,000 → RED 82–90 (HERO)
- **L1**: new device → BLOCKED by L1 cooldown (no L2 score)

`app/scoring/demo_overrides.py` **guarantees** these scenarios produce deterministic scores regardless of model state. If you need to disable overrides during development, set `DEMO_OVERRIDES_ENABLED=false` in `.env`.

## Mobile emulator networking

From an Android emulator, `localhost` refers to the emulator itself. To reach your host machine's FastAPI, use `http://10.0.2.2:8000`. This is already the default in the mobile's `ApiConfigDefaults`.

## Training the ML model (optional)

Rules-only scoring works out of the box. To upgrade to a trained GBDT:

```bash
uv run python scripts/train_model.py
# writes data/scorer.pkl
# restart uvicorn — it auto-loads the model on next request
```

## Project layout

```
backend/
├── app/
│   ├── main.py           FastAPI factory
│   ├── config.py         pydantic-settings
│   ├── db.py · models.py SQLAlchemy
│   ├── schemas/          Pydantic DTOs (Kotlin-aligned)
│   ├── api/              FastAPI routers
│   ├── scoring/          L2: rules + demo_overrides + optional GBDT
│   └── graph/            L3: NetworkX builder + patterns
├── scripts/
│   ├── seed.py           deterministic seeder (auto-runs on empty DB)
│   └── train_model.py    optional GBDT trainer
├── data/                 sqlite + pkl live here (gitignored)
└── tests/                scoring tests assert G1/R1/Y1 produce right verdicts
```

See `CLAUDE.md` for conventions (no-comments, no-commit policy, architecture).
See `/plan/` for the full hackathon plan.
