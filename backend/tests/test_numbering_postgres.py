"""Gapless numbering under real concurrency. Needs PostgreSQL: set TEST_DATABASE_URL (CI does)."""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import DocumentSequence
from app.numbering import allocate_number

URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL.startswith("postgresql"), reason="TEST_DATABASE_URL (PostgreSQL) not set")


@pytest.fixture
def pg_sessions():
    url = URL.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url, pool_size=20, max_overflow=40)
    table = DocumentSequence.__table__
    table.drop(engine, checkfirst=True)
    table.create(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    table.drop(engine)
    engine.dispose()


def test_fifty_parallel_issues_get_fifty_numbers_without_gaps(pg_sessions):
    def issue(i: int) -> str | None:
        with pg_sessions() as db:
            number = allocate_number(db, "INV")
            if i % 10 == 9:  # some requests fail after taking a number: it must be given back
                db.rollback()
                return None
            db.commit()
            return number

    with ThreadPoolExecutor(max_workers=25) as pool:
        numbers = [n for n in pool.map(issue, range(55)) if n]

    assert len(numbers) == 50
    assert sorted(numbers) == [f"SP-INV-{n:04d}" for n in range(1, 51)]
