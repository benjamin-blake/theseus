"""Conformance against REAL Claude Code transcripts on the implementer's machine (operator choice 2026-09-28).

pytest.mark.integration. Nothing from the transcripts is committed (the repository is public): failure messages and the
printed report carry counts, types, booleans and hashed session ids only, never content. The raw walk below is
independent of src.turn_capture.transcript / streams. Transcripts are read from TURN_CAPTURE_REAL_TRANSCRIPTS (an
os.pathsep-separated list of root .jsonl files or directories) else ~/.claude/projects/*/*.jsonl, and snapshotted to a
temp dir first so a live, growing transcript cannot change between passes. The test FAILS when none exist.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from src.telemetry.identity import canonical_ref
from src.telemetry.timestamps import TimestampError, parse_iso8601_utc
from src.turn_capture.record_turn import record_turn
from src.turn_capture.scrub import scrub_text
from src.turn_capture.transcript import ROOT, FsTree
from tests.fixtures.turn_capture_ducklake import create_tables, load_specs, open_local_lake

pytestmark = pytest.mark.integration

PROJECT_REF = "real/conformance"
MAX_FULL_CUT_LINES = 3000
USAGE = (
    ("tokens_input", "input_tokens"),
    ("tokens_output", "output_tokens"),
    ("tokens_cache_read", "cache_read_input_tokens"),
    ("tokens_cache_creation", "cache_creation_input_tokens"),
)


def _discover() -> list[Path]:
    override = os.environ.get("TURN_CAPTURE_REAL_TRANSCRIPTS")
    if not override:
        return sorted(Path.home().glob(".claude/projects/*/*.jsonl"))
    found: list[Path] = []
    for item in override.split(os.pathsep):
        path = Path(item).expanduser()
        found += sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
    return found


def _snapshot(paths: list[Path], into: Path) -> list[Path]:
    out = []
    for i, src in enumerate(paths):
        dest = into / f"t{i}"
        dest.mkdir(parents=True)
        shutil.copy2(src, dest / src.name)
        session_dir = src.parent / src.stem
        if session_dir.is_dir():
            shutil.copytree(session_dir, dest / src.stem)
        out.append(dest / src.name)
    return out


def _hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()[:10]


def raw_lines(path: Path, limit: int | None = None) -> tuple[list[tuple[int, dict[str, Any]]], int]:
    """Newline-terminated JSON-object lines (independent of the producer's reader) and the malformed count."""
    records, malformed = [], 0
    for index, raw in enumerate(path.read_bytes().split(b"\n")[:-1]):
        if limit is not None and index >= limit:
            break
        try:
            data = json.loads(raw)
        except ValueError:
            malformed += 1
            continue
        if isinstance(data, dict):
            records.append((index, data))
        else:
            malformed += 1
    return records, malformed


def _timed(d: dict[str, Any]) -> bool:
    try:
        return isinstance(d.get("uuid"), str) and d["uuid"] != "" and parse_iso8601_utc(d["timestamp"]) is not None
    except (KeyError, TypeError, TimestampError):
        return False


def _blocks(d: dict[str, Any]) -> list[Any]:
    content = (d.get("message") or {}).get("content")
    return content if isinstance(content, list) else []


class _Walk:
    """Independent per-stream expectations from the raw records (spans by promptId and resume boundaries)."""

    def __init__(self) -> None:
        self.n: Counter[str] = Counter()
        self.cur: str | None = None
        self.turn = 0
        self.seen: set[str] = set()
        self.uses: dict[str, int] = {}
        self.answered: set[str] = set()
        self.responses: dict[tuple[int, str], dict[str, Any]] = {}
        self.in_group = False

    def attachment(self, d: dict[str, Any]) -> None:
        name = str((d.get("attachment") or {}).get("hookName") or "")
        if name.startswith("SessionStart:resume") and not self.in_group:
            self.in_group, self.cur = True, None

    def results(self, blocks: list[Any]) -> None:
        for b in blocks:
            tid = b.get("tool_use_id") if isinstance(b, dict) and b.get("type") == "tool_result" else None
            if not isinstance(tid, str) or not tid or tid in self.answered:
                continue
            self.answered.add(tid)
            if self.cur is not None and self.uses.get(tid, self.turn) == self.turn:
                self.n["closes"] += 1

    def prompt(self, d: dict[str, Any]) -> None:
        content, pid = (d.get("message") or {}).get("content"), d.get("promptId")
        if d.get("sourceToolUseID") or d.get("turnCompanion") or not (isinstance(pid, str) and pid):
            return
        if not isinstance(content, (str, list)) or (pid in self.seen and pid != self.cur):
            return
        if pid != self.cur:
            self.cur, self.turn = pid, self.turn + 1
            self.seen.add(pid)

    def assistant(self, d: dict[str, Any]) -> None:
        message = d.get("message") or {}
        if not (isinstance(message.get("id"), str) and message["id"] and isinstance(message.get("content"), list)):
            return
        if self.cur is None:
            return
        usage = message.get("usage")
        self.responses[(self.turn, message["id"])] = usage if isinstance(usage, dict) else {}
        for b in _blocks(d):
            if (
                isinstance(b, dict)
                and b.get("type") == "tool_use"
                and isinstance(b.get("id"), str)
                and b["id"] not in self.uses
            ):
                self.uses[b["id"]] = self.turn
                self.n["opens"] += 1

    def finish(self) -> Counter[str]:
        self.n["turns"], self.n["model_calls"] = len(self.seen), len(self.responses)
        self.n["synthetic"] = sum(1 for t in self.uses if t not in self.answered)
        for col, key in USAGE:
            self.n[col] = sum(u.get(key, 0) for u in self.responses.values() if type(u.get(key, 0)) is int)
        return self.n


def walk(records: list[tuple[int, dict[str, Any]]]) -> Counter[str]:
    w = _Walk()
    for _, d in records:
        kind = d.get("type")
        if kind not in ("user", "assistant", "attachment") or not _timed(d):
            continue
        if kind == "attachment":
            w.attachment(d)
            continue
        w.in_group = False
        blocks = _blocks(d)
        if kind == "user" and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks):
            w.results(blocks)
        elif kind == "user":
            w.prompt(d)
        else:
            w.assistant(d)
    return w.finish()


