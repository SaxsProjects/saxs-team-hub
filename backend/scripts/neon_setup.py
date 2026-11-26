"""One-time production database setup on Neon (PostgreSQL), with least-privilege logins.

    python -m scripts.neon_setup <owner-env-file> <output-env-file>          # before the first deploy
    python -m scripts.neon_setup <owner-env-file> <output-env-file> --after-migrate

<owner-env-file> holds `DATABASE_URL=` for the Neon project owner (from the Neon console).
The script never prints a password or URL. It writes the results to <output-env-file>, which
should live in a folder only you can read.

What it sets up:
- database `teamhub`, owned by `teamhub_migrator` (runs migrations, owns the tables)
- `teamhub_app`: the running API. It can read and write rows but never create, alter or drop
  tables, has a connection cap, and has statement and lock timeouts so a stuck query cannot hang it
- nobody else (PUBLIC) can connect to the database or create objects in it
- connections require TLS with channel binding (protects the password against a man in the middle)
- `--after-migrate`: also removes UPDATE/DELETE/TRUNCATE on `audit_log` from the app login
  (the table trigger already blocks them; this is a second, independent lock)

It also generates SECRET_KEY, FIELD_ENCRYPTION_KEY and JOBS_TOKEN if the output file lacks them.
Running it again keeps existing passwords and keys (it only fills in what is missing).
"""

import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

import psycopg
from cryptography.fernet import Fernet
from psycopg import sql

DB = "teamhub"
MIGRATOR = "teamhub_migrator"
APP = "teamhub_app"


def read_env(path: Path) -> dict[str, str]:
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env(path: Path, values: dict[str, str]) -> None:
    """Write secrets readable by the owner only: mode 0600 on Linux/macOS. On Windows, keep the file
    in a folder whose ACL grants only your account (docs/deploy.md)."""
    data = "".join(f"{k}={v}\n" for k, v in values.items()).encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.chmod(path, 0o600)  # also tightens a file that already existed


def password_of(url: str) -> str | None:
    return urlsplit(url).password if url else None


def role_url(owner_url: str, role: str, password: str) -> str:
    host = urlsplit(owner_url).hostname
    port = urlsplit(owner_url).port
    hostport = f"{host}:{port}" if port else host
    return f"postgresql://{role}:{quote(password, safe='')}@{hostport}/{DB}?sslmode=require&channel_binding=require"


def ensure_role(cur, role: str, password: str, *, limit: int, settings: dict[str, str]) -> None:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    exists = cur.fetchone()
    # The safety attributes are set at creation. Re-stating them on ALTER fails on Neon, where only a
    # superuser may mention SUPERUSER/REPLICATION, so a re-run only refreshes the password and limit
    # and then checks the attributes are still safe.
    attrs = "" if exists else " NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
    cur.execute(
        sql.SQL("{} ROLE {} LOGIN PASSWORD {}" + attrs + " CONNECTION LIMIT {}").format(
            sql.SQL("ALTER" if exists else "CREATE"), sql.Identifier(role), sql.Literal(password), sql.Literal(limit)
        )
    )
    cur.execute(
        "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls FROM pg_roles WHERE rolname = %s",
        (role,),
    )
    if cur.fetchone()[0]:
        raise SystemExit(f"{role} has a privileged attribute; remove it in the Neon console before continuing")
    for name, value in settings.items():
        cur.execute(sql.SQL("ALTER ROLE {} SET {} = {}").format(sql.Identifier(role), sql.Identifier(name), sql.Literal(value)))


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    owner_url = read_env(Path(argv[1])).get("DATABASE_URL", "")
    if not owner_url.startswith(("postgresql://", "postgres://")):
        print("error: the owner file has no PostgreSQL DATABASE_URL")
        return 2
    out_path = Path(argv[2])
    out = read_env(out_path)
    after_migrate = "--after-migrate" in argv

    migrator_pw = password_of(out.get("MIGRATION_DATABASE_URL", "")) or secrets.token_urlsafe(32)
    app_pw = password_of(out.get("DATABASE_URL", "")) or secrets.token_urlsafe(32)

    with psycopg.connect(owner_url, autocommit=True, connect_timeout=15) as conn, conn.cursor() as cur:
        ensure_role(cur, MIGRATOR, migrator_pw, limit=3, settings={"statement_timeout": "300s", "lock_timeout": "10s"})
        ensure_role(
            cur,
            APP,
            app_pw,
            limit=10,
            settings={
                "statement_timeout": "15s",
                "lock_timeout": "5s",
                "idle_in_transaction_session_timeout": "60s",
            },
        )
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB,))
        if not cur.fetchone():
            # The owner must be able to act as the migrator to hand it the database.
            cur.execute(sql.SQL("GRANT {} TO CURRENT_USER").format(sql.Identifier(MIGRATOR)))
            cur.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(DB), sql.Identifier(MIGRATOR)))
        cur.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(DB)))
        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(DB), sql.Identifier(APP)))

    migrator_url = role_url(owner_url, MIGRATOR, migrator_pw)
    with psycopg.connect(migrator_url, autocommit=True, connect_timeout=15) as conn, conn.cursor() as cur:
        cur.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(APP)))
        for stmt in (
            "ALTER DEFAULT PRIVILEGES FOR ROLE {m} IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {a}",
            "ALTER DEFAULT PRIVILEGES FOR ROLE {m} IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {a}",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {a}",
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {a}",
        ):
            cur.execute(sql.SQL(stmt).format(m=sql.Identifier(MIGRATOR), a=sql.Identifier(APP)))
        if after_migrate:
            cur.execute("SELECT to_regclass('public.audit_log') IS NOT NULL")
            if not cur.fetchone()[0]:
                print("error: audit_log does not exist yet; deploy (migrate) first")
                return 1
            cur.execute(sql.SQL("REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM {}").format(sql.Identifier(APP)))
            cur.execute(sql.SQL("REVOKE TRUNCATE ON ALL TABLES IN SCHEMA public FROM {}").format(sql.Identifier(APP)))

    out["DATABASE_URL"] = role_url(owner_url, APP, app_pw)
    out["MIGRATION_DATABASE_URL"] = migrator_url
    out.setdefault("SECRET_KEY", secrets.token_urlsafe(48))
    out.setdefault("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    out.setdefault("JOBS_TOKEN", secrets.token_urlsafe(32))
    write_env(out_path, out)

    # Prove the app login is limited, without printing anything secret.
    with psycopg.connect(out["DATABASE_URL"], autocommit=True, connect_timeout=15) as conn, conn.cursor() as cur:
        cur.execute("SELECT current_user, current_setting('statement_timeout'), current_setting('ssl', true)")
        user, timeout, _ = cur.fetchone()
        try:
            cur.execute("CREATE TABLE should_fail (id int)")
            print("FAIL: the app login could create a table")
            return 1
        except psycopg.errors.InsufficientPrivilege:
            pass
        tls = conn.pgconn.ssl_in_use  # client side: Neon's proxy terminates TLS before the database
    print(f"ok: database '{DB}' ready; app login '{user}' cannot create tables; statement_timeout={timeout}")
    print(f"ok: TLS on the app connection: {bool(tls)}")
    print(f"ok: wrote DATABASE_URL, MIGRATION_DATABASE_URL and keys to {out_path} (values not shown)")
    if after_migrate:
        print("ok: app login can no longer UPDATE, DELETE or TRUNCATE audit_log")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
