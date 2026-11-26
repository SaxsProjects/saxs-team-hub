"""Encrypted logical backups of the Team Hub database, with verify and restore.

    python -m scripts.backup generate-key            # once: a BACKUP_KEY for the password manager
    python -m scripts.backup backup FILE             # write an encrypted backup
    python -m scripts.backup verify FILE             # decrypt and count rows (no database needed)
    python -m scripts.backup restore FILE            # into an EMPTY database migrated to the same version

Uses MIGRATION_DATABASE_URL if set, otherwise DATABASE_URL, and the Fernet key in BACKUP_KEY. Keep
BACKUP_KEY apart from FIELD_ENCRYPTION_KEY, so one leaked key does not open both. Personal fields that the
app encrypts stay encrypted inside the backup too, so a restore also needs the same FIELD_ENCRYPTION_KEY.

The file is gzip-compressed JSON encrypted and authenticated with Fernet (AES-128-CBC + HMAC-SHA256):
any change to the file makes decryption fail instead of restoring tampered data. Nothing secret is printed.
"""

import base64
import gzip
import json
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import create_engine, func, insert, inspect, select, text

FORMAT = 1


def _encode(value):
    if isinstance(value, datetime):
        return {"__dt": value.isoformat()}
    if isinstance(value, date):
        return {"__d": value.isoformat()}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__b": base64.b64encode(bytes(value)).decode()}
    return value


def _decode(value):
    if isinstance(value, dict) and len(value) == 1:
        ((tag, raw),) = value.items()
        if tag == "__dt":
            return datetime.fromisoformat(raw)
        if tag == "__d":
            return date.fromisoformat(raw)
        if tag == "__b":
            return base64.b64decode(raw)
    return value


def _fernet() -> Fernet:
    key = os.environ.get("BACKUP_KEY", "").strip()
    if not key:
        raise SystemExit("Set BACKUP_KEY (python -m scripts.backup generate-key makes one)")
    try:
        return Fernet(key)
    except ValueError:
        raise SystemExit("BACKUP_KEY is not a valid Fernet key") from None


def _engine():
    from app.config import get_settings

    settings = get_settings()
    return create_engine(settings.migration_database_url or settings.database_url)


def _tables():
    import app.models  # noqa: F401 - registers every table on Base.metadata
    from app.db import Base

    return Base.metadata.sorted_tables  # parents before children


def _revision(conn) -> str | None:
    if not inspect(conn).has_table("alembic_version"):
        return None
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def dump(engine) -> dict:
    data = {"format": FORMAT, "created_at": datetime.now(UTC).isoformat(), "tables": {}}
    conn = engine.connect()
    if engine.dialect.name == "postgresql":
        # Every table is read from one snapshot, so the backup is consistent even while the app runs.
        conn = conn.execution_options(isolation_level="REPEATABLE READ")
    with conn:
        with conn.begin():
            data["alembic_revision"] = _revision(conn)
            for table in _tables():
                order = [c for c in table.primary_key.columns] or list(table.columns)
                rows = conn.execute(select(table).order_by(*order)).mappings().all()
                data["tables"][table.name] = [{k: _encode(v) for k, v in row.items()} for row in rows]
    return data


def seal(data: dict) -> bytes:
    payload = gzip.compress(json.dumps(data, separators=(",", ":")).encode("utf-8"))
    return _fernet().encrypt(payload)


def unseal(blob: bytes) -> dict:
    try:
        payload = _fernet().decrypt(blob)
    except InvalidToken:
        raise SystemExit("Cannot decrypt: wrong BACKUP_KEY, or the file was changed or damaged") from None
    data = json.loads(gzip.decompress(payload))
    if data.get("format") != FORMAT:
        raise SystemExit(f"Unsupported backup format {data.get('format')!r}")
    return data


def load(engine, data: dict) -> dict[str, int]:
    """Insert a backup into an empty database at the same migration revision, in one transaction."""
    tables = _tables()
    counts = {}
    with engine.begin() as conn:
        revision = _revision(conn)
        if revision != data["alembic_revision"]:
            raise SystemExit(
                f"Database is at revision {revision!r} but the backup is {data['alembic_revision']!r}; "
                "run `alembic upgrade` to the backup's revision first"
            )
        busy = [t.name for t in tables if conn.execute(select(func.count()).select_from(t)).scalar()]
        if busy:
            raise SystemExit("Refusing to restore into a database that already has data in: " + ", ".join(busy))
        for table in tables:
            rows = [{k: _decode(v) for k, v in row.items()} for row in data["tables"].get(table.name, [])]
            if rows:
                conn.execute(insert(table), rows)
            counts[table.name] = len(rows)
        if conn.dialect.name == "postgresql":
            # Rows came in with their ids; move each id sequence past them so new rows do not collide.
            for table in tables:
                if "id" in table.columns and counts[table.name]:
                    quoted = conn.dialect.identifier_preparer.quote(table.name)  # names come from our models
                    conn.execute(
                        text(f"SELECT setval(pg_get_serial_sequence(:t, 'id'), (SELECT MAX(id) FROM {quoted}))"),  # noqa: S608
                        {"t": table.name},
                    )
    return counts


def _summary(data: dict) -> str:
    total = sum(len(rows) for rows in data["tables"].values())
    busy = {name: len(rows) for name, rows in data["tables"].items() if rows}
    return f"{total} rows, revision {data['alembic_revision']}, taken {data['created_at']}: {busy}"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("generate-key", "backup", "verify", "restore"):
        print(__doc__)
        return 2
    command = argv[1]
    if command == "generate-key":
        print(Fernet.generate_key().decode())  # shown once, for the password manager
        return 0
    if len(argv) != 3:
        print(__doc__)
        return 2
    path = Path(argv[2])
    if command == "backup":
        data = dump(_engine())
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # never overwrite an older backup
        with os.fdopen(fd, "wb") as f:
            f.write(seal(data))
        unseal(path.read_bytes())  # prove the file just written can be read back
        print(f"ok: backup written and verified: {_summary(data)}")
    elif command == "verify":
        print(f"ok: {_summary(unseal(path.read_bytes()))}")
    else:
        counts = load(_engine(), unseal(path.read_bytes()))
        print(f"ok: restored {sum(counts.values())} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
