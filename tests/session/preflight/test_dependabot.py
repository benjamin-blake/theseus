"""Tests for scripts/preflight/dependabot.py -- the stranded-dependabot-PR preflight signal.

Imported directly from scripts.preflight.dependabot (not via the scripts.session.preflight
facade), the convention tests/session/preflight/test_alerts.py established: the module
deliberately gets no facade re-export, so tests/test_session_preflight_decomposition.py's frozen
symbol list stays untouched.

Coverage: ecosystem parsing, UTC age arithmetic, the stranded threshold boundary at 14 days,
DIRTY/BLOCKED as an age-independent stranded verdict, per-ecosystem quota saturation at 5, every
gh-degradation path returning None (never a false-clean dict), the summary.py presentation half,
and the /orient surfacing contract (render-only, no shell-out).
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.preflight import dependabot, summary

ROOT = Path(__file__).resolve().parents[3]

_NOW = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)


def _created(days_ago: float) -> str:
    """createdAt relative to the real clock, so check_stranded_prs' own datetime.now() is the
    reference instant. Second-granularity truncation only ever ages a PR by well under the 0.1d
    rounding step, so the 14-day boundary cases below stay deterministic without mocking datetime.
    """
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pr(number: int, *, head_ref: str = "dependabot/pip/foo-1.2.3", days_ago: float = 1.0, merge_state: str = "CLEAN") -> dict:
    return {
        "number": number,
        "title": f"bump foo to 1.2.{number}",
        "headRefName": head_ref,
        "mergeStateStatus": merge_state,
        "createdAt": _created(days_ago),
    }


def _gh_result(payload: object, *, returncode: int = 0) -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stdout = payload if isinstance(payload, str) else json.dumps(payload)
    return result


def _run_with(payload: object, *, returncode: int = 0) -> dict | None:
    """Invoke check_stranded_prs() against a canned gh response."""
    with patch("scripts.preflight.dependabot.subprocess.run", return_value=_gh_result(payload, returncode=returncode)):
        return dependabot.check_stranded_prs()


class TestEcosystem:
    """_ecosystem() reads the ecosystem slug out of the dependabot head ref."""

    @pytest.mark.parametrize(
        ("head_ref", "expected"),
        [
            ("dependabot/pip/sympy-1.14.0", "pip"),
            ("dependabot/github_actions/actions/download-artifact-8", "github_actions"),
            ("dependabot/pip/minor-and-patch-abc123", "pip"),
        ],
    )
    def test_known_ecosystems(self, head_ref: str, expected: str) -> None:
        assert dependabot._ecosystem(head_ref) == expected

    @pytest.mark.parametrize("head_ref", ["", "claude/some-branch", "dependabot/pip", "dependabot//foo", "main"])
    def test_unrecognised_refs_fall_back_to_unknown(self, head_ref: str) -> None:
        assert dependabot._ecosystem(head_ref) == "unknown"


class TestAgeDays:
    """_age_days() is UTC arithmetic over an ISO-8601 createdAt, rounded once."""

    def test_zulu_suffix_parsed_as_utc(self) -> None:
        assert dependabot._age_days("2026-08-12T12:00:00Z", _NOW) == 14.0

    def test_explicit_offset_parsed(self) -> None:
        assert dependabot._age_days("2026-08-12T13:00:00+01:00", _NOW) == 14.0

    def test_naive_timestamp_treated_as_utc(self) -> None:
        assert dependabot._age_days("2026-08-12T12:00:00", _NOW) == 14.0

    def test_fractional_age_rounded_to_one_decimal(self) -> None:
        assert dependabot._age_days("2026-08-25T00:00:00Z", _NOW) == 1.5

    @pytest.mark.parametrize("created_at", ["", "not-a-timestamp", "2026-13-45T99:99:99Z"])
    def test_unparseable_returns_none(self, created_at: str) -> None:
        assert dependabot._age_days(created_at, _NOW) is None


class TestStrandedClassification:
    """A PR is stranded on age >= 14d OR on a terminal merge state, never on a green young PR."""

    def test_exactly_fourteen_days_is_stranded(self) -> None:
        report = _run_with([_pr(1, days_ago=14.0)])
        assert report is not None
        assert [s["number"] for s in report["stranded"]] == [1]
        assert report["stranded"][0]["age_days"] == 14.0

    def test_just_under_fourteen_days_is_not_stranded(self) -> None:
        report = _run_with([_pr(1, days_ago=13.9)])
        assert report is not None
        assert report["stranded"] == []
        assert report["open_total"] == 1

    def test_well_past_the_threshold_is_stranded(self) -> None:
        report = _run_with([_pr(1, days_ago=51.0)])
        assert report is not None
        assert [s["number"] for s in report["stranded"]] == [1]

    @pytest.mark.parametrize("merge_state", ["DIRTY", "BLOCKED"])
    def test_terminal_merge_state_is_stranded_regardless_of_age(self, merge_state: str) -> None:
        report = _run_with([_pr(7, days_ago=0.1, merge_state=merge_state)])
        assert report is not None
        assert [s["number"] for s in report["stranded"]] == [7]
        assert report["stranded"][0]["merge_state"] == merge_state

    @pytest.mark.parametrize("merge_state", ["CLEAN", "BEHIND", "UNSTABLE", ""])
    def test_non_terminal_merge_state_alone_is_not_stranded(self, merge_state: str) -> None:
        report = _run_with([_pr(7, days_ago=0.1, merge_state=merge_state)])
        assert report is not None
        assert report["stranded"] == []

    def test_unparseable_created_at_is_not_stranded_without_a_terminal_state(self) -> None:
        pr = _pr(3)
        pr["createdAt"] = "garbage"
        report = _run_with([pr])
        assert report is not None
        assert report["stranded"] == []

    def test_unparseable_created_at_still_stranded_when_dirty(self) -> None:
        pr = _pr(3, merge_state="DIRTY")
        pr["createdAt"] = "garbage"
        report = _run_with([pr])
        assert report is not None
        assert [s["number"] for s in report["stranded"]] == [3]
        assert report["stranded"][0]["age_days"] is None

    def test_stranded_entry_carries_the_full_payload_shape(self) -> None:
        report = _run_with([_pr(493, head_ref="dependabot/pip/sympy-1.14.0", days_ago=51.0)])
        assert report is not None
        entry = report["stranded"][0]
        assert entry["number"] == 493
        assert entry["ecosystem"] == "pip"
        assert entry["title"]
        assert entry["age_days"] == 51.0
        assert entry["merge_state"] == "CLEAN"


class TestEcosystemTallyAndQuota:
    """by_ecosystem counts every open PR; quota_saturated fires at the dependabot.yml limit of 5."""

    def test_counts_split_by_ecosystem(self) -> None:
        prs = [
            _pr(1, head_ref="dependabot/pip/a-1"),
            _pr(2, head_ref="dependabot/pip/b-1"),
            _pr(3, head_ref="dependabot/github_actions/actions/checkout-7"),
        ]
        report = _run_with(prs)
        assert report is not None
        assert report["by_ecosystem"] == {"pip": 2, "github_actions": 1}
        assert report["open_total"] == 3

    def test_saturated_at_exactly_five(self) -> None:
        report = _run_with([_pr(i, head_ref=f"dependabot/pip/pkg{i}-1") for i in range(5)])
        assert report is not None
        assert report["quota_saturated"] == ["pip"]

    def test_not_saturated_at_four(self) -> None:
        report = _run_with([_pr(i, head_ref=f"dependabot/pip/pkg{i}-1") for i in range(4)])
        assert report is not None
        assert report["quota_saturated"] == []

    def test_both_ecosystems_can_saturate_and_are_sorted(self) -> None:
        prs = [_pr(i, head_ref=f"dependabot/pip/pkg{i}-1") for i in range(5)]
        prs += [_pr(100 + i, head_ref=f"dependabot/github_actions/act{i}-1") for i in range(5)]
        report = _run_with(prs)
        assert report is not None
        assert report["quota_saturated"] == ["github_actions", "pip"]

    def test_no_open_prs_returns_a_clean_report_not_none(self) -> None:
        report = _run_with([])
        assert report == {"open_total": 0, "by_ecosystem": {}, "stranded": [], "quota_saturated": []}


class TestGhDegradation:
    """Every unusable gh outcome returns None so a consumer renders UNKNOWN, not a clean report."""

    def test_gh_missing_returns_none(self) -> None:
        with patch("scripts.preflight.dependabot.subprocess.run", side_effect=OSError("gh not found")):
            assert dependabot.check_stranded_prs() is None

    def test_timeout_returns_none(self) -> None:
        with patch(
            "scripts.preflight.dependabot.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=15),
        ):
            assert dependabot.check_stranded_prs() is None

    def test_nonzero_returncode_returns_none(self) -> None:
        assert _run_with([_pr(1)], returncode=1) is None

    def test_empty_stdout_returns_none(self) -> None:
        assert _run_with("   ") is None

    def test_garbage_json_returns_none(self) -> None:
        assert _run_with("{not json at all") is None

    def test_json_that_is_not_a_list_returns_none(self) -> None:
        assert _run_with({"prs": []}) is None

    def test_non_dict_rows_are_skipped_not_fatal(self) -> None:
        report = _run_with(["a string row", _pr(1, days_ago=20.0)])
        assert report is not None
        assert report["open_total"] == 1
        assert [s["number"] for s in report["stranded"]] == [1]


class TestGhInvocationContract:
    """The shell-out mirrors ci_rca_signals' idiom: bounded, decoded, and dependabot-scoped."""

    def test_gh_called_with_the_expected_argv_and_guards(self) -> None:
        with patch("scripts.preflight.dependabot.subprocess.run", return_value=_gh_result([])) as mock_run:
            dependabot.check_stranded_prs()

        argv, kwargs = mock_run.call_args[0][0], mock_run.call_args[1]
        assert argv[:3] == ["gh", "pr", "list"]
        assert "app/dependabot" in argv
        assert "open" in argv
        assert "number,title,headRefName,mergeStateStatus,createdAt" in argv
        assert kwargs["timeout"] == 15
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "replace"

    def test_signal_needs_no_aws_credentials(self) -> None:
        """check_stranded_prs takes no creds_status argument -- gh auth is not AWS auth."""
        import inspect  # noqa: PLC0415

        assert list(inspect.signature(dependabot.check_stranded_prs).parameters) == []


