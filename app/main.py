from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import alerts, graph, health, scenarios, transfer
from app.config import settings
from app.core.identity import endpoints as identity_endpoints
from app.db import init_db, is_empty
from app.logger import get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("scamshield.startup", env=settings.app_env, version=__version__)
    init_db(drop_first=False)

    if settings.auto_seed_on_empty and is_empty():
        log.info("db.empty.autoseed.begin")
        from scripts.seed import seed as run_seed
        run_seed()
        log.info("db.empty.autoseed.complete")

    yield
    log.info("scamshield.shutdown")


app = FastAPI(
    title="ScamShield Backend",
    version=__version__,
    description="AI-powered anti-scam scoring + mule graph for the ScamShield mobile demo.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(identity_endpoints.router)
app.include_router(transfer.router, prefix="/transfer", tags=["transfer"])
app.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
app.include_router(graph.router, prefix="/graph", tags=["graph"])
app.include_router(scenarios.router, prefix="/scenarios", tags=["scenarios"])