def _stream_files(root: Path) -> dict[str, Path]:
    files = {root.stem: root}
    for path in sorted((root.parent / root.stem / "subagents").glob("agent-*.jsonl")):
        files[f"{root.stem}:{path.stem[len('agent-') :]}"] = path
    return files


class PrefixTree(FsTree):
    def __init__(self, root_file: Path, limit: int) -> None:
        super().__init__(root_file)
        self.limit = limit

    def read(self, key: str) -> bytes | None:
        data = super().read(key)
        if key != ROOT or data is None:
            return data
        return b"".join(line + b"\n" for line in data.split(b"\n")[: self.limit])


def _keyed(result: Any) -> dict[tuple[str, str], dict[str, Any]]:
    return {(t, r["external_ref"]): r for t, rows in result.batches for r in rows}


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> list[dict[str, Any]]:
    sources = _discover()
    if not sources:
        pytest.fail(
            "no real Claude Code transcripts found: set TURN_CAPTURE_REAL_TRANSCRIPTS or run on a machine that has them"
        )
    out = []
    for root in _snapshot(sources, tmp_path_factory.mktemp("real")):
        started = time.perf_counter()
        result = record_turn(FsTree(root), None, project_ref=PROJECT_REF, session_final=True)
        out.append({"root": root, "sid": root.stem, "result": result, "secs": time.perf_counter() - started})
    return out


def _live(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in runs if r["result"].next_cursor is not None]


def test_output_reconciles_with_an_independent_raw_walk(runs: list[dict[str, Any]]) -> None:
    live = _live(runs)
    assert live, "every real transcript deferred (no parseable timestamp)"
    exercised = 0
    for run in live:
        sid, result, tag = run["sid"], run["result"], _hash(run["sid"])
        malformed = 0
        for stream, path in _stream_files(run["root"]).items():
            records, bad = raw_lines(path)
            malformed += bad
            want = walk(records)
            obs = [r for r in result.observations if r["session_ref"] == stream]
            opens = [r for r in obs if r["observation_type"] == "tool_call" and r["event_kind"] == "open"]
            closes = [r for r in obs if r["observation_type"] == "tool_call" and r["event_kind"] == "close"]
            calls = [r for r in obs if r["observation_type"] == "model_call"]
            got = {
                "turns": sum(1 for r in obs if r["observation_type"] == "turn" and r["event_kind"] == "open"),
                "model_calls": len(calls), "opens": len(opens),
                **{col: sum(r.get(col, 0) for r in calls) for col, _ in USAGE},
            }  # fmt: skip
            for key, value in got.items():
                assert value == want[key], f"{tag} stream {_hash(stream)}: {key} produced {value} != raw {want[key]}"
            assert len({r["entity_ref"] for r in closes}) == len(closes), f"{tag}: a tool_call closed twice"
            assert len(closes) == want["closes"] + want["synthetic"], (
                f"{tag} stream {_hash(stream)}: closes != in-span + synthetic"
            )
            exercised += bool(opens) and ":" in "".join(_stream_files(run["root"]))
        assert result.diagnostics.get("malformed_lines", 0) == malformed, f"{tag}: malformed lines are counted and consumed"
        metas = list((run["root"].parent / sid / "subagents").glob("agent-*.meta.json"))
        wanted = {json.loads(m.read_text(encoding="utf-8")).get("toolUseId") for m in metas}
        opened = {r["entity_ref"] for r in result.agents if r["event_kind"] == "open"}
        assert opened <= wanted, f"{tag}: an agents open without a meta.json toolUseId"
    assert exercised, "no root transcript with a tool call and a sub-agent was exercised"


