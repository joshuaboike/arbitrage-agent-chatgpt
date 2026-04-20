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
    table_names = inspector.get_table_names()
    if "listing_images" in table_names:
        image_columns = {column["name"] for column in inspector.get_columns("listing_images")}
        image_statements: list[str] = []
        if "local_path" not in image_columns:
            image_statements.append(
                "ALTER TABLE listing_images ADD COLUMN local_path VARCHAR(1000)"
            )
        if "content_type" not in image_columns:
            image_statements.append(
                "ALTER TABLE listing_images ADD COLUMN content_type VARCHAR(128)"
            )
        if "size_bytes" not in image_columns:
            image_statements.append("ALTER TABLE listing_images ADD COLUMN size_bytes INTEGER")
        if "downloaded_at" not in image_columns:
            image_statements.append("ALTER TABLE listing_images ADD COLUMN downloaded_at DATETIME")

        with engine.begin() as connection:
            for statement in image_statements:
                connection.execute(text(statement))

    if "triage_results" not in table_names:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("triage_results")}
    statements: list[str] = []
    if "llm_triage_json" not in existing_columns:
        statements.append("ALTER TABLE triage_results ADD COLUMN llm_triage_json JSON")
    if "llm_model" not in existing_columns:
        statements.append("ALTER TABLE triage_results ADD COLUMN llm_model VARCHAR(64)")
    if "llm_reviewed_at" not in existing_columns:
        statements.append("ALTER TABLE triage_results ADD COLUMN llm_reviewed_at DATETIME")
    if "photo_review_json" not in existing_columns:
        statements.append("ALTER TABLE triage_results ADD COLUMN photo_review_json JSON")
    if "photo_reviewed_at" not in existing_columns:
        statements.append("ALTER TABLE triage_results ADD COLUMN photo_reviewed_at DATETIME")
    if "market_check_json" not in existing_columns:
        statements.append("ALTER TABLE triage_results ADD COLUMN market_check_json JSON")
    if "market_checked_at" not in existing_columns:
        statements.append("ALTER TABLE triage_results ADD COLUMN market_checked_at DATETIME")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
