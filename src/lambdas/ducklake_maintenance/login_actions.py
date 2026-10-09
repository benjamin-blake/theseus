"""Decision 213 cl.5 provisioning verb for the telemetry writer's scoped catalog login.

One OPERATIONAL, human-invoked action on the ducklake_maintenance function -- invoked over 443 via
`aws lambda invoke` (never a public Function URL, never reachable from CI or PlatformDev), by PlatformAdmin or by
an ADMIN-container agent only under explicit human direction, presenting each mutation (Decision 213 cl.5).
No CC-web container has TCP/5432 egress, so the migration, the password set and the reach check all run here.

  - action_provision_telemetry_login: closed, no caller-supplied SQL, role or secret name; refuses unless
    confirm == "ducklake_telemetry_writer". As the ducklake_ops owner login it applies the password-free role
    migration (ducklake_telemetry_writer_role.sql, bundled beside this file) and records whether the owner is a
    neon_superuser member; it then sets the role's password from the scoped secret, and finally connects AS the
    scoped login to report its reach. Idempotent: a re-run is rotation, and the RDS swap's re-provision.

Every psycopg2.Error is re-raised as a DuckLakeRuntimeError carrying only the exception class and its SQLSTATE,
because a connect error message names the catalog host. Neither the response nor any log line carries the
host, the DSN or the password.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from src.common import ducklake_runtime as rt

TELEMETRY_LOGIN = "ducklake_telemetry_writer"
TELEMETRY_DSN_SECRET_ID = "agent-platform-ducklake-telemetry-writer-dsn"
_SQL_PATH = Path(__file__).with_name("ducklake_telemetry_writer_role.sql")
_NEON_SUPERUSER_QUERY = (
    "SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'neon_superuser') "
    "THEN pg_has_role(current_user, 'neon_superuser', 'member') END"
)
_SCOPE_QUERY = (
    "SELECT has_schema_privilege(current_user, 'ducklake_smoke', 'USAGE'), "
    "has_schema_privilege(current_user, 'ducklake_ops', 'USAGE'), "
    "has_schema_privilege(current_user, 'ducklake_smoke', 'CREATE'), "
    "has_schema_privilege(current_user, 'ducklake_ops', 'CREATE'), "
    "has_schema_privilege(current_user, 'public', 'CREATE'), "
    "has_database_privilege(current_user, current_database(), 'CREATE'), "
    "(SELECT rolconnlimit FROM pg_roles WHERE rolname = current_user)"
)
_SCOPE_KEYS = (
    "smoke_usage",
    "ops_usage",
    "smoke_create",
    "ops_create",
    "public_create",
    "database_create",
    "connection_limit",
)


def _scoped_dsn(owner: dict[str, str]) -> dict[str, str]:
    """Fetch the scoped login's secret and refuse unless it names this role on the owner's host over TLS."""
    try:
        scoped = rt.fetch_dsn(TELEMETRY_DSN_SECRET_ID)
    except RuntimeError:
        raise rt.DuckLakeRuntimeError("provision_telemetry_login: the scoped login secret is missing required keys") from None
    wrong = [
        field
        for field, expected in (
            ("username", TELEMETRY_LOGIN),
            ("host", owner["host"]),
            ("dbname", owner["dbname"]),
            ("sslmode", "require"),
        )
        if scoped.get(field) != expected
    ]
    if wrong:
        raise rt.DuckLakeRuntimeError(
            f"provision_telemetry_login: the scoped login secret differs from what is required in: {', '.join(wrong)}"
        )
    return scoped


def _apply_as_owner(psycopg2: Any, owner: dict[str, str]) -> tuple[bool | None, str, dict[str, str]]:
    """Owner session: record neon_superuser membership, run the migration, then set the password. Commits each step."""
    sql_bytes = _SQL_PATH.read_bytes()
    conn = psycopg2.connect(rt.libpq_conninfo(owner))
    try:
        with conn.cursor() as cur:
            cur.execute(_NEON_SUPERUSER_QUERY)
            member = cur.fetchone()[0]
            cur.execute(sql_bytes.decode("utf-8"))
        conn.commit()
        scoped = _scoped_dsn(owner)
        with conn.cursor() as cur:
            # Neon accepts only a plaintext password here; psycopg2 binds it client-side, so it is never
            # concatenated into SQL text by this module and never logged.
            cur.execute(f"ALTER ROLE {TELEMETRY_LOGIN} PASSWORD %s", (scoped["password"],))
        conn.commit()
    finally:
        conn.close()
    return member, hashlib.sha256(sql_bytes).hexdigest(), scoped


def _probe_as_scoped(psycopg2: Any, scoped: dict[str, str]) -> tuple[dict[str, Any], bool]:
    """Scoped session: report the login's privileges and whether it can read the smoke catalog's metadata."""
    conn = psycopg2.connect(rt.libpq_conninfo(scoped))
    try:
        with conn.cursor() as cur:
            cur.execute(_SCOPE_QUERY)
            scope = dict(zip(_SCOPE_KEYS, cur.fetchone(), strict=True))
        readable = True
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM ducklake_smoke.ducklake_metadata")
                cur.fetchone()
        except psycopg2.Error:
            conn.rollback()
            readable = False
    finally:
        conn.close()
    return scope, readable


def action_provision_telemetry_login(event: dict[str, Any], _con: Any) -> dict[str, Any]:
    """OPERATIONAL, human-invoked: provision the telemetry writer's scoped login and report its reach (Decision 213 cl.5)."""
    if event.get("confirm") != TELEMETRY_LOGIN:
        raise rt.DuckLakeRuntimeError(f"provision_telemetry_login requires confirm={TELEMETRY_LOGIN!r}")
    import psycopg2  # noqa: PLC0415

    try:
        member, migration_sha256, scoped = _apply_as_owner(psycopg2, rt.fetch_dsn())
        scope, readable = _probe_as_scoped(psycopg2, scoped)
    except psycopg2.Error as exc:
        raise rt.DuckLakeRuntimeError(
            f"provision_telemetry_login database error: {type(exc).__name__} sqlstate={exc.pgcode}"
        ) from None
    return {
        "ok": True,
        "migration_applied": True,
        "migration_sha256": migration_sha256,
        "password_set": True,
        "owner_is_neon_superuser_member": member,
        "scope": scope,
        "metadata_readable": readable,
    }