class TestPrintDependabotStrandedAlert:
    """summary.print_dependabot_stranded_alert is presentation only and silent when there is
    nothing actionable."""

    def test_none_signal_prints_nothing(self, capsys: pytest.CaptureFixture) -> None:
        summary.print_dependabot_stranded_alert(None)
        assert capsys.readouterr().err == ""

    def test_clean_backlog_prints_nothing(self, capsys: pytest.CaptureFixture) -> None:
        summary.print_dependabot_stranded_alert(
            {"open_total": 2, "by_ecosystem": {"pip": 2}, "stranded": [], "quota_saturated": []}
        )
        assert capsys.readouterr().err == ""

    def test_stranded_prs_reported_with_counts(self, capsys: pytest.CaptureFixture) -> None:
        summary.print_dependabot_stranded_alert(
            {
                "open_total": 8,
                "by_ecosystem": {"pip": 5, "github_actions": 3},
                "stranded": [{"number": 493}, {"number": 774}],
                "quota_saturated": [],
            }
        )
        err = capsys.readouterr().err
        assert "Dependabot backlog alert" in err
        assert "2 of 8" in err

    def test_quota_saturation_names_the_ecosystems(self, capsys: pytest.CaptureFixture) -> None:
        summary.print_dependabot_stranded_alert(
            {"open_total": 5, "by_ecosystem": {"pip": 5}, "stranded": [], "quota_saturated": ["pip"]}
        )
        err = capsys.readouterr().err
        assert "Quota saturated: pip" in err

    def test_partial_signal_shape_does_not_raise(self, capsys: pytest.CaptureFixture) -> None:
        summary.print_dependabot_stranded_alert({"marker": "shape-not-recognised"})
        assert capsys.readouterr().err == ""


