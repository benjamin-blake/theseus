"""record_turn: the cursor-driven capture pass (Decision 207 R7 producer obligations).

Each pass re-parses the whole tree, then selects only rows whose emission condition holds now and did NOT hold
over the tree truncated to the cursor's per-file lines_consumed with the cursor's finalized flag -- so a
finalized tree that later grows (a resumed session) re-emits nothing already emitted, and incremental capture
equals one full parse. Data batches first, ONE telemetry_sessions batch LAST. No file writes, no network, no
writer call: the caller persists next_cursor only after every batch was written.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from src.telemetry.timestamps import epoch_ms
from src.turn_capture.cursor import CaptureCursor
from src.turn_capture.observations import build_observations
from src.turn_capture.sessions import build_agents, build_sessions
from src.turn_capture.streams import ParsedTree, parse_tree
from src.turn_capture.transcript import ROOT, TranscriptTree, read_lines, session_pin
from src.turn_capture.transcripts import Ctx, Sidecars, build_transcripts

PRODUCER = "claude_code"
PARSER_VERSION = 1
PRODUCER_VERSION = "turn-capture-3a"
BILLING_SHAPES = ("metered_marginal", "fixed_non_rollover_allowance")
TABLES = ("telemetry_observations", "telemetry_transcripts", "telemetry_agents", "telemetry_sessions")


@dataclass(frozen=True)
class CaptureResult:
    observations: list[dict[str, Any]]
    transcripts: list[dict[str, Any]]
    agents: list[dict[str, Any]]
    sessions: list[dict[str, Any]]
    next_cursor: CaptureCursor | None
    diagnostics: dict[str, int]

    @property
    def batches(self) -> list[tuple[str, list[dict[str, Any]]]]:
        """Write order: data tables first, the single sessions batch last."""
        return list(zip(TABLES, (self.observations, self.transcripts, self.agents, self.sessions), strict=True))


def _build_all(parsed: ParsedTree, ctx: Ctx, sidecars: Sidecars, diag: Counter[str]) -> dict[str, list[dict[str, Any]]]:
    built = {
        "telemetry_observations": build_observations(parsed, ctx, diag),
        "telemetry_transcripts": build_transcripts(parsed, ctx, sidecars, diag),
        "telemetry_agents": build_agents(parsed, ctx),
        "telemetry_sessions": build_sessions(parsed, ctx),
    }
    for table, rows in built.items():
        seen: set[str] = set()
        unique = []
        for row in rows:
            if row["external_ref"] in seen:
                diag["duplicate_refs"] += 1
                continue
            seen.add(row["external_ref"])
            unique.append(row)
        built[table] = unique
    return built


def record_turn(
    tree: TranscriptTree,
    cursor: CaptureCursor | None,
    *,
    project_ref: str,
    billing_shape: str = "fixed_non_rollover_allowance",
    session_final: bool = False,
) -> CaptureResult:
    if billing_shape not in BILLING_SHAPES:
        raise ValueError(f"billing_shape must be one of {BILLING_SHAPES}")
    if not project_ref:
        raise ValueError("project_ref is required")
    root = tree.read(ROOT)
    pin = session_pin(read_lines(root or b""))
    if pin is None:
        return CaptureResult([], [], [], [], None, {})
    started_ms = epoch_ms(pin)
    base = None
    if cursor is not None:
        cursor.check_pins(
            root_session_ref=tree.session_id,
            project_ref=project_ref,
            billing_shape=billing_shape,
            session_started_at_ms=started_ms,
        )
        base = (
            cursor if (cursor.producer, cursor.parser_version) == (PRODUCER, PARSER_VERSION) else cursor.reset(PARSER_VERSION)
        )
    ctx = Ctx(PRODUCER, PRODUCER_VERSION, PARSER_VERSION, pin, billing_shape)
    diag: Counter[str] = Counter()
    parsed = parse_tree(tree, None, session_final)
    sidecars = Sidecars(tree, base)
    built = _build_all(parsed, ctx, sidecars, diag)
    prior: set[tuple[str, str]] = set()
    if base is not None:
        old = parse_tree(tree, base.lines_consumed, base.finalized)
        old_built = _build_all(old, ctx, Sidecars(tree, base), Counter())
        prior = {(t, r["external_ref"]) for t, rows in old_built.items() for r in rows}
    fresh = {t: [r for r in rows if (t, r["external_ref"]) not in prior] for t, rows in built.items()}
    diag.update(parsed.diag)
    nxt = CaptureCursor(
        PRODUCER,
        PARSER_VERSION,
        tree.session_id,
        project_ref,
        billing_shape,
        started_ms,
        lines_consumed=dict(parsed.lines_total),
        sidecars={**(base.sidecars if base else {}), **sidecars.used},
        finalized=session_final or bool(base and base.finalized),
    )
    return CaptureResult(
        fresh[TABLES[0]], fresh[TABLES[1]], fresh[TABLES[2]], fresh[TABLES[3]], nxt, dict(sorted(diag.items()))
    )
