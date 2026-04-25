from collections.abc import Generator
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

class Base(DeclarativeBase):
    pass

# Production-ready engine configuration
# Use NullPool in Lambda to avoid connection leakage across ephemeral containers
engine_args = {}
if not settings.resolved_database_url.startswith("sqlite"):
    engine_args["poolclass"] = NullPool
else:
    engine_args["connect_args"] = {"check_same_thread": False}

engine = create_engine(
    settings.resolved_database_url,
    echo=False,
    **engine_args
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


def init_db(drop_first: bool = False) -> None:
    from app import models  # noqa: F401
    if drop_first:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def is_empty() -> bool:
    from app.models import User
    with SessionLocal() as s:
        return s.query(User).count() == 0


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
