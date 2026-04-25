# CLAUDE.md

Guidance for AI assistants working in this repository.

## Critical Rules - READ FIRST

1. **NEVER COMMIT** unless the user explicitly says "commit".
2. **NEVER PUSH** unless the user explicitly requests it.
3. **NO COMMENTS** in code (strict). See Code Style.
4. **DEMO-FIRST MINDSET** — if a change could affect the deterministic demo scenarios (G1/R1/L1), stop and confirm with the user.

## Project Overview

ScamShield backend — the brain behind the TNG-style mobile demo. Serves:

- **L2** transaction risk scoring (GBDT + rule overlay + explainability)
- **L3** mule-network graph (NetworkX, fan-in / velocity / off-ramp patterns)
- Supporting endpoints for the BO dashboard (alert feed, cluster view, demo scenarios)

**Package**: `app/` namespace. No root package prefix.
**Python**: 3.11+

## Build Commands

```bash
# Dev server (auto-reload, auto-seed on empty DB)
uv run uvicorn app.main:app --reload --port 8000

# Run scoring tests
uv run pytest tests/test_demo_scenarios.py -v

# Re-seed DB (drops and recreates tables + data)
uv run python scripts/seed.py

# Train the GBDT model (optional)
uv run python scripts/train_model.py
```

## Architecture

```
HTTP  ─►  app/api/*        ← thin routers, FastAPI decorators
          app/schemas/*    ← Pydantic DTOs (wire format)
          app/scoring/*    ← L2 brain
          app/graph/*      ← L3 brain
          app/models.py    ← SQLAlchemy ORM
          app/db.py        ← session factory
```

Rule of thumb: **API layer is dumb**. Business logic lives in `scoring/service.py` and `graph/service.py`. Routers are ~5 lines each.

## Wire contract with mobile

`app/schemas/transfer.py` defines Pydantic models that match the KMP mobile's DTOs byte-for-byte. **JSON field names are snake_case** — this matches mobile's `@SerialName("snake_case_name")` annotations. If you change a field name in `schemas/transfer.py`, you MUST update `composeApp/src/commonMain/kotlin/my/scamshield/feature/transfer/data/dto/*.kt` in the mobile repo, and vice-versa.

## L2 scoring — three layers (in order)

1. `demo_overrides.py` — if `DEMO_OVERRIDES_ENABLED=true` AND request matches a locked scenario (G1/R1 by phone), return the pre-canned response. Guarantees demo stability.
2. `rules.py` — deterministic feature-weighted rules with attribution. Baseline 50, adjusted by 15 hand-crafted features. Always available.
3. `model.py` — GBDT (scikit-learn GradientBoostingClassifier) loaded from `data/scorer.pkl`. If model file missing, scoring falls back to rules. Friend trains with `scripts/train_model.py`.

Attribution format: list of `FeatureContribution(feature, contribution, direction)`. Both `rules.py` and `model.py` produce this — the API response shape does not change based on which path fires.

## L3 graph

`graph/builder.py` loads all transactions from DB into a `networkx.DiGraph`. Edges = transfers, nodes = users.

`graph/patterns.py` detects:
- **Fan-in** — count distinct senders to a node in last N hours
- **Velocity cluster** — transactions in/out in last hour
- **Off-ramp proximity** — shortest path to any node tagged as `usdt_offramp_*`

These run on demand for graph queries. For scoring inference, recipient mule-likelihood is pre-computed on each user row (`users.mule_likelihood`) during seeding and can be refreshed on a cron.

`graph/service.py` returns a cluster subgraph with cached spring-layout positions. Layout is computed once at startup — never per-request.

## Seeding

`scripts/seed.py` is idempotent. Run it any time — drops and recreates everything.

Produces (per doc 05 §3):
- 1,000 normal users (Faker ms_MY locale)
- 50 mules (16 in MP-047 cluster, rest scattered)
- ~20,000 transactions over 30 days
- 200 scam reports (7 pointing at recipient_mule_01 specifically — the pitch copy references this number)
- 50 SMS lures
- 4 demo scenarios (G1/Y1/R1/L1) with seeded sender+recipient users