def test_rows_are_unique_valid_and_scrubbed(runs: list[dict[str, Any]]) -> None:
    generic = Counter()
    for run in _live(runs):
        result, tag = run["result"], _hash(run["sid"])
        starts = {r["session_started_at"] for _, rows in result.batches for r in rows}
        assert len(starts) == 1, f"{tag}: {len(starts)} session_started_at values in one tree"
        seen = set()
        for table, rows in result.batches:
            for r in rows:
                key = (table, r["external_ref"])
                assert key not in seen, f"{tag}: duplicate (table, external_ref) in {table}"
                seen.add(key)
                for field in (
                    "external_ref",
                    "entity_ref",
                    "session_ref",
                    "parent_observation_ref",
                    "observation_ref",
                    "parent_session_ref",
                ):
                    if r.get(field) is not None:
                        canonical_ref(r[field])
                for value in r.values():
                    if isinstance(value, str):
                        assert scrub_text(value).counts == {}, (
                            f"{tag}: a scrub pattern still matches a stored value in {table}"
                        )
                        generic.update(["long_token"] * len([w for w in value.split() if len(w) >= 40 and w.isalnum()]))
        for r in result.transcripts:
            assert r["content_bytes"] == len(r["content"].encode()), f"{tag}: content_bytes disagrees"
    print(f"\nconformance: generic long alphanumeric tokens in stored text (count only): {sum(generic.values())}")


def test_sidecars_resolve_untruncated(runs: list[dict[str, Any]]) -> None:
    checked = 0
    for run in _live(runs):
        tag = _hash(run["sid"])
        rows = {r["external_ref"]: r for r in run["result"].transcripts}
        for path in _stream_files(run["root"]).values():
            for _, d in raw_lines(path)[0]:
                info = d.get("toolUseResult")
                name = (
                    os.path.basename(str(info.get("persistedOutputPath") or "").replace("\\", "/"))
                    if isinstance(info, dict)
                    else ""
                )
                if not name or not (run["root"].parent / run["sid"] / "tool-results" / name).is_file():
                    continue
                for k, block in enumerate(_blocks(d)):
                    row = rows.get(f"{d.get('uuid')}#{k}")
                    if isinstance(block, dict) and block.get("type") == "tool_result" and row is not None:
                        checked += 1
                        assert row["content_truncated"] is False, f"{tag}: a resolvable sidecar was stored truncated"
    print(f"\nconformance: {checked} resolvable sidecar tool_results stored untruncated")


def test_cross_tree_uniqueness(runs: list[dict[str, Any]]) -> None:
    trees = _live(runs)
    owner: dict[tuple[str, str], str] = {}
    for run in trees:
        for key in _keyed(run["result"]):
            other = owner.setdefault(key, run["sid"])
            assert other == run["sid"], (
                f"STOP: (table, external_ref) recurs across root trees {_hash(other)} and {_hash(run['sid'])} -- "
                "file a contract-risk rec against rec-4149's scope and return to /plan"
            )
    if len(trees) < 2:
        print(f"\nconformance: cross-tree uniqueness unverified ({len(trees)} root trees)")