class TestOrientSurfacingContract:
    """The signal is surfaced through the /orient docs as a cache RENDER, never a recomputation."""

    _SKILL = ROOT / ".claude" / "skills" / "orient" / "SKILL.md"
    _COMMAND = ROOT / ".claude" / "commands" / "orient.md"

    def test_best_practices_table_carries_a_dependabot_row(self) -> None:
        text = self._SKILL.read_text(encoding="utf-8")
        section = text.split("### 4. Best-Practices Health Check", 1)
        assert len(section) == 2, "Best-Practices Health Check section missing from the orient skill"
        body = section[1].split("### 5.", 1)[0]
        rows = [line for line in body.splitlines() if line.startswith("|") and "dependabot_stranded_prs" in line]
        assert rows, "no Best-Practices row renders dependabot_stranded_prs"
        row = rows[0]
        for verdict in ("PASS", "WATCH", "GAP"):
            assert verdict in row, f"{verdict} threshold missing from the dependency-backlog row"

    def test_command_load_inputs_lists_the_cache_key(self) -> None:
        text = self._COMMAND.read_text(encoding="utf-8")
        load_inputs = text.split("## Step 2: Load Inputs", 1)
        assert len(load_inputs) == 2, "Load Inputs step missing from the orient command"
        assert "dependabot_stranded_prs" in load_inputs[1].split("## Step 3", 1)[0]

    def test_orient_docs_never_shell_out_for_the_signal(self) -> None:
        for path in (self._SKILL, self._COMMAND):
            text = path.read_text(encoding="utf-8")
            assert "gh pr list" not in text, f"{path.name} must render the cached signal, not recompute it"
