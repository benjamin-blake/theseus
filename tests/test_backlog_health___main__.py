"""Mirror test for scripts/backlog_health/__main__.py (PLAN-backlog-health-detection)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.backlog_health import __main__ as cli
from scripts.backlog_health import census as census_mod
from scripts.backlog_health import escalate as escalate_mod
from scripts.backlog_health import probe as probe_mod


class TestBuildParser:
    def test_three_subcommands_wired(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["census"])
        assert args.command == "census"
        assert args.handler is cli.cmd_census

        args = parser.parse_args(["probe"])
        assert args.handler is cli.cmd_probe

        args = parser.parse_args(["escalate"])
        assert args.handler is cli.cmd_escalate

    def test_dry_run_flag_defaults_false(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["census"])
        assert args.dry_run is False

    def test_dry_run_flag_settable(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["escalate", "--dry-run"])
        assert args.dry_run is True

    def test_requires_a_subcommand(self) -> None:
        parser = cli.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


class TestCmdCensus:
    def test_writes_artifact_and_writes_nothing_upstream(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_result = {"counts": {"probeable": 1}, "buckets": {}, "probe_payload": [], "recent_commits": [], "open_rows": []}
        monkeypatch.setattr(census_mod, "run_census", lambda **kwargs: fake_result)
        parser = cli.build_parser()
        args = parser.parse_args(["--artifact-dir", str(tmp_path), "census"])
        exit_code = cli.cmd_census(args)
        assert exit_code == 0
        written = json.loads((tmp_path / cli._CENSUS_ARTIFACT).read_text())
        assert written == fake_result

    def test_dry_run_still_writes_local_handoff_artifact(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_result: dict[str, object] = {
            "counts": {},
            "buckets": {},
            "probe_payload": [],
            "recent_commits": [],
            "open_rows": [],
        }
        monkeypatch.setattr(census_mod, "run_census", lambda **kwargs: fake_result)
        parser = cli.build_parser()
        args = parser.parse_args(["--artifact-dir", str(tmp_path), "census", "--dry-run"])
        cli.cmd_census(args)
        assert (tmp_path / cli._CENSUS_ARTIFACT).is_file()


class TestCmdProbe:
    def test_reads_census_writes_probe_artifact(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        census_result = {"probe_payload": [{"id": "rec-1", "acceptance": "echo hi", "acceptance_sha256": "h"}]}
        (tmp_path / cli._CENSUS_ARTIFACT).write_text(json.dumps(census_result))
        monkeypatch.setattr(cli, "_current_main_sha", lambda repo_root: "deadbeef")
        fake_probe_result = {"main_sha": "deadbeef", "isolation_available": True, "verdicts": {"rec-1": probe_mod.PASS}}
        monkeypatch.setattr(probe_mod, "run_all", lambda payload, **kwargs: fake_probe_result)
        parser = cli.build_parser()
        args = parser.parse_args(["--artifact-dir", str(tmp_path), "probe"])
        exit_code = cli.cmd_probe(args)
        assert exit_code == 0
        written = json.loads((tmp_path / cli._PROBE_ARTIFACT).read_text())
        assert written == fake_probe_result

    def test_isolation_unavailable_with_pending_work_is_nonzero_exit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        census_result = {"probe_payload": [{"id": "rec-1", "acceptance": "echo hi", "acceptance_sha256": "h"}]}
        (tmp_path / cli._CENSUS_ARTIFACT).write_text(json.dumps(census_result))
        monkeypatch.setattr(cli, "_current_main_sha", lambda repo_root: "deadbeef")
        fake_probe_result = {
            "main_sha": "deadbeef",
            "isolation_available": False,
            "verdicts": {"rec-1": probe_mod.ISOLATION_UNAVAILABLE},
        }
        monkeypatch.setattr(probe_mod, "run_all", lambda payload, **kwargs: fake_probe_result)
        parser = cli.build_parser()
        args = parser.parse_args(["--artifact-dir", str(tmp_path), "probe"])
        assert cli.cmd_probe(args) == 1

    def test_missing_census_artifact_raises(self, tmp_path: Path) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["--artifact-dir", str(tmp_path), "probe"])
        with pytest.raises(RuntimeError, match="expected artifact not found"):
            cli.cmd_probe(args)


class TestCmdEscalate:
    def test_wires_rejoin_classify_and_episodes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        census_result = {
            "probe_payload": [{"id": "rec-1", "acceptance": "x", "acceptance_sha256": "h"}],
            "recent_commits": [],
            "open_rows": [{"id": "rec-1", "status": "open"}],
        }
        (tmp_path / cli._CENSUS_ARTIFACT).write_text(json.dumps(census_result))
        (tmp_path / cli._PROBE_ARTIFACT).write_text(json.dumps({"main_sha": "x", "isolation_available": True, "verdicts": {}}))
        monkeypatch.setattr(census_mod, "read_open_recs", lambda **kwargs: [{"id": "rec-1", "status": "open"}])
        fake_results = {source: {"action": "none", "rec_id": None, "count": 0} for source in escalate_mod.ALL_SOURCES}
        run_all_episodes_mock = MagicMock(return_value=fake_results)
        monkeypatch.setattr(escalate_mod, "run_all_episodes", run_all_episodes_mock)
        parser = cli.build_parser()
        args = parser.parse_args(["--artifact-dir", str(tmp_path), "escalate", "--dry-run"])
        exit_code = cli.cmd_escalate(args)
        assert exit_code == 0
        run_all_episodes_mock.assert_called_once()
        assert run_all_episodes_mock.call_args.kwargs["dry_run"] is True

    def test_missing_probe_artifact_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / cli._CENSUS_ARTIFACT).write_text(json.dumps({"probe_payload": [], "open_rows": []}))
        parser = cli.build_parser()
        args = parser.parse_args(["--artifact-dir", str(tmp_path), "escalate"])
        with pytest.raises(RuntimeError, match="expected artifact not found"):
            cli.cmd_escalate(args)


class TestMainLoudFailure:
    def test_runtime_error_is_caught_and_reported_nonzero(self, tmp_path: Path) -> None:
        exit_code = cli.main(["--artifact-dir", str(tmp_path), "probe"])
        assert exit_code == 1

    def test_default_artifact_dir_is_used_when_unset(self) -> None:
        default_dir = cli._default_artifact_dir()
        assert default_dir.name == "backlog_health"

    def test_main_falls_back_to_default_artifact_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(cli, "_default_artifact_dir", lambda: tmp_path)
        monkeypatch.setattr(
            census_mod,
            "run_census",
            lambda **kwargs: {"counts": {}, "buckets": {}, "probe_payload": [], "recent_commits": [], "open_rows": []},
        )
        exit_code = cli.main(["census"])
        assert exit_code == 0
        assert (tmp_path / cli._CENSUS_ARTIFACT).is_file()


class TestCurrentMainSha:
    def test_resolves_head_sha_in_a_real_git_repo(self) -> None:
        sha = cli._current_main_sha(Path(__file__).resolve().parent.parent)
        assert len(sha) == 40
        assert sha.strip() == sha

    def test_raises_on_a_non_git_directory(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="git rev-parse HEAD failed"):
            cli._current_main_sha(tmp_path)
