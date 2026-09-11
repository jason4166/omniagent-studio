import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from omniagent.credentials import resolve_credential
from omniagent.telemetry import instrument_database


def configured_database_url(default: str) -> str:
    if os.environ.get("OMNIAGENT_DATABASE_URL_FILE"):
        return resolve_credential("OMNIAGENT_DATABASE_URL")
    return os.environ.get("OMNIAGENT_DATABASE_URL", default)


def build_engine(database_url: str) -> Engine:
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_timeout=5,
        connect_args={
            "connect_timeout": 5,
            "options": "-c statement_timeout=10000 -c lock_timeout=3000",
        }
        if database_url.startswith("postgresql")
        else {},
    )
    instrument_database(engine)
    return engine


def build_session_factory(
    engine: Engine,
) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )
