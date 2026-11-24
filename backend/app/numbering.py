"""Gapless document numbers: SP-Q-2026-001, SP-INV-2026-001, SP-R-2026-001, SP-CN-2026-001, SP-PS-2026-001.

A number is assigned only when a document is issued, inside the same transaction. The sequence row
is locked (SELECT ... FOR UPDATE on PostgreSQL), so two requests can never get the same number,
and if the transaction rolls back the number is not used up. The counter restarts every year.
"""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import DocumentSequence

PREFIXES = {
    "Q": "SP-Q",
    "INV": "SP-INV",
    "R": "SP-R",
    "CN": "SP-CN",
    "PS": "SP-PS",
}


def format_number(doc_type: str, year: int, number: int) -> str:
    return f"{PREFIXES[doc_type]}-{year}-{number:03d}"


def _locked_row(db: Session, doc_type: str, year: int) -> DocumentSequence | None:
    stmt = (
        select(DocumentSequence)
        .where(DocumentSequence.doc_type == doc_type, DocumentSequence.year == year)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return db.scalars(stmt).first()


def allocate_number(db: Session, doc_type: str, year: int, seed: Callable[[], int] | None = None) -> str:
    """Take the next number for `doc_type` in `year`. The caller commits (or rolls back) the transaction.

    `seed` gives the starting count when a year's sequence row is first created (used for numbers
    that existed before this table, such as payout statements).
    """
    if doc_type not in PREFIXES:
        raise ValueError(f"Unknown document type {doc_type!r}")
    row = _locked_row(db, doc_type, year)
    if row is None:
        start = seed() if seed else 0
        if db.get_bind().dialect.name == "postgresql":
            # Two requests may try to create the first row of a year at once; the loser re-reads it.
            try:
                with db.begin_nested():
                    db.add(DocumentSequence(doc_type=doc_type, year=year, last_number=start))
            except IntegrityError:
                pass
        else:
            db.add(DocumentSequence(doc_type=doc_type, year=year, last_number=start))
            db.flush()
        row = _locked_row(db, doc_type, year)
        assert row is not None
    row.last_number += 1
    db.flush()
    return format_number(doc_type, year, row.last_number)