def _cut_points(root: Path) -> list[int]:
    records, _ = raw_lines(root)
    total = root.read_bytes().count(b"\n")
    prompts = [i + 1 for i, d in records if d.get("type") == "user" and d.get("promptId") and not d.get("sourceToolUseID")]
    step = 50 if total <= MAX_FULL_CUT_LINES else max(50, total // 60)
    return sorted({*prompts, *range(step, total, step), total})


def test_incremental_equals_full_at_every_prompt_and_line_cut(runs: list[dict[str, Any]]) -> None:
    for run in _live(runs):
        tag, full = _hash(run["sid"]), _keyed(run["result"])
        cursor, seen, cuts = None, {}, _cut_points(run["root"])
        for index, limit in enumerate(cuts):
            step = record_turn(
                PrefixTree(run["root"], limit), cursor, project_ref=PROJECT_REF, session_final=index == len(cuts) - 1
            )
            cursor = step.next_cursor if step.next_cursor is not None else cursor
            for key, row in _keyed(step).items():
                assert key not in seen, f"{tag}: {key[0]} row emitted twice by incremental capture (cut {limit})"
                assert row == full[key], f"{tag}: {key[0]} row differs between incremental (cut {limit}) and full parse"
                seen[key] = row
        assert set(seen) == set(full), f"{tag}: incremental emitted {len(seen)} rows, full parse {len(full)}"
        print(f"\nconformance: {tag}: {len(cuts)} incremental cuts (every prompt plus a line stride)")


def test_finalized_prefix_at_true_session_ends_is_a_row_subset(runs: list[dict[str, Any]]) -> None:
    for run in _live(runs):
        tag, full = _hash(run["sid"]), _keyed(run["result"])
        records, _ = raw_lines(run["root"])
        ends, in_group = [], False
        for index, d in records:
            is_resume = d.get("type") == "attachment" and str((d.get("attachment") or {}).get("hookName") or "").startswith(
                "SessionStart:resume"
            )
            if is_resume and not in_group and index > 0:
                ends.append(index)
            in_group = is_resume if d.get("type") == "attachment" else False
        for limit in ends:
            prefix = _keyed(record_turn(PrefixTree(run["root"], limit), None, project_ref=PROJECT_REF, session_final=True))
            for key, row in prefix.items():
                assert key in full and full[key] == row, (
                    f"{tag}: a row of the finalized prefix at a resume boundary is absent or changed in the full parse"
                )


def test_loads_into_local_ducklake_with_every_fk_resolving(
    runs: list[dict[str, Any]], tmp_path: Path, _allow_network_for_integration: None
) -> None:
    from src.telemetry.append import append_events  # noqa: PLC0415
    from tests.fixtures.turn_capture_corpus import PROJECT, TENANT  # noqa: PLC0415

    live = _live(runs)
    specs = load_specs()
    con = open_local_lake(tmp_path)
    create_tables(con, specs)
    skipped = 0
    for table, position in (
        ("telemetry_observations", 0),
        ("telemetry_transcripts", 1),
        ("telemetry_agents", 2),
        ("telemetry_sessions", 3),
    ):
        rows = []
        for run in live:
            for r in run["result"].batches[position][1]:
                if table == "telemetry_transcripts" and len(r["content"].encode()) > 65536:
                    skipped += 1
                    continue
                rows.append(r)
        for start in range(0, len(rows), 500):
            append_events(con, specs[table], rows[start : start + 500], tenant_id=TENANT, project_id=PROJECT, catalog="lake")
    checks = (
        ("telemetry_observations", "session_id", "telemetry_sessions", "session_id"),
        ("telemetry_transcripts", "session_id", "telemetry_sessions", "session_id"),
        ("telemetry_transcripts", "observation_id", "telemetry_observations", "observation_id"),
        ("telemetry_agents", "session_id", "telemetry_sessions", "session_id"),
        ("telemetry_observations", "parent_observation_id", "telemetry_observations", "observation_id"),
        ("telemetry_sessions", "parent_session_id", "telemetry_sessions", "session_id"),
    )
    for child, column, parent, key in checks:
        sql = (
            f"SELECT count(*) FROM lake.{child} c WHERE c.{column} IS NOT NULL "
            f"AND NOT EXISTS (SELECT 1 FROM lake.{parent} p WHERE p.{key} = c.{column})"
        )
        assert con.execute(sql).fetchone()[0] == 0, f"dangling {child}.{column}"
    print(f"\nconformance: loaded {len(live)} root trees; {skipped} transcript rows over 65,536 bytes excluded")
    con.close()


def test_drift_dashboard(runs: list[dict[str, Any]]) -> None:
    unknown: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    stops: Counter[str] = Counter()
    workflows: Counter[str] = Counter()
    for run in runs:
        result = run["result"]
        unknown.update({k: v for k, v in result.diagnostics.items() if k.startswith("unknown_")})
        outcomes.update(
            r["outcome"] for r in result.observations if r["observation_type"] == "tool_call" and r["event_kind"] == "close"
        )
        workflows.update(r["workflow"] for r in result.sessions if r["event_kind"] == "open")
        for _, d in raw_lines(run["root"])[0]:
            reason = (d.get("message") or {}).get("stop_reason") if d.get("type") == "assistant" else None
            stops[str(reason)] += d.get("type") == "assistant"
        print(f"\nconformance: tree {_hash(run['sid'])}: parsed in {run['secs']:.2f}s, diagnostics {dict(result.diagnostics)}")
    print(
        f"\nconformance dashboard: unknown types {dict(unknown)}; outcomes {dict(outcomes)}; "
        f"stop_reasons {dict(stops)}; workflows {dict(workflows)}"
    )
    assert runs
