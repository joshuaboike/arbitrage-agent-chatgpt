from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from scanner.libs.storage.models import Base


def build_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, future=True, connect_args=connect_args)


def build_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = build_engine(database_url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_database(database_url: str) -> None:
    engine = build_engine(database_url)
    Base.metadata.create_all(bind=engine)
    ensure_local_schema_compatibility(engine)


def ensure_local_schema_compatibility(engine) -> None:
    inspector = inspect(engine)
    if "triage_results" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("triage_results")}
    statements: list[str] = []
    if "llm_triage_json" not in existing_columns:
        statements.append("ALTER TABLE triage_results ADD COLUMN llm_triage_json JSON")
    if "llm_model" not in existing_columns:
        statements.append("ALTER TABLE triage_results ADD COLUMN llm_model VARCHAR(64)")
    if "llm_reviewed_at" not in existing_columns:
        statements.append("ALTER TABLE triage_results ADD COLUMN llm_reviewed_at DATETIME")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
