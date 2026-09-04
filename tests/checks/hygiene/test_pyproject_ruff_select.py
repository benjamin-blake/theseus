"""Ratchets [tool.ruff.lint] select and proves every family named there is LIVE, not merely spelled.

Wave A adopts ten rule families this tree already satisfies at zero violations. The guard is a
one-way ratchet: MEMBERSHIP, never equality, so a later wave extends the same select line without
editing this module, while dropping an adopted family reddens it. A family whose rules are all
preview-only would be inert once selected, so every selected family must own at least one stable
rule -- matched prefix-plus-digits, which keeps the numeric-prefix selector C4 resolvable and stops
the family `A` from absorbing AIR/ARG/ASYNC codes. FA is the family that makes the firing half worth
having: FA100 and FA102 both respect target-version, so neither can emit anything at py312; its
guard asserts FA100 fires against the same fixture at py38 and stays silent at py312. Fixtures are
synthetic, written to tmp_path and linted through this repository's own pyproject config; none is
checked in.
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
_ADOPTED_FAMILIES: tuple[str, ...] = ("A", "ASYNC", "FA", "INT", "ISC", "LOG", "Q", "SLOT", "TID", "YTT")

_FIRING_FIXTURES: dict[str, tuple[str, str]] = {
    "A": ("A001", "id = 1\n"),
    "ASYNC": ("ASYNC251", "import time\n\n\nasync def f() -> None:\n    time.sleep(1)\n"),
    "INT": ("INT001", 'def _(s: str) -> str:\n    return s\n\n\ny = _(f"{1}")\n'),
    "ISC": ("ISC001", 'x = "a" "b"\n'),
    "LOG": ("LOG009", "import logging\n\nx = logging.WARN\n"),
    "Q": ("Q000", "x = 'a'\n"),
    "SLOT": ("SLOT000", "class C(str):\n    pass\n"),
    "TID": ("TID252", "from ..pkg import thing\n"),
    "YTT": ("YTT201", "import sys\n\nx = sys.version_info[0] == 3\n"),
}

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


def _selected_families() -> list[str]:
    with open(_PYPROJECT, "rb") as handle:
        return tomllib.load(handle)["tool"]["ruff"]["lint"]["select"]


def _lint_through_repo_config(fixture: Path, *extra: str) -> str:
    done = _ruff("check", "--config", str(_PYPROJECT), "--no-cache", "--output-format=concise", *extra, str(fixture))
    return done.stdout + done.stderr


def _stable_rule_codes() -> list[str]:
    done = _ruff("rule", "--all", "--output-format=json")
    return [rule["code"] for rule in json.loads(done.stdout) if not rule["preview"]]


def _owns_a_stable_rule(family: str, stable_codes: list[str]) -> bool:
    return any(code.startswith(family) and code[len(family) :].isdigit() for code in stable_codes)


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
