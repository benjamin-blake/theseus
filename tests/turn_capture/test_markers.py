"""Mirror test for src/turn_capture/markers.py (rec-4172)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from src.turn_capture import markers
from src.turn_capture.markers import Marker, format_gate_marker, parse_markers

_CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "telemetry_observations.yaml"


def _contract_process_event_pattern() -> str:
    return yaml.safe_load(_CONTRACT.read_text(encoding="utf-8"))["fields"]["name"]["dq_intent"]["pattern_when"][0]["pattern"]


def test_gate_marker_round_trips() -> None:
    line = format_gate_marker("validate_scope_boundary")
    assert line == "GATE-FAILURE v1 source=gate check=validate_scope_boundary"
    assert parse_markers(f"noise\n{line}\n") == [Marker("gate", "validate_scope_boundary", 1)]


@pytest.mark.parametrize("bad", ["", "-lead", "a b", "a:b", "a" * 201, "café"])
def test_format_rejects_non_identifiers(bad: str) -> None:
    with pytest.raises(ValueError):
        format_gate_marker(bad)


@pytest.mark.parametrize(
    "line",
    [
        "x GATE-FAILURE v1 source=gate check=a",
        "GATE-FAILURE v1 source=gate check=a extra",
        "GATE-FAILURE v2 source=gate check=a",
        "GATE-FAILURE v1 source=hook check=a",
        "GATE-FAILURE v1 source=gate check=",
        "GATE-FAILURE v1 source=gate check=a b",
    ],
)
def test_partial_and_foreign_lines_are_not_markers(line: str) -> None:
    assert parse_markers(line) == []


def test_ansi_and_crlf_tolerated_and_lines_split_on_newline_only() -> None:
    text = "a\x0bb\r\n\x1b[31mGATE-FAILURE v1 source=gate check=x\x1b[0m\r\nlast"
    assert parse_markers(text) == [Marker("gate", "x", 1)]


_PRECOMMIT_BLOCKS = (
    "ruff....................................................................Failed\n"
    "- hook id: ruff\n"
    "- exit code: 1\n"
    "\n"
    "trailing-whitespace.....................................................Failed\n"
    "- hook id: trailing-whitespace\n"
    "- exit code: 1\n"
    "- files were modified by this hook\n"
    "\n"
    "fixer...................................................................Failed\n"
    "- hook id: fixer\n"
    "- files were modified by this hook\n"
    "\n"
    "verbose.................................................................Passed\n"
    "- hook id: verbose\n"
    "- duration: 0.01s\n"
    "- exit code: 0\n"
)


def test_precommit_block_rule_requires_nonzero_exit_or_modified_files() -> None:
    assert [m.signature for m in parse_markers(_PRECOMMIT_BLOCKS)] == ["ruff", "trailing-whitespace", "fixer"]
    assert {m.source for m in parse_markers(_PRECOMMIT_BLOCKS)} == {"precommit"}


def test_coloured_precommit_block_parses() -> None:
    text = "\x1b[1m- hook id: ruff\x1b[0m\r\n\x1b[2m- exit code: 1\x1b[0m\r\n"
    assert parse_markers(text) == [Marker("precommit", "ruff", 0)]


def test_precommit_hook_id_must_fit_the_signature_class() -> None:
    assert parse_markers("- hook id: bad id\n- exit code: 1\n") == []


def test_signature_pattern_equals_contract_class() -> None:
    contract = _contract_process_event_pattern()
    assert contract == f"^(hook|gate|precommit):{markers.SIGNATURE_PATTERN}$"
    assert re.fullmatch(markers.SIGNATURE_PATTERN, "validate_scope_boundary")
