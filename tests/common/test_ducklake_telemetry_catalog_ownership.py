"""Real Postgres 16 proof of the owner-provisioning split (Decision 216; rec-4294).

pytestmark integration: excluded from --pre and the full tier, run before merge by the implementer (CI gating of real-engine
tests is rec-4071). The fixture builds a Neon-shaped stage from DUCKLAKE_TEST_PG_ADMIN_DSN and FAILS, never skips (rec-4071),
when the variable is unset, an extension cannot load, or duckdb.__version__ differs from config/lambda/ducklake/version.yaml
(the Decision 99 lockstep pin). It refuses any non-local host so it can never touch Neon. Per test it drops and recreates the
database ducklake_ops, a NOLOGIN neon_superuser-like role (CREATEDB CREATEROLE BYPASSRLS, with and without pg_read_all_data and
pg_write_all_data) and the NON-superuser owner login ducklake_ops (CREATEDB CREATEROLE, member of that role), which owns the
database and creates schema ducklake_smoke; it then applies the REAL ducklake_telemetry_writer_role.sql as the owner.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

duckdb = pytest.importorskip("duckdb")
psycopg2 = pytest.importorskip("psycopg2")
yaml = pytest.importorskip("yaml")

from src.common import ducklake_telemetry_provision as prov  # noqa: E402
from src.common import ducklake_telemetry_registration as reg  # noqa: E402
from src.common.ducklake_scd2_schema import DuckLakeRuntimeError, load_field_semantics  # noqa: E402
from src.common.ducklake_telemetry_txn import run_telemetry_txn  # noqa: E402

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
ROLE_SQL = ROOT / "src" / "lambdas" / "ducklake_maintenance" / "ducklake_telemetry_writer_role.sql"
SEM = load_field_semantics()
SCOPED = "ducklake_telemetry_writer"
OWNER = "ducklake_ops"
SCHEMA = "ducklake_smoke"
PRINCIPAL = reg.CallerPrincipal("aws_account", "acct-under-test", "SomeRole")
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _admin_params() -> dict[str, str]:
    dsn = os.environ.get("DUCKLAKE_TEST_PG_ADMIN_DSN", "")
    if not dsn:
        pytest.fail("DUCKLAKE_TEST_PG_ADMIN_DSN is unset -- a skip is a FAIL (rec-4071)")
    params = psycopg2.extensions.parse_dsn(dsn)
    host = params.get("host", "")
    if host not in _LOCAL_HOSTS and not host.startswith("/"):
        pytest.fail("DUCKLAKE_TEST_PG_ADMIN_DSN must point at a local server; this test never touches a remote catalog")
    return params


def _pg(params: dict[str, str], user: str | None, db: str, sql: str) -> list[tuple[Any, ...]]:
    conn = psycopg2.connect(**{**params, "dbname": db, **({"user": user} if user else {})})
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall() if cur.description else []
    finally:
        conn.close()


@pytest.fixture(params=["read_all", "no_read_all"])
def stage(request: pytest.FixtureRequest, tmp_path: Path, _allow_network_for_integration: None) -> Any:
    params = _admin_params()
    pinned = yaml.safe_load((ROOT / "config" / "lambda" / "ducklake" / "version.yaml").read_text(encoding="utf-8"))
    if duckdb.__version__ != str(pinned["duckdb_version"]):
        pytest.fail(f"duckdb {duckdb.__version__} differs from the pinned {pinned['duckdb_version']} (Decision 99)")
    host, port = params.get("host", "127.0.0.1"), params.get("port", "5432")

    admin = lambda sql, user=None, db="postgres": _pg(params, user, db, sql)  # noqa: E731
    admin(f"DROP DATABASE IF EXISTS {OWNER} WITH (FORCE)")
    for role in (SCOPED, OWNER, "neon_superuser"):
        admin(f"DROP ROLE IF EXISTS {role}")
    admin("CREATE ROLE neon_superuser NOLOGIN CREATEDB CREATEROLE BYPASSRLS")
    if request.param == "read_all":
        admin("GRANT pg_read_all_data, pg_write_all_data TO neon_superuser")
    admin(
        f"CREATE ROLE {OWNER} LOGIN CREATEDB CREATEROLE IN ROLE neon_superuser PASSWORD 'test-only'"
    )  # pragma: allowlist secret
    admin(f"CREATE DATABASE {OWNER} OWNER {OWNER}")
    admin(f"CREATE SCHEMA {SCHEMA}", user=OWNER, db=OWNER)

    def connect(user: str) -> Any:
        c = duckdb.connect()
        try:
            c.execute("INSTALL ducklake; LOAD ducklake; INSTALL postgres; LOAD postgres")
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"extensions could not load -- a skip is a FAIL (rec-4071): {exc}")
        c.execute("SET ducklake_default_data_inlining_row_limit=0")
        c.execute("SET TimeZone='UTC'")
        c.execute(
            f"ATTACH 'ducklake:postgres:dbname={OWNER} host={host} port={port} user={user}' AS ops_catalog "
            f"(DATA_PATH '{tmp_path / 'data'}/', META_SCHEMA '{SCHEMA}')"
        )
        return c

    owner = connect(OWNER)
    owner.execute("CREATE TABLE ops_catalog.warm(a INT)")
    admin(ROLE_SQL.read_text(encoding="utf-8"), user=OWNER, db=OWNER)
    admin(f"ALTER ROLE {SCOPED} PASSWORD 'test-only'")  # pragma: allowlist secret
    opened: list[Any] = [owner]

    def scoped() -> Any:
        c = connect(SCOPED)
        opened.append(c)
        return c

    yield SimpleNamespace(
        owner=owner,
        scoped=scoped,
        sql=lambda stmt, user=OWNER: admin(stmt, user=user, db=OWNER),
        params=params,
        tmp=tmp_path,
        reconnect_owner=lambda: connect(OWNER),
    )
    for c in opened:
        c.close()


def _create(owner: Any) -> prov.CreateResult:
    return run_telemetry_txn(owner, lambda c: prov.create_telemetry_tables(c, semantics=SEM)).result


def _provision(con: Any) -> prov.ProvisionResult:
    return run_telemetry_txn(con, lambda c: prov.provision_telemetry_catalog(c, semantics=SEM)).result


def _append(con: Any, n: int) -> None:
    con.execute(
        "INSERT INTO ops_catalog.telemetry_sessions (event_id, session_started_at, producer, parser_version, "
        "created_timestamp, tenant_id, project_id, session_id) VALUES (?, now(), 'p', 2, now(), 't', 'p', 's')",
        [f"e{n}"],
    )


def _report(con: Any) -> prov.OwnershipReport:
    return prov.ownership_report(con, meta_schema=SCHEMA, scoped_login=SCOPED)


def test_role_sql_grants_the_scoped_login_no_create(stage: Any) -> None:
    priv = lambda schema, kind: stage.sql(f"SELECT has_schema_privilege('{SCOPED}', '{schema}', '{kind}')")[0][0]  # noqa: E731
    assert priv(SCHEMA, "USAGE") is True
    assert priv(SCHEMA, "CREATE") is False and priv("public", "CREATE") is False
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        stage.sql(f"CREATE TABLE {SCHEMA}.planted(x int)", user=SCOPED)
    assert prov.session_can_create(stage.scoped(), meta_schema=SCHEMA) is False
    assert prov.session_can_create(stage.owner, meta_schema=SCHEMA) is True


def test_owner_creates_then_scoped_login_verifies_seeds_and_writes(stage: Any) -> None:
    created = _create(stage.owner)
    assert len(created.created) == 9 and list(created.tables) == list(prov.target_tables(SEM))
    assert _report(stage.owner) == prov.OwnershipReport(0, True, False, False)

    scoped = stage.scoped()
    provisioned = _provision(scoped)
    assert provisioned.created == () and provisioned.counters == {"ops_tenants": 0, "ops_projects": 0}
    assert reg.register_tenant(scoped, PRINCIPAL).created is True
    assert reg.register_project(scoped, PRINCIPAL, "synthetic:ownership").created is True
    _append(scoped, 1)

    owner = stage.reconnect_owner()
    assert owner.execute("SELECT count(*) FROM ops_catalog.telemetry_sessions").fetchone()[0] == 1
    assert owner.execute("SELECT count(*) FROM ops_catalog.ops_tenants_current").fetchone()[0] == 1
    pg_dump = shutil.which("pg_dump") or next(iter(sorted(Path("/usr/lib/postgresql").glob("*/bin/pg_dump"))), None)
    assert pg_dump, "pg_dump not found"
    dump = subprocess.run(
        [str(pg_dump), "--format=custom", "-h", stage.params.get("host", "127.0.0.1"), "-p", stage.params.get("port", "5432"),
         "-U", OWNER, "-f", str(stage.tmp / "dump"), OWNER],
        capture_output=True,
        check=False,
    )  # fmt: skip
    assert dump.returncode == 0, dump.stderr.decode()[-300:]
    owner.execute("CALL ducklake_flush_inlined_data('ops_catalog')").fetchall()
    owner.execute("CALL ducklake_merge_adjacent_files('ops_catalog')").fetchall()

    owner.execute("CREATE TABLE ops_catalog.unrelated(b INT)")
    owner.execute("ALTER TABLE ops_catalog.unrelated ADD COLUMN c INT")
    _append(stage.scoped(), 2)
    assert _report(owner) == prov.OwnershipReport(0, True, False, False)
    assert _report(stage.scoped()) == prov.OwnershipReport(0, False, False, False)


def test_scoped_login_cannot_create_tables(stage: Any) -> None:
    scoped = stage.scoped()
    before = stage.sql(f"SELECT count(*) FROM pg_tables WHERE schemaname = '{SCHEMA}'")[0][0]
    with pytest.raises(DuckLakeRuntimeError, match="telemetry tables absent"):
        _provision(scoped)
    with pytest.raises(Exception, match="permission denied|Failed to commit"):
        scoped.execute("CREATE TABLE ops_catalog.scoped_new(x INT)")
    assert stage.sql(f"SELECT count(*) FROM pg_tables WHERE schemaname = '{SCHEMA}'")[0][0] == before


def test_create_is_idempotent_and_refuses_drift(stage: Any) -> None:
    assert len(_create(stage.owner).created) == 9
    assert _create(stage.owner).created == ()
    stage.owner.execute("ALTER TABLE ops_catalog.telemetry_sessions ADD COLUMN extra_col VARCHAR")
    with pytest.raises(DuckLakeRuntimeError, match="telemetry_sessions: columns"):
        _create(stage.owner)
    scoped = stage.scoped()
    with pytest.raises(DuckLakeRuntimeError, match="telemetry_sessions: columns"):
        _provision(scoped)
    _append(scoped, 3)
    assert _report(stage.owner) == prov.OwnershipReport(0, True, False, False)


_NEW_COLUMNS = {
    "telemetry_sessions": ("harness_session_key", "checkout_sha", "checkout_base_sha", "checkout_dirty"),
    "telemetry_observations": (
        "usage_final",
        "usage_source",
        "requested_model",
        "reasoning_effort",
        "cache_creation_1h_tokens",
        "cache_creation_5m_tokens",
    ),
}


def _reduced_semantics() -> dict[str, Any]:
    import copy  # noqa: PLC0415

    sem = copy.deepcopy(SEM)
    for table, cols in _NEW_COLUMNS.items():
        for col in cols:
            del sem["ops_tables"][table]["columns"][col]
    return sem


def _append_with_new_columns(con: Any, n: int) -> None:
    con.execute(
        "INSERT INTO ops_catalog.telemetry_sessions (event_id, session_started_at, producer, parser_version, "
        "created_timestamp, tenant_id, project_id, session_id, harness_session_key, checkout_sha, checkout_dirty) "
        "VALUES (?, now(), 'p', 2, now(), 't', 'p', 's', 'session_x', ?, false)",
        [f"n{n}", "a" * 40],
    )


def test_owner_adds_a_missing_nullable_column_and_the_scoped_login_still_writes(stage: Any) -> None:
    reduced = _reduced_semantics()
    created = run_telemetry_txn(stage.owner, lambda c: prov.create_telemetry_tables(c, semantics=reduced)).result
    assert len(created.created) == 9 and created.added == ()

    warm = stage.scoped()
    run_telemetry_txn(warm, lambda c: prov.provision_telemetry_catalog(c, semantics=reduced))
    _append(warm, 1)

    added = _create(stage.owner)
    assert len(added.added) == 10 and added.created == ()

    for scoped in (warm, stage.scoped()):
        assert _provision(scoped).created == ()
        _append_with_new_columns(scoped, id(scoped))
    owner = stage.reconnect_owner()
    rows = owner.execute("SELECT count(*), count(checkout_sha) FROM ops_catalog.telemetry_sessions").fetchone()
    assert tuple(rows) == (3, 2)
    assert _report(owner) == prov.OwnershipReport(0, True, False, False)
    assert _report(stage.scoped()) == prov.OwnershipReport(0, False, False, False)
