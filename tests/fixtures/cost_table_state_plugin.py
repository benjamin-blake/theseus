"""VP step 9 forced-state proof plugin (Decision 208): loaded ONLY via
``-p tests.fixtures.cost_table_state_plugin``, never from a conftest, never autouse by default.

Its autouse fixture forces ``module_cost_table.read_at_base_ref`` from the environment variable
``FAST_TIER_COST_TABLE_STATE``: ``ok`` returns the WORKING-TREE
config/agent/fast_tier/module_costs.json as status ok (the state main sees once this plan merges);
``unreadable`` returns status unreadable. Module-level pins in the four budget test files still
win (closer scope, applied after this plugin's session-discovered fixture in pytest's setup
order), so this plugin exercises exactly the modules that do NOT pin -- proving on the installing
PR that they pass in the post-merge state.

Kept after merge on purpose: every rec-4125 table-refresh PR (and any later change to
module_cost_table.py) re-runs VP step 9's forced-state proof with it; delete it only together with
the cost-table seam.
"""

from __future__ import annotations

import json
import os
import statistics
from pathlib import Path

import pytest

from scripts.checks.deps import module_cost_table as mct

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TABLE_PATH = _REPO_ROOT / mct.TABLE_RELATIVE_PATH


def _forced_read() -> mct.CostTableRead:
    state = os.environ.get("FAST_TIER_COST_TABLE_STATE")
    if state == "unreadable":
        return mct.CostTableRead("unreadable", {}, 0.0)
    if state == "ok":
        table = json.loads(_TABLE_PATH.read_text(encoding="utf-8"))
        costs = {str(path): float(seconds) for path, seconds in table["modules"].items()}
        values = list(costs.values())
        default_cost = statistics.quantiles(values, n=10, method="inclusive")[8]
        return mct.CostTableRead("ok", costs, default_cost)
    raise RuntimeError(f"FAST_TIER_COST_TABLE_STATE must be 'ok' or 'unreadable', got {state!r}")


@pytest.fixture(autouse=True)
def _force_cost_table_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mct, "read_at_base_ref", lambda root: _forced_read())
