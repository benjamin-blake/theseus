"""Coverage home for src/common/ducklake_telemetry_provision.py (a recording fake connection, fast tier)."""

from __future__ import annotations

import re
from typing import Any

import pytest

from src.common import ducklake_telemetry_provision as prov
from src.common.ducklake_control_tables import resolve_control_spec
from src.common.ducklake_partition_spec import normalize_partition_spec
from src.common.ducklake_scd2_schema import DuckLakeRuntimeError, load_field_semantics, resolve_table_spec

SEM = load_field_semantics()
EVENTS = prov.event_table_names(SEM)
HISTORIES = {n: resolve_table_spec(n, SEM).history_table for n in prov.DIMENSIONS}
CURRENTS = {n: str(resolve_table_spec(n, SEM).current_table) for n in prov.DIMENSIONS}
NINE = sorted([*EVENTS, *HISTORIES.values(), *CURRENTS.values(), "ops_entity_counters"])


def _declared_transforms() -> dict[str, tuple[tuple[str, str], ...]]:
    out: dict[str, tuple[tuple[str, str], ...]] = {}
    for name in EVENTS:
        out[name] = normalize_partition_spec(SEM["ops_tables"][name]["partition"]["history"])
    for name in prov.DIMENSIONS:
        spec = resolve_table_spec(name, SEM)
        out[spec.history_table] = normalize_partition_spec(spec.partition_history)
        out[str(spec.current_table)] = normalize_partition_spec(str(spec.partition_current))
    out["ops_entity_counters"] = normalize_partition_spec(resolve_control_spec("ops_entity_counters").partition_key)
    return out


class _Cur:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None


class FakeCon:
    """Records every statement and answers the read-only metadata, count and counter reads from scripted state."""

    def __init__(
        self,
        existing: tuple[str, ...] = (),
        *,
        transforms: dict[str, tuple[tuple[str, str], ...]] | None = None,
        columns: dict[str, set[str]] | None = None,
        counts: dict[str, int] | None = None,
        counters: dict[str, list[int]] | None = None,
        extra_tables: tuple[str, ...] = (),
    ) -> None:
        self.sql: list[str] = []
        self.params: list[Any] = []
        self.existing = tuple(existing) + tuple(extra_tables)
        self.transforms = _declared_transforms() if transforms is None else transforms
        self.columns = columns if columns is not None else prov._declared_columns(SEM)
        self.counts = counts or {}
        self.counters = counters if counters is not None else {}

    def execute(self, sql: str, params: Any = None) -> _Cur:
        self.sql.append(sql)
        self.params.append(params)
        if "duckdb_tables()" in sql:
            return _Cur([(t,) for t in self.existing])
        if "ducklake_table WHERE" in sql:
            return _Cur([(self.existing.index(params[0]) + 1,)])
        if "ducklake_partition_info" in sql:
            table = self.existing[params[0] - 1]
            return _Cur([(params[0] * 10,)] if self.transforms.get(table) else [])
        if "ducklake_partition_column" in sql:
            table = self.existing[params[1] - 1]
            return _Cur([(t, c) for t, c in self.transforms[table]])
        if "information_schema.columns" in sql:
            return _Cur([(c,) for c in sorted(self.columns.get(params[1], set()))])
        if sql.startswith("SELECT count(*)"):
            table = sql.split(".")[1].split()[0]
            return _Cur([(self.counts.get(table, 0),)])
        if sql.startswith("SELECT current_value"):
            return _Cur([(v,) for v in self.counters.get(params[0], [])])
        if sql.startswith("DELETE"):
            self.counters.pop(params[0], None)
        if sql.startswith("INSERT"):
            self.counters[params[0]] = [params[1]]
        return _Cur([])

    def statements(self, *prefixes: str) -> list[str]:
        return [s for s in self.sql if s.startswith(prefixes)]


def _all_existing(**kw: Any) -> FakeCon:
    return FakeCon(tuple(NINE), counters={"ops_tenants": [0], "ops_projects": [0]}, **kw)


def test_provision_creates_and_partitions_every_table_before_any_write() -> None:
    con = FakeCon()
    result = prov.provision_telemetry_catalog(con, semantics=SEM)
    ddl = con.statements("CREATE TABLE", "ALTER TABLE")
    creates = [s for s in ddl if s.startswith("CREATE")]
    assert len(creates) == 9 and len(ddl) == 18
    first_write = min(i for i, s in enumerate(con.sql) if s.startswith(("INSERT", "DELETE")))
    assert all(con.sql.index(s) < first_write for s in ddl)
    for create in creates:
        table = create.split(".")[1].split()[0]
        alter = next(s for s in ddl if s.startswith("ALTER") and f".{table} SET PARTITIONED BY" in s)
        assert ddl.index(create) < ddl.index(alter)
    assert sorted(result.created) == sorted(set(NINE) | set(EVENTS))


