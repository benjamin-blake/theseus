"""Pins the zero-delta mypy strictness flags adopted by Task 5 Unit 0 into [tool.mypy].

Decision 161 left pyproject.toml's [tool.mypy] block deliberately minimal; Unit 0 adopts
the five flags measured as exactly zero-delta on this tree. This module is the guard that
a later edit cannot silently drop them. Membership and value only -- never an exact key
count over the block, which Units 2-5 grow (tests/CLAUDE.md test-count coupling).
"""

from __future__ import annotations

import tomllib
from typing import Any

from scripts.checks import _common

_ADOPTED_FLAGS: tuple[str, ...] = (
    "warn_redundant_casts",
    "no_implicit_optional",
    "strict_equality",
    "warn_no_return",
    "check_untyped_defs",
)


def _mypy_block() -> dict[str, Any]:
    with open(_common.ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)["tool"]["mypy"]


class TestAdoptedMypyFlags:
    def test_zero_delta_strictness_flags_are_pinned(self) -> None:
        block = _mypy_block()

        missing = [flag for flag in _ADOPTED_FLAGS if flag not in block]
        assert not missing, f"[tool.mypy] is missing adopted strictness flag(s): {missing}"

        not_true = [flag for flag in _ADOPTED_FLAGS if block[flag] is not True]
        assert not not_true, f"[tool.mypy] flag(s) not the TOML boolean true: {not_true}"

        assert block["python_version"] == "3.12"
        assert block["disable_error_code"] == ["import-untyped"]
