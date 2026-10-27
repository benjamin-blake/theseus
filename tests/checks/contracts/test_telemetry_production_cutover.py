"""Contract-text guards for PLAN-telemetry-production-flip (T2.36 c2, Decision 230, Decision 236).

The writer contract states the production binding (catalog ducklake_telemetry on the ducklake_telemetry_writer_prod login),
the blob-root write fence in place of the CI-write residual, both operator audit lines and the production invocation
measure; and no live text in .github/workflows/, .github/actions/, scripts/ or docs/contracts/*.yaml names the retired
heavy --lambda-telemetry flag (each contract's amendment_log and previous_versions blocks are history, so they are
skipped). Each predicate has red cases on synthetic input.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_CONTRACT = _ROOT / "docs" / "contracts" / "ducklake_telemetry_writer.yaml"
_LOGIN = "ducklake_telemetry_writer_prod"
_CATALOG = re.compile(r"\bducklake_telemetry\b")
_FENCE = "only the telemetry writer roles put to the blob root"
_OPERATOR_LINES = ("Operator writes:", "Integrity repair:")
_BARE_FLAG = re.compile(r"--lambda-telemetry(?![-\w])")
_HISTORY_KEY = re.compile(r"^(\s*)(amendment_log|previous_versions):")


def writer_contract_problems(doc: dict) -> list[str]:
    contract = doc.get("contract") or {}
    fields = {
        "description": contract.get("description") or "",
        "write_path": (contract.get("governance") or {}).get("write_path") or "",
    }
    problems = [
        f"{name} must name ducklake_telemetry and {_LOGIN}"
        for name, text in fields.items()
        if not (_CATALOG.search(text) and _LOGIN in text)
    ]
    invariants = [i for i in doc.get("audit_invariants") or [] if isinstance(i, str)]
    claim = [i for i in invariants if i.startswith("Claim-check rule")]
    if len(claim) != 1:
        problems.append(f"expected one claim-check invariant, found {len(claim)}")
    elif _FENCE not in claim[0] or "rec-4292" in claim[0] or "named residual" in claim[0]:
        problems.append("the claim-check invariant must state the Decision 230 cl.5 fence and name no residual owner")
    problems += [f"no audit invariant starts {p!r}" for p in _OPERATOR_LINES if not any(i.startswith(p) for i in invariants)]
    note = (contract.get("provisional_v0") or {}).get("surfacing_note") or ""
    if "AWS/Lambda Invocations" not in note:
        problems.append("the surfacing note must measure production_invocations as AWS/Lambda Invocations")
    return problems


def live_lines(text: str, *, skip_history: bool) -> Iterable[tuple[int, str]]:
    history_indent: int | None = None
    for number, line in enumerate(text.splitlines(), 1):
        indent = len(line) - len(line.lstrip())
        if history_indent is not None:
            if not line.strip() or indent > history_indent or (indent == history_indent and line.lstrip().startswith("- ")):
                continue
            history_indent = None
        match = _HISTORY_KEY.match(line) if skip_history else None
        if match:
            history_indent = len(match.group(1))
            continue
        yield number, line


def bare_flag_hits(files: dict[str, tuple[str, bool]]) -> list[str]:
    return [
        f"{name}:{number}"
        for name, (text, skip_history) in sorted(files.items())
        for number, line in live_lines(text, skip_history=skip_history)
        if _BARE_FLAG.search(line)
    ]


def _live_files() -> dict[str, tuple[str, bool]]:
    files: dict[str, tuple[str, bool]] = {}
    for tree in (_ROOT / ".github" / "workflows", _ROOT / ".github" / "actions", _ROOT / "scripts"):
        for path in sorted(tree.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                files[str(path.relative_to(_ROOT))] = (path.read_text(encoding="utf-8", errors="replace"), False)
    for path in sorted((_ROOT / "docs" / "contracts").glob("*.yaml")):
        files[str(path.relative_to(_ROOT))] = (path.read_text(encoding="utf-8"), True)
    return files


def test_writer_contract_states_the_production_binding_fence_and_operator_lines() -> None:
    doc = yaml.safe_load(_CONTRACT.read_text(encoding="utf-8"))
    assert writer_contract_problems(doc) == []
    claim_at = next(i for i, s in enumerate(doc["audit_invariants"]) if s.startswith("Claim-check rule"))
    mutations = [
        lambda d: d["contract"].update(
            description=d["contract"]["description"].replace("ducklake_telemetry ", "ducklake_smoke ")
        ),
        lambda d: d["contract"].update(description=d["contract"]["description"].replace(_LOGIN, "ducklake_telemetry_writer")),
        lambda d: d["contract"]["governance"].update(
            write_path=d["contract"]["governance"]["write_path"].replace(_LOGIN, "x")
        ),
        lambda d: d["audit_invariants"].__setitem__(claim_at, d["audit_invariants"][claim_at].replace(_FENCE, "x")),
        lambda d: d["audit_invariants"].__setitem__(
            claim_at, d["audit_invariants"][claim_at] + " A named residual owned by rec-4292."
        ),
        lambda d: d.update(audit_invariants=[i for i in d["audit_invariants"] if not i.startswith("Operator writes:")]),
        lambda d: d.update(audit_invariants=[i for i in d["audit_invariants"] if not i.startswith("Integrity repair:")]),
        lambda d: d["contract"]["provisional_v0"].update(surfacing_note="RequestCount by Verb"),
    ]
    for mutate in mutations:
        bad = copy.deepcopy(doc)
        mutate(bad)
        assert writer_contract_problems(bad), mutate


def test_no_live_text_names_the_retired_heavy_flag() -> None:
    assert bare_flag_hits(_live_files()) == []
    history = "contract:\n  id: x\namendment_log:\n  - date: d\n    summary: >-\n      ran --lambda-telemetry\n"
    flat_history = "previous_versions:\n- summary: --lambda-telemetry\n  note: x\n"
    green = {
        "a.yaml": (history, True),
        "b.yaml": (flat_history, True),
        "c.yml": ("run: x --lambda-telemetry-production\nrun: x --lambda-telemetry-smoke --profile p", False),
    }
    assert bare_flag_hits(green) == []
    red = {
        "after_history.yaml": (history + "notes: run --lambda-telemetry\n", True),
        "workflow.yml": ("run: x --lambda-telemetry --profile p", False),
        "eol.py": ('"""Run --lambda-telemetry"""', False),
        "history_off.yml": (history, False),
    }
    assert bare_flag_hits({**green, **red}) == ["after_history.yaml:7", "eol.py:1", "history_off.yml:6", "workflow.yml:1"]
