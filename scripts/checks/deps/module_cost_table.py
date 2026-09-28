"""Per-module measured test cost: the table's format, generator, base-ref reader and pricing function
(Decision 208, amends Decision 182).

The fast tier's test half is budgeted from what each selected test module MEASURABLY costs, not from
how many modules were selected. This module owns the table that makes that possible:

* ``generate`` -- sums junit testcase ``time`` per test module (grouped by the testcase ``file``
  attribute, which pytest emits only under ``-o junit_family=xunit1``).
* the CLI -- writes ``config/agent/fast_tier/module_costs.json`` from one or more junit files. The
  committed table is GENERATED (its first key carries the regeneration command), never hand-edited.
* ``read_at_base_ref`` -- reads the committed table from the merge-base with origin/main, never the
  working tree, so a PR cannot raise its own allowance by editing the table it is judged against.
  ``absent`` means ONLY "the merge-base resolves and the path does not exist there" (the installing
  PR); every other failure is ``unreadable`` (fail closed, Decision 55).
* ``selection_cost`` -- prices a selection: table cost per known module, the table's 90th percentile
  for an unknown ``test_*.py`` (the likeliest unknown module is the PR's own new test), zero for any
  path that never appears in junit (conftest.py, fixtures, non-test files).

Stdlib only at module scope: scripts/validate.py imports selection_budget, which imports this, on the
``--terraform-only`` path where yaml and networkx are unavailable.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import statistics
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

TABLE_RELATIVE_PATH = "config/agent/fast_tier/module_costs.json"
_REGENERATE_COMMAND = (
    "bin/venv-python -m pytest tests -m 'not integration' -n auto -q -o junit_family=xunit1 --junitxml=<junit.xml> && "
    f"bin/venv-python -m scripts.checks.deps.module_cost_table --junit <junit.xml> --write {TABLE_RELATIVE_PATH}"
)
_GIT_TIMEOUT_SECONDS = 30


@dataclasses.dataclass(frozen=True)
class CostTableRead:
    """One read of the committed table: ``status`` is ok | absent | unreadable; ``costs`` maps a test
    module path to worker-seconds; ``default_cost`` prices an unknown test module (0.0 unless ok)."""

    status: str
    costs: dict[str, float]
    default_cost: float


def generate(junit_paths: list[Path | str]) -> dict[str, float]:
    """Sum junit testcase ``time`` per test module across every given junit file.

    A testcase without a ``file`` attribute is a loud error, never a classname guess: the attribute is
    only emitted under ``-o junit_family=xunit1``, and a guessed path would price the wrong module.
    """
    totals: dict[str, float] = {}
    for junit_path in junit_paths:
        for case in ET.parse(junit_path).getroot().iter("testcase"):
            module = case.get("file")
            if not module:
                raise ValueError(
                    f"{junit_path}: testcase {case.get('classname')}::{case.get('name')} has no `file` attribute -- "
                    "regenerate the junit with `-o junit_family=xunit1`"
                )
            totals[module] = totals.get(module, 0.0) + float(case.get("time") or 0.0)
    return {module: round(seconds, 3) for module, seconds in sorted(totals.items())}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_GIT_TIMEOUT_SECONDS,
        check=False,
    )


def _unreadable() -> CostTableRead:
    return CostTableRead("unreadable", {}, 0.0)


def read_at_base_ref(root: Path | str) -> CostTableRead:
    """Read the committed table at ``git merge-base HEAD origin/main`` (Decision 187 point 1).

    Never raises: any git, JSON or shape failure is ``unreadable``. ``absent`` is reserved for the
    one case where the merge-base resolved and ``git ls-tree`` found no such path -- the PR that
    installs the table -- so an unreadable base can never pick the looser legacy rule by mistake.
    """
    root_path = Path(root)
    try:
        merge_base = _git(root_path, "merge-base", "HEAD", "origin/main")
        if merge_base.returncode != 0 or not merge_base.stdout.strip():
            return _unreadable()
        base = merge_base.stdout.strip()
        listing = _git(root_path, "ls-tree", base, "--", TABLE_RELATIVE_PATH)
        if listing.returncode != 0:
            return _unreadable()
        if not listing.stdout.strip():
            return CostTableRead("absent", {}, 0.0)
        shown = _git(root_path, "show", f"{base}:{TABLE_RELATIVE_PATH}")
        if shown.returncode != 0:
            return _unreadable()
        modules = json.loads(shown.stdout)["modules"]
        costs = {str(path): float(seconds) for path, seconds in modules.items()}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, AttributeError):
        return _unreadable()
    if not costs:
        return _unreadable()
    values = list(costs.values())
    default_cost = statistics.quantiles(values, n=10, method="inclusive")[8] if len(values) > 1 else values[0]
    return CostTableRead("ok", costs, default_cost)


def selection_cost(selected: list[str], read: CostTableRead, root: Path | str, *, require_on_disk: bool = True) -> float:
    """Price a selection in worker-seconds: deduped, and with ``require_on_disk`` only paths that
    exist under ``root`` (the census-clamp analogue -- a corrupted or inflated selector cannot price
    phantom modules). A path absent from the table costs ``default_cost`` only when its basename is
    ``test_*.py``; every other unknown path costs 0.0 because it never appears in junit."""
    base = Path(root)
    total = 0.0
    for path in set(selected):
        if require_on_disk and not (base / path).exists():
            continue
        if path in read.costs:
            total += read.costs[path]
            continue
        name = path.rsplit("/", 1)[-1]
        if name.startswith("test_") and name.endswith(".py"):
            total += read.default_cost
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.checks.deps.module_cost_table",
        description="Generate the per-module test cost table from pytest junit (xunit1) output.",
    )
    parser.add_argument("--junit", action="append", required=True, help="a junit xml file (repeatable)")
    parser.add_argument("--write", required=True, help="path of the JSON table to write")
    args = parser.parse_args(argv)

    table = {
        "_banner": f"GENERATED -- DO NOT EDIT. Regenerate with: {_REGENERATE_COMMAND}",
        "generated_on": date.today().isoformat(),
        "source": f"pytest junit xunit1, {len(args.junit)} file(s)",
        "modules": generate(args.junit),
    }
    Path(args.write).write_text(json.dumps(table, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