def test_event_tables_carry_not_null_and_the_session_day_partition() -> None:
    con = FakeCon()
    prov.provision_telemetry_catalog(con, semantics=SEM)
    create = next(s for s in con.sql if s.startswith("CREATE TABLE ops_catalog.telemetry_sessions "))
    for column in (
        "event_id VARCHAR NOT NULL",
        "producer VARCHAR NOT NULL",
        "tenant_id VARCHAR NOT NULL",
        "project_id VARCHAR NOT NULL",
    ):
        assert column in create
    assert "session_started_at TIMESTAMP WITH TIME ZONE NOT NULL" in create
    alter = next(s for s in con.sql if s.startswith("ALTER TABLE ops_catalog.telemetry_sessions "))
    assert alter.endswith("SET PARTITIONED BY (year(session_started_at), month(session_started_at), day(session_started_at))")


def test_seed_touches_only_the_two_telemetry_counter_rows() -> None:
    con = FakeCon(counters={"ops_recommendations": [41]})
    prov.provision_telemetry_catalog(con, semantics=SEM)
    writes = [(s.split()[0], p[0]) for s, p in zip(con.sql, con.params, strict=True) if s.startswith(("INSERT", "DELETE"))]
    assert writes == [
        ("DELETE", "ops_tenants"),
        ("INSERT", "ops_tenants"),
        ("DELETE", "ops_projects"),
        ("INSERT", "ops_projects"),
    ]
    assert con.counters["ops_recommendations"] == [41]


def test_seed_never_lowers_a_counter() -> None:
    con = _all_existing(counts={CURRENTS["ops_tenants"]: 3, CURRENTS["ops_projects"]: 5})
    con.counters = {"ops_tenants": [7], "ops_projects": [2]}
    result = prov.provision_telemetry_catalog(con, semantics=SEM)
    assert con.counters["ops_tenants"] == [7] and con.counters["ops_projects"] == [5]
    assert result.counters == {"ops_tenants": 7, "ops_projects": 5}
    assert [s for s in con.sql if s.startswith("INSERT")] and not [s for s in con.sql if s.startswith(("CREATE", "ALTER"))]


def test_duplicated_counter_row_is_repaired_at_the_floor() -> None:
    con = _all_existing(counts={CURRENTS["ops_projects"]: 5})
    con.counters = {"ops_tenants": [0], "ops_projects": [9, 4]}
    result = prov.provision_telemetry_catalog(con, semantics=SEM)
    assert con.counters["ops_projects"] == [9] and result.counters["ops_projects"] == 9
    assert con.counters["ops_tenants"] == [0]


def test_provision_issues_no_drop_or_truncate() -> None:
    for con in (FakeCon(), _all_existing()):
        prov.provision_telemetry_catalog(con, semantics=SEM)
        assert not [s for s in con.sql if re.search(r"\b(DROP|TRUNCATE)\b", s, re.IGNORECASE)]
    with open(prov.__file__, encoding="utf-8") as fh:
        source = fh.read().upper()
    assert "DROP TABLE" not in source and "TRUNCATE TABLE" not in source and "FORCE_RECREATE" not in source


def test_existing_tables_are_never_re_altered() -> None:
    con = _all_existing(extra_tables=("unrelated_smoke_table",))
    result = prov.provision_telemetry_catalog(con, semantics=SEM)
    assert not con.statements("CREATE", "ALTER", "DROP") and result.created == ()
    assert "unrelated_smoke_table" not in str(con.params)


def test_half_present_dimension_pair_fails_loud() -> None:
    con = FakeCon((HISTORIES["ops_tenants"],))
    with pytest.raises(DuckLakeRuntimeError, match="half-present"):
        prov.provision_telemetry_catalog(con, semantics=SEM)
    assert not con.statements("CREATE", "ALTER", "INSERT", "DELETE")


def test_preexisting_table_with_drifted_partition_fails_before_any_seed() -> None:
    transforms = _declared_transforms()
    transforms["ops_entity_counters"] = ()
    con = _all_existing(transforms=transforms)
    with pytest.raises(DuckLakeRuntimeError, match="ops_entity_counters: partitions"):
        prov.provision_telemetry_catalog(con, semantics=SEM)
    assert not con.statements("CREATE", "ALTER", "INSERT", "DELETE")


def test_preexisting_table_with_drifted_columns_fails_before_any_seed() -> None:
    columns = prov._declared_columns(SEM)
    columns["telemetry_sessions"] = (columns["telemetry_sessions"] - {"event_id"}) | {"stray"}
    con = _all_existing(columns=columns)
    with pytest.raises(DuckLakeRuntimeError, match=r"telemetry_sessions: columns missing \['event_id'\] extra \['stray'\]"):
        prov.provision_telemetry_catalog(con, semantics=SEM)
    assert not con.statements("CREATE", "ALTER", "INSERT", "DELETE")


def test_provision_never_enables_inlining() -> None:
    con = FakeCon()
    prov.provision_telemetry_catalog(con, semantics=SEM)
    assert not [s for s in con.sql if "inlining" in s.lower()]


def test_provision_reports_counters_and_tables() -> None:
    con = FakeCon(counts={CURRENTS["ops_tenants"]: 0})
    result = prov.provision_telemetry_catalog(con, semantics=SEM)
    assert list(result.tables) == NINE and len(result.tables) == 9
    assert result.counters == {"ops_tenants": 0, "ops_projects": 0}
