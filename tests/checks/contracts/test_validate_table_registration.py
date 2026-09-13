"""Tests for scripts/checks/contracts/validate_table_registration.py (Decision 170 admission
control, T2.26 control-table-class-and-counter-conformance)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from scripts.checks import registry
from scripts.checks.contracts import _manifest
from scripts.checks.contracts import validate_table_registration as check

pytestmark = pytest.mark.unit


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_unregistered_create_table_fails(tmp_path: Path) -> None:
    _write(
        tmp_path / "pkg" / "mod.py",
        'CATALOG_ALIAS = "ops_catalog"\n'
        'ROGUE_TABLE = "ops_rogue_table"\n'
        "def f(con):\n"
        '    con.execute(f"CREATE TABLE IF NOT EXISTS {CATALOG_ALIAS}.{ROGUE_TABLE} (x INT)")\n',
    )
    failed: list[str] = []
    check.validate_table_registration(
        failed, src_dir=tmp_path / "pkg", known_tables={"ops_recommendations"}, catalog_alias="ops_catalog"
    )
    assert failed == ["Table registration admission control"]


def test_registered_create_table_passes(tmp_path: Path) -> None:
    _write(
        tmp_path / "pkg" / "mod.py",
        'CATALOG_ALIAS = "ops_catalog"\n'
        'KNOWN_TABLE = "ops_known_table"\n'
        "def f(con):\n"
        '    con.execute(f"CREATE TABLE IF NOT EXISTS {CATALOG_ALIAS}.{KNOWN_TABLE} (x INT)")\n',
    )
    failed: list[str] = []
    check.validate_table_registration(
        failed, src_dir=tmp_path / "pkg", known_tables={"ops_known_table"}, catalog_alias="ops_catalog"
    )
    assert failed == []


def test_resolves_module_level_constant_via_one_hop_import(tmp_path: Path) -> None:
    """A CATALOG_ALIAS imported `from X import CATALOG_ALIAS` resolves by reading X's own
    module-level literal -- mirrors the real ducklake_control_tables.py/ducklake_scd2_schema.py shape."""
    _write(tmp_path / "pkg" / "__init__.py", "")
    _write(tmp_path / "pkg" / "schema.py", 'CATALOG_ALIAS = "ops_catalog"\n')
    _write(
        tmp_path / "pkg" / "mod.py",
        "from pkg.schema import CATALOG_ALIAS\n"
        'KNOWN_TABLE = "ops_known_table"\n'
        "def f(con):\n"
        '    con.execute(f"CREATE TABLE IF NOT EXISTS {CATALOG_ALIAS}.{KNOWN_TABLE} (x INT)")\n',
    )
    failed: list[str] = []
    check.validate_table_registration(
        failed,
        src_dir=tmp_path / "pkg",
        known_tables={"ops_known_table"},
        catalog_alias="ops_catalog",
        import_root=tmp_path,
    )
    assert failed == []


def test_skips_unresolvable_dynamic_table_name(tmp_path: Path) -> None:
    """A table name built from an attribute expression (e.g. spec.history_table) is not a bare
    NAME placeholder and is silently skipped -- it is already registry-derived by construction."""
    _write(
        tmp_path / "pkg" / "mod.py",
        'CATALOG_ALIAS = "ops_catalog"\n'
        "def f(con, spec):\n"
        '    history = f"{CATALOG_ALIAS}.{spec.history_table}"\n'
        '    con.execute(f"CREATE TABLE IF NOT EXISTS {history} (x INT)")\n',
    )
    failed: list[str] = []
    check.validate_table_registration(failed, src_dir=tmp_path / "pkg", known_tables=set(), catalog_alias="ops_catalog")
    assert failed == []


def test_skips_a_different_non_governed_catalog(tmp_path: Path) -> None:
    """A CREATE TABLE resolving to a catalog other than the live CATALOG_ALIAS value (e.g. a spike
    probe's own private catalog) is out of scope, not a violation."""
    _write(
        tmp_path / "pkg" / "mod.py",
        '_CATALOG_ALIAS = "spike_lake"\n'
        'SPIKE_TABLE = "throwaway_ops"\n'
        "def f(con):\n"
        '    con.execute(f"CREATE TABLE IF NOT EXISTS {_CATALOG_ALIAS}.{SPIKE_TABLE} (x INT)")\n',
    )
    failed: list[str] = []
    check.validate_table_registration(failed, src_dir=tmp_path / "pkg", known_tables=set(), catalog_alias="ops_catalog")
    assert failed == []


def test_examined_reports_real_src_above_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """The admission check is not Decision 170 vacuous: it reports examined() over the real src/
    tree above zero, and the real repo passes with zero failures."""
    calls: list[tuple[int, str]] = []
    monkeypatch.setattr(registry, "examined", lambda count, *, unit="items": calls.append((count, unit)))
    failed: list[str] = []
    check.validate_table_registration(failed)
    assert failed == []
    assert calls, "examined() was never called"
    assert calls[0][0] > 0, "examined() must report a non-zero count over the real src/ tree"


def test_skips_name_unresolvable_via_either_path(tmp_path: Path) -> None:
    """A bare NAME placeholder that is neither a local module-level constant nor an imported name
    resolves to None (line 75's origin-is-None branch) and is silently skipped (line 162)."""
    _write(
        tmp_path / "pkg" / "mod.py",
        'CATALOG_ALIAS = "ops_catalog"\n'
        "def f(con, spec_table):\n"
        '    con.execute(f"CREATE TABLE IF NOT EXISTS {CATALOG_ALIAS}.{UNRESOLVABLE_NAME} (x INT)")\n',
    )
    failed: list[str] = []
    check.validate_table_registration(failed, src_dir=tmp_path / "pkg", known_tables=set(), catalog_alias="ops_catalog")
    assert failed == []


def test_import_target_module_does_not_exist_on_disk(tmp_path: Path) -> None:
    """An imported name whose dotted module has no corresponding file (_module_dotted_to_path
    returns None) resolves to None rather than raising."""
    _write(
        tmp_path / "pkg" / "mod.py",
        "from pkg.nonexistent_module import CATALOG_ALIAS\n"
        'KNOWN_TABLE = "ops_known_table"\n'
        "def f(con):\n"
        '    con.execute(f"CREATE TABLE IF NOT EXISTS {CATALOG_ALIAS}.{KNOWN_TABLE} (x INT)")\n',
    )
    failed: list[str] = []
    check.validate_table_registration(
        failed,
        src_dir=tmp_path / "pkg",
        known_tables={"ops_known_table"},
        catalog_alias="ops_catalog",
        import_root=tmp_path,
    )
    assert failed == []  # unresolvable catalog constant -- out of scope, not a violation


def test_import_target_module_has_syntax_error(tmp_path: Path) -> None:
    """An imported name whose origin module fails to parse resolves to None rather than raising."""
    _write(tmp_path / "pkg" / "__init__.py", "")
    _write(tmp_path / "pkg" / "schema.py", "CATALOG_ALIAS = ((( not valid python\n")
    _write(
        tmp_path / "pkg" / "mod.py",
        "from pkg.schema import CATALOG_ALIAS\n"
        'KNOWN_TABLE = "ops_known_table"\n'
        "def f(con):\n"
        '    con.execute(f"CREATE TABLE IF NOT EXISTS {CATALOG_ALIAS}.{KNOWN_TABLE} (x INT)")\n',
    )
    failed: list[str] = []
    check.validate_table_registration(
        failed,
        src_dir=tmp_path / "pkg",
        known_tables={"ops_known_table"},
        catalog_alias="ops_catalog",
        import_root=tmp_path,
    )
    assert failed == []


def test_file_with_syntax_error_is_skipped(tmp_path: Path) -> None:
    """A .py file whose raw text matches the CREATE TABLE regex but fails ast.parse is skipped
    (the check only inspects files it can actually parse)."""
    _write(
        tmp_path / "pkg" / "mod.py",
        "def broken(:\n    pass\nCREATE TABLE {CATALOG_ALIAS}.{ROGUE_TABLE}\n",
    )
    failed: list[str] = []
    check.validate_table_registration(failed, src_dir=tmp_path / "pkg", known_tables=set(), catalog_alias="ops_catalog")
    assert failed == []


def test_live_registry_injects_and_restores_sys_path(tmp_path: Path) -> None:
    """_live_registry inserts the given root into sys.path only if absent, and always removes it
    again afterward -- it must not leave a residual sys.path entry."""
    root_str = str(tmp_path)
    assert root_str not in sys.path
    result = check._live_registry(tmp_path)
    assert result is not None  # the real src.common registry is importable regardless of tmp_path
    assert root_str not in sys.path  # removed again in the finally block


def test_live_registry_returns_none_on_import_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An ImportError while loading the live registry resolves to None rather than raising."""
    monkeypatch.setitem(sys.modules, "src.common.ducklake_control_tables", None)
    result = check._live_registry(tmp_path)
    assert result is None


def test_live_registry_unavailable_fails_with_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the live registry cannot be imported and no test-isolation override is supplied, the
    check fails loudly (never silently no-ops) and declares a skipped() outcome."""
    monkeypatch.setattr(check, "_live_registry", lambda root: None)
    skipped_reasons: list[str] = []
    monkeypatch.setattr(registry, "skipped", lambda reason: skipped_reasons.append(reason))
    failed: list[str] = []
    check.validate_table_registration(failed)
    assert failed == ["Table registration admission control: could not import the live table registry"]
    assert skipped_reasons == ["live table registry unavailable"]


def test_check_is_registered() -> None:
    """The new check is registered and dispatched by the contracts domain (Decision 169)."""
    entry = next((e for e in _manifest.ENTRIES if e.name == "validate_table_registration"), None)
    assert entry is not None
    assert entry.module == "scripts.checks.contracts.validate_table_registration"
    assert entry.attr == "validate_table_registration"
    module = importlib.import_module(entry.module)
    fn = getattr(module, entry.attr)
    assert callable(fn)
    assert registry.resolve(entry.name) is fn