The server auto-seeds on startup if the DB is empty (controlled by `AUTO_SEED_ON_EMPTY=true`).

## Demo scenarios — LOCKED

See `/plan/05_data_seeding.docx` §4 (also replicated in mobile's `DemoScenarios.kt`).

| ID | Sender | Recipient | Phone | Amount | Expected |
|----|--------|-----------|-------|--------|----------|
| G1 | demo_user_01 | contact_siti | +60 12-345 6789 | RM 50 | GREEN 15–25 |
| Y1 | demo_user_01 | new_recipient_22 | +60 13-777 0022 | RM 800 | YELLOW 45–65 |
| R1 | demo_user_01 | recipient_mule_01 | +60 11-XXXX 8712 | RM 2,000 | RED 82–90 |
| L1 | scammer_device_02 | (no L2) | — | — | BLOCKED by L1 |

If your code changes cause any of these to drift: stop, revert, rerun `pytest tests/test_demo_scenarios.py`.

## Source layout

```
app/
├── main.py             FastAPI app factory, CORS, startup auto-seed
├── config.py           pydantic-settings (.env)
├── logger.py           structlog wrapper
├── db.py               engine + SessionLocal
├── models.py           ORM: User · Device · Transaction · ScamReport · DemoScenario · SmsLure
├── schemas/
│   ├── transfer.py     ScoreTransferRequest/Response · FeatureContribution
│   ├── alerts.py · graph.py · scenarios.py
├── api/                one module per endpoint group, all trivial wiring
├── scoring/
│   ├── demo_overrides.py   LOCKED scenario responses
│   ├── features.py         feature extraction
│   ├── rules.py            rule overlay + attribution
│   ├── model.py            GBDT loader (optional)
│   └── service.py          orchestration
└── graph/
    ├── builder.py      load DB → networkx.DiGraph
    ├── patterns.py     fan-in · velocity · off-ramp
    └── service.py      cluster query + cached layout
```

## Code Style

### Comments Policy (STRICT)

- **NO COMMENTS**: inline, docstring, or "# explanatory" comments.
- **ONLY** exceptions: `# TODO:` for critical follow-ups, `# FIXME:` for known bugs.
- Self-documenting code via naming. If a function needs a comment, rename or split it.

### Other rules

- **Type hints everywhere.** Python 3.11+ syntax (`list[int]`, `str | None`).
- **Pydantic v2 syntax** — `model_config = ConfigDict(...)`, not class-based Config.
- **Structured logging** — inject `get_logger(__name__)` from `app.logger`, never `print`.
- **Session management** — use `Depends(get_db)` in endpoints, never global sessions.
- **Snake_case JSON fields** — keep wire format consistent with mobile.

## Common Pitfalls

- **`Faker(locale="ms_MY")`** generates some phone numbers without the +60 prefix. Wrap with a helper that normalises.
- **Spring layout is slow** — cache in-memory at startup, never compute per request.
- **SHAP on first-call** — JIT-warms slowly. Warm in startup if `data/scorer.pkl` exists.
- **SQLite concurrent writes** — single process only. `uvicorn --workers 1` for demo.
- **Demo overrides bypass the DB** — they don't persist. If you want the BO feed to show the demo transaction, seed it separately OR disable overrides for the alert-feed query path.

## Plan docs

Located at `/Users/ahmadwafi/hackaton-tng/plan/`. Read before making architecture changes:

- `02_solution_layers.docx` — 3-layer defence
- `03_demo_script.docx` — storyboards
- `04_bo_dashboard.docx` — BO spec
- `05_data_seeding.docx` — synthetic data + LOCKED scenarios
- `06_pitch_structure.docx` — 7-min pitch arc
- `07_decisions_to_lock.docx` — sign-off decisions
