"""Ratchets [tool.ruff.lint] select and proves every family named there is LIVE, not merely spelled.

Wave A adopted ten families this tree already satisfied; wave B adds the six that needed fixes first
(C4, ERA, ICN, INP, PIE, RET). The membership guard is a one-way ratchet -- MEMBERSHIP, never
equality -- so a later wave extends the same select line without editing this module, while dropping
an adopted family reddens it. Every selected family must also own a stable (non-preview) rule,
matched prefix-plus-digits, which keeps the numeric-prefix selector C4 resolvable and stops the
family `A` from absorbing AIR/ARG/ASYNC codes.

The coupling (rec-3572) stops a family being DECLARED adopted while carrying zero firing evidence:
_ADOPTED_FAMILIES minus _SEPARATELY_GUARDED_FAMILIES must equal _FIRING_FIXTURES exactly, and every
family named in select must be declared here at all, so a family reaching select alone fails too.
The only escape hatch is _SEPARATELY_GUARDED_FAMILIES, and it is not free: each family listed there
owes a dedicated test on TestSelectedFamiliesAreLive. FA is its one entry and the reason it exists --
FA100 and FA102 both respect target-version, so neither can emit anything at py312, and FA's
dedicated guard asserts FA100 fires at py38 and stays silent at py312.

[tool.ruff.lint.per-file-ignores] is pinned by EXACT equality rather than membership, because growing
that table neuters a selected family in effect while it stays in select. Fixtures are synthetic,
written to tmp_path and linted through this repository's own pyproject config; none is checked in.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from scripts.checks import _common

_PYPROJECT = _common.ROOT / "pyproject.toml"

_PREEXISTING_FAMILIES: tuple[str, ...] = ("E", "F", "I", "W")
_ADOPTED_FAMILIES: tuple[str, ...] = (
    "A",
    "ASYNC",
    "C4",
    "ERA",
    "FA",
    "ICN",
    "INP",
    "INT",
    "ISC",
    "LOG",
    "PIE",
    "Q",
    "RET",
    "SLOT",
    "TID",
    "YTT",
)

_SEPARATELY_GUARDED_FAMILIES: tuple[str, ...] = ("FA",)

_FIRING_FIXTURES: dict[str, tuple[str, str]] = {
    "A": ("A001", "id = 1\n"),
    "ASYNC": ("ASYNC251", "import time\n\n\nasync def f() -> None:\n    time.sleep(1)\n"),
    "C4": ("C408", "x = dict()\n"),
    "ERA": ("ERA001", "x = 1\n# y = 2\n"),
    "ICN": ("ICN001", "import numpy\n\nx = numpy\n"),
    "INP": ("INP001", "x = 1\n"),
    "INT": ("INT001", 'def _(s: str) -> str:\n    return s\n\n\ny = _(f"{1}")\n'),
    "ISC": ("ISC001", 'x = "a" "b"\n'),
    "LOG": ("LOG009", "import logging\n\nx = logging.WARN\n"),
    "PIE": ("PIE810", 'def f(s: str) -> bool:\n    return s.startswith("a") or s.startswith("b")\n'),
    "Q": ("Q000", "x = 'a'\n"),
    "RET": ("RET505", "def f(x: int) -> int:\n    if x:\n        return 1\n    else:\n        return 2\n"),
    "SLOT": ("SLOT000", "class C(str):\n    pass\n"),
    "TID": ("TID252", "from ..pkg import thing\n"),
    "YTT": ("YTT201", "import sys\n\nx = sys.version_info[0] == 3\n"),
}

_SANCTIONED_PER_FILE_IGNORES: dict[str, list[str]] = {"scripts/llm/utils.py": ["RET505"]}

_FA_FIXTURE = "from typing import List\n\nx: List[int] = []\n"


def _ruff(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ruff", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _lint_config() -> dict:
    with open(_PYPROJECT, "rb") as handle:
        return tomllib.load(handle)["tool"]["ruff"]["lint"]


def _selected_families() -> list[str]:
    return _lint_config()["select"]


def _per_file_ignores() -> dict[str, list[str]]:
    return _lint_config().get("per-file-ignores", {})


def _lint_through_repo_config(fixture: Path, *extra: str) -> str:
    done = _ruff("check", "--config", str(_PYPROJECT), "--no-cache", "--output-format=concise", *extra, str(fixture))
    return done.stdout + done.stderr


def _stable_rule_codes() -> list[str]:
    done = _ruff("rule", "--all", "--output-format=json")
    return [rule["code"] for rule in json.loads(done.stdout) if not rule["preview"]]


def _owns_a_stable_rule(family: str, stable_codes: list[str]) -> bool:
    return any(code.startswith(family) and code[len(family) :].isdigit() for code in stable_codes)


def _dedicated_live_tests(family: str) -> list[str]:
    prefix = f"test_{family.lower()}_"
    return sorted(name for name in dir(TestSelectedFamiliesAreLive) if name.startswith(prefix))


class TestRuffSelectRatchet:
    def test_adopted_and_preexisting_families_are_all_present(self) -> None:
        selected = set(_selected_families())
        missing = sorted(f for f in (*_PREEXISTING_FAMILIES, *_ADOPTED_FAMILIES) if f not in selected)
        assert not missing, f"[tool.ruff.lint] select no longer names rule family/families: {missing}"

    def test_select_names_no_family_twice(self) -> None:
        selected = _selected_families()
        duplicates = sorted({f for f in selected if selected.count(f) > 1})
        assert not duplicates, f"[tool.ruff.lint] select names family/families more than once: {duplicates}"

    def test_every_selected_family_owns_a_stable_rule(self) -> None:
        stable_codes = _stable_rule_codes()
        assert stable_codes, "ruff reported no stable rules at all"
        inert = sorted(f for f in _selected_families() if not _owns_a_stable_rule(f, stable_codes))
        assert not inert, f"[tool.ruff.lint] select names family/families with no stable rule: {inert}"

    def test_every_adopted_family_has_firing_evidence(self) -> None:
        owed = set(_ADOPTED_FAMILIES) - set(_SEPARATELY_GUARDED_FAMILIES)
        assert owed == set(_FIRING_FIXTURES), (
            "every adopted family that is not separately guarded owes a firing fixture -- "
            f"adopted without one: {sorted(owed - set(_FIRING_FIXTURES))}; "
            f"fixture for an unadopted family: {sorted(set(_FIRING_FIXTURES) - owed)}"
        )
        declared = {*_ADOPTED_FAMILIES, *_PREEXISTING_FAMILIES}
        undeclared = sorted(f for f in _selected_families() if f not in declared)
        assert not undeclared, (
            "[tool.ruff.lint] select names family/families this module never declares, so they carry no "
            f"firing evidence at all: {undeclared}"
        )

    def test_separately_guarded_families_each_own_a_dedicated_test(self) -> None:
        unguarded = sorted(f for f in _SEPARATELY_GUARDED_FAMILIES if not _dedicated_live_tests(f))
        assert not unguarded, (
            "a family is exempt from the firing-fixture coupling only while it owns a dedicated test on "
            f"TestSelectedFamiliesAreLive: {unguarded}"
        )


class TestPerFileIgnoresAreExactlySanctioned:
    def test_per_file_ignores_hold_exactly_the_sanctioned_entries(self) -> None:
        assert _per_file_ignores() == _SANCTIONED_PER_FILE_IGNORES, (
            "[tool.ruff.lint.per-file-ignores] must hold exactly the sanctioned entries -- growing it "
            f"neuters a selected family in effect: {_per_file_ignores()}"
        )


class TestSelectedFamiliesAreLive:
    @pytest.mark.parametrize("family", sorted(_FIRING_FIXTURES), ids=sorted(_FIRING_FIXTURES))
    def test_adopted_family_fires_on_a_synthetic_violation(self, family: str, tmp_path: Path) -> None:
        code, source = _FIRING_FIXTURES[family]
        fixture = tmp_path / f"{family.lower()}_violation.py"
        fixture.write_text(source, encoding="utf-8")
        output = _lint_through_repo_config(fixture)
        assert f" {code} " in output, f"{family} is named in select but {code} did not fire:\n{output}"

    def test_fa_is_target_version_gated_and_inert_at_py312(self, tmp_path: Path) -> None:
        fixture = tmp_path / "fa_violation.py"
        fixture.write_text(_FA_FIXTURE, encoding="utf-8")
        below = _lint_through_repo_config(fixture, "--target-version", "py38")
        assert " FA100 " in below, f"FA is named in select but FA100 stayed silent even at py38:\n{below}"
        at_target = _lint_through_repo_config(fixture)
        assert " FA100 " not in at_target, f"FA100 fired at py312; target-version changed:\n{at_target}"
