"""Shared builders for the budget_ingest concern-split test package (rec-3288 / D2-2b wave 4).

Decision 131 point 2 forbids one tests/** module importing from another test_* module, so the
fixtures every half needs live here -- `from .conftest import X` is permitted (the final module
component is `conftest`, not `test_*`). Same shape as the sibling code_drift package.

Every external dependency of scripts.convergence_health.budget_ingest is injected -- the GitHub
API caller, the artifact zip fetcher, the rec lists and the ops portal -- so no test in this
package touches the network or the real portal. Artifact archives are built in-memory.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any, Optional

from scripts.convergence_health import budget_ingest as bi

MARKERS = "Branch: claude/slow-branch. Dominant phase: pytest."

# The columns the `open_recs` named verb ACTUALLY projects -- src/common/ducklake_scd2_schema.py
# NAMED_READS: "SELECT id, title, context, created_timestamp, automatable ... WHERE status =
# 'open'". A live open row therefore carries NEITHER `status` (filtered server-side) NOR `source`.
# Open-rec fixtures are built to exactly this shape: supplying those two keys is what masked the
# matcher defect that made the OPEN half of the dedupe never fire in production.
LIVE_OPEN_REC_KEYS = ("id", "title", "context", "created_timestamp", "automatable")

# The title both budget-breach writers produce for the default block below (420s elapsed, outcome
# "breach", branch claude/slow-branch).
DEFAULT_TITLE = "Fast-tier budget breach (7.0 min) on claude/slow-branch"

DEFAULT_CREATED = "2026-08-26T10:00:00+00:00"


def _budget_block(
    *,
    outcome: str = "breach",
    branch: str = "claude/slow-branch",
    dominant_phase: Optional[str] = "pytest",
    elapsed_s: float = 420.0,
    limit_s: float = 300.0,
    run_id: str = "555",
    repository: str = "benjamin-blake/theseus",
) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "elapsed_s": elapsed_s,
        "elapsed_min": elapsed_s / 60,
        "limit_s": limit_s,
        "dominant_phase": dominant_phase,
        "phase_times": {"pytest": elapsed_s},
        "diff_file_count": 3,
        "diff_manifest": ["scripts/validate.py"],
        "branch": branch,
        "run_id": run_id,
        "repository": repository,
        "ci": True,
        "rec_filed": False,
        "rec_skipped_reason": "ci_no_portal_access",
    }


def _archive(payload: Any, *, member: str = "selection-manifest.json") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, payload if isinstance(payload, str) else json.dumps(payload))
    return buffer.getvalue()


def _artifact(
    artifact_id: int = 1,
    *,
    name: str = "selection-manifest",
    head_branch: str = "claude/slow-branch",
    head_sha: str = "a" * 40,
    expired: bool = False,
) -> dict[str, Any]:
    return {
        "id": artifact_id,
        "name": name,
        "expired": expired,
        "created_at": "2026-08-26T10:00:00Z",
        "archive_download_url": f"https://api.github.com/repos/o/r/actions/artifacts/{artifact_id}/zip",
        "workflow_run": {"id": 9000 + artifact_id, "head_branch": head_branch, "head_sha": head_sha},
    }


def _caller_for(artifacts: list[dict[str, Any]], total_count: Optional[int] = None) -> Any:
    def _caller(url: str) -> Any:
        assert "actions/artifacts" in url
        return {"artifacts": artifacts, "total_count": len(artifacts) if total_count is None else total_count}

    return _caller


def _fetcher_for(archives: dict[int, Any]) -> Any:
    def _fetch(url: str) -> bytes:
        artifact_id = int(url.rstrip("/zip").rsplit("/", 1)[-1])
        payload = archives[artifact_id]
        if isinstance(payload, bytes):
            return payload
        return _archive(payload)

    return _fetch


def _rec(
    rec_id: str = "rec-3000",
    *,
    context: str = MARKERS,
    title: str = DEFAULT_TITLE,
    created_timestamp: str = DEFAULT_CREATED,
    automatable: bool = False,
) -> dict[str, Any]:
    """An OPEN rec in the shape the `open_recs` verb really returns: the five projected columns."""
    return {
        "id": rec_id,
        "title": title,
        "context": context,
        "created_timestamp": created_timestamp,
        "automatable": automatable,
    }


def _full_rec(
    rec_id: str = "rec-3000",
    *,
    status: str = "closed",
    source: str = "budget_breach",
    context: str = MARKERS,
    title: str = DEFAULT_TITLE,
) -> dict[str, Any]:
    """A rec in the shape `rec_by_id` (SELECT *) returns -- `status` and `source` included.

    What the RESOLVED half of the dedupe consumes: _fetch_resolved_budget_recs hydrates each
    candidate through `rec_by_id`, so those rows genuinely do carry both keys.
    """
    return {**_rec(rec_id, context=context, title=title), "status": status, "source": source}


def _live_open(rec: dict[str, Any]) -> dict[str, Any]:
    """Project a stored (full) rec down to the five columns `open_recs` returns."""
    return {key: rec.get(key) for key in LIVE_OPEN_REC_KEYS}


def _ingest_one(**kwargs: Any) -> dict[str, Any]:
    """One tick over a single default breach artifact, with both rec lists defaulting to empty."""
    blocks = kwargs.pop("blocks", None) or [_budget_block()]
    artifacts = [_artifact(i + 1) for i in range(len(blocks))]
    archives = {i + 1: {"budget": block} for i, block in enumerate(blocks)}
    kwargs.setdefault("open_recs", [])
    kwargs.setdefault("resolved_recs", [])
    return bi.ingest_budget_breaches(gh_caller=_caller_for(artifacts), artifact_fetcher=_fetcher_for(archives), **kwargs)


class _ToyWarehouse:
    """A minimal in-memory ops_recommendations stand-in: file allocates an id, update merges.

    `open_recs` deliberately returns the LIVE projection (five columns, no status/source) rather
    than the stored rows, so a tick loop over this warehouse exercises what the reader really hands
    the matcher; `resolved_recs` stays full-shaped because its half hydrates through `rec_by_id`.
    """

    def __init__(self) -> None:
        self.recs: list[dict[str, Any]] = []
        self.writes = 0
        self._next_id = 4001

    def portal(self, action: str, fields: dict[str, Any]) -> Any:
        self.writes += 1
        if action == "file":
            rec_id = f"rec-{self._next_id}"
            self._next_id += 1
            self.recs.append({"id": rec_id, "created_timestamp": DEFAULT_CREATED, **fields})
            return rec_id
        stored = next(rec for rec in self.recs if rec["id"] == fields["id"])
        stored.update({key: value for key, value in fields.items() if key != "id"})
        return None

    def close(self, rec_id: str) -> None:
        next(rec for rec in self.recs if rec["id"] == rec_id)["status"] = "closed"

    @property
    def open_recs(self) -> list[dict[str, Any]]:
        return [_live_open(rec) for rec in self.recs if rec.get("status") == "open"]

    @property
    def resolved_recs(self) -> list[dict[str, Any]]:
        return [rec for rec in self.recs if rec.get("status") in bi.RESOLVED_REC_STATUSES]
