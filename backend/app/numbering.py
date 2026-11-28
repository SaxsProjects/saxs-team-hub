"""Gapless, continuous document numbers: SP-Q-0001, SP-INV-0001, SP-R-0001, ... and on to SP-INV-10000.

Company standard SP/CORP/2026/008: every document type has its own series that never restarts, is never
reused and never skips. A number is assigned only when a document is issued, inside the same
transaction. The sequence row is locked (SELECT ... FOR UPDATE on PostgreSQL), so two requests can
never get the same number, and if the transaction rolls back the number is not used up.

Before version 2.0 numbers restarted every year (SP-INV-2026-001). Those rows are kept as history in
`document_sequences` (one per year); the continuous series is the row with year 0, and it starts
after every number already issued, so old and new numbers can never collide.
"""

from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import DocumentSequence

PREFIXES = {
    "Q": "SP-Q",
    "INV": "SP-INV",
    "R": "SP-R",
    "CN": "SP-CN",
    "PS": "SP-PS",
    "TO": "SP-TO",
    "OFF": "SP-OFF",
    "PRO": "SP-PRO",
    "SOA": "SP-SOA",
    "CERT": "SP-CERT",
}

CONTINUOUS = 0  # the `year` value of the never-resetting sequence row


def format_number(doc_type: str, number: int) -> str:
    return f"{PREFIXES[doc_type]}-{number:04d}"


def _locked_row(db: Session, doc_type: str) -> DocumentSequence | None:
    stmt = (
        select(DocumentSequence)
        .where(DocumentSequence.doc_type == doc_type, DocumentSequence.year == CONTINUOUS)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return db.scalars(stmt).first()


def _issued_before(db: Session, doc_type: str) -> int:
    """How many numbers the old yearly series issued for this type (they were gapless, so this is a count)."""
    stmt = select(func.coalesce(func.sum(DocumentSequence.last_number), 0)).where(
        DocumentSequence.doc_type == doc_type, DocumentSequence.year != CONTINUOUS
    )
    return int(db.scalar(stmt) or 0)


def allocate_number(db: Session, doc_type: str, seed: Callable[[], int] | None = None) -> str:
    """Take the next number for `doc_type`. The caller commits (or rolls back) the transaction.

    `seed` counts documents of this type that exist without any sequence row (numbers made before the
    sequence table, such as early payout statements and offers); the series starts after the larger of
    that count and the numbers the yearly series already issued.
    """
    if doc_type not in PREFIXES:
        raise ValueError(f"Unknown document type {doc_type!r}")
    row = _locked_row(db, doc_type)
    if row is None:
        start = max(_issued_before(db, doc_type), seed() if seed else 0)
        if db.get_bind().dialect.name == "postgresql":
            # Two requests may try to create the row at once; the loser re-reads it.
            try:
                with db.begin_nested():
                    db.add(DocumentSequence(doc_type=doc_type, year=CONTINUOUS, last_number=start))
            except IntegrityError:
                pass
        else:
            db.add(DocumentSequence(doc_type=doc_type, year=CONTINUOUS, last_number=start))
            db.flush()
        row = _locked_row(db, doc_type)
        assert row is not None
    row.last_number += 1
    db.flush()
    return format_number(doc_type, row.last_number)
