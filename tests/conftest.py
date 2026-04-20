from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from scanner.libs.services.container import ApplicationContainer
from scanner.libs.storage.database import build_engine
from scanner.libs.storage.models import Base

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


@pytest.fixture()
def fixture_loader():
    return load_fixture


@pytest.fixture()
def test_container() -> ApplicationContainer:
    database_url = "sqlite+pysqlite:///:memory:"
    engine = build_engine(database_url)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return ApplicationContainer(session_factory=session_factory)
