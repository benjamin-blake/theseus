from __future__ import annotations

import contextlib
import copy
import json
import os
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.checks.deps import fast_tier_harness as harness

ROOT = Path(__file__).resolve().parents[3]
CORPUS_PATH = ROOT / "scripts" / "checks" / "deps" / "fast_tier_corpus.yaml"


def _raw_corpus() -> dict:
    return yaml.safe_load(CORPUS_PATH.read_text(encoding="utf-8"))


def _write_corpus(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "corpus.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _git(repo: Path, *args: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, input=input_bytes, capture_output=True, check=True)


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.decode().strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    return repo


class TestCorpus:
    def test_tracked_manifest_loads_with_both_required_strata(self) -> None:
        corpus = harness.load_corpus(CORPUS_PATH)
        assert corpus.base_sha == "35609091fd8482d3116e4b360c6ec2bc9ab25b90"  # pragma: allowlist secret -- public git SHA
        assert len(corpus.cases) == 16  # count-coupling-ok: section 8.4 fixes the corpus at 16 PRs
        assert len(corpus.predictor_pairs) == 8  # count-coupling-ok: section 8.4 fixes calibration at 8 pairs
        assert corpus.cases[0].case_id == "pr-1128"
        assert corpus.cases[-1].case_id == "pr-1094"

    @pytest.mark.parametrize(
        ("mutation", "message"),
        [
            (lambda row: row.update(schema_version=2), "schema_version"),
            (lambda row: row.update(base_sha="short"), "base_sha"),
            (lambda row: row["implementation"].update(required_count=15), "required 16"),
            (lambda row: row["implementation"]["cases"].pop(), "required 16"),
            (lambda row: row["implementation"]["cases"][0].update(id=""), "invalid or duplicate id"),
            (
                lambda row: row["implementation"]["cases"][1].update(id=row["implementation"]["cases"][0]["id"]),
                "invalid or duplicate id",
            ),
            (lambda row: row["implementation"]["cases"][0].update(pr=-1), "invalid or duplicate PR"),
            (
                lambda row: row["implementation"]["cases"][1].update(pr=row["implementation"]["cases"][0]["pr"]),
                "invalid or duplicate PR",
            ),
            (lambda row: row["implementation"]["cases"][0].update(diff_sha256="bad"), "diff_sha256"),
            (
                lambda row: row["implementation"]["cases"][0].update(qualifying_python_paths=[]),
                "qualifying Python path",
            ),
            (
                lambda row: row["implementation"]["cases"][0].update(qualifying_python_paths=["docs/not-python.md"]),
                "qualifying Python path",
            ),
            (
                lambda row: row["implementation"]["cases"][0].update(qualifying_python_paths=["tests/x.py", "tests/x.py"]),
                "repeats a qualifying Python path",
            ),
            (
                lambda row: row["implementation"]["cases"][0].update(merge_parent_sha="bad"),
                "merge_parent_sha",
            ),
            (lambda row: row["predictor_calibration"].update(required_count=7), "required 8"),
            (lambda row: row["predictor_calibration"]["pairs"].pop(), "required 8"),
            (
                lambda row: row["predictor_calibration"]["pairs"][0]["implementation"].update(pr=0),
                "invalid or duplicate implementation PR",
            ),
            (
                lambda row: row["predictor_calibration"]["pairs"][1]["implementation"].update(
                    pr=row["predictor_calibration"]["pairs"][0]["implementation"]["pr"]
                ),
                "invalid or duplicate implementation PR",
            ),
            (
                lambda row: row["predictor_calibration"]["pairs"][0]["observed"].pop("test_s"),
                "lacks observed",
            ),
            (
                lambda row: row["predictor_calibration"]["pairs"][0]["plan"].pop("reported"),
                "predictor calibration corpus is incomplete",
            ),
        ],
    )
    def test_invalid_manifest_fails_loudly(self, tmp_path: Path, mutation, message: str) -> None:
        payload = copy.deepcopy(_raw_corpus())
        mutation(payload)
        with pytest.raises(harness.HarnessError, match=message):
            harness.load_corpus(_write_corpus(tmp_path, payload))

    def test_unreadable_and_non_mapping_manifest_fail_loudly(self, tmp_path: Path) -> None:
        with pytest.raises(harness.HarnessError, match="cannot load corpus"):
            harness.load_corpus(tmp_path / "missing.yaml")
        path = tmp_path / "list.yaml"
        path.write_text("- value\n", encoding="utf-8")
        with pytest.raises(harness.HarnessError, match="corpus must be a mapping"):
            harness.load_corpus(path)
        payload = _raw_corpus()
        payload["implementation"]["cases"] = "not-a-list"
        with pytest.raises(harness.HarnessError, match="implementation.cases must be a list"):
            harness.load_corpus(_write_corpus(tmp_path, payload))

    def test_historical_diff_matches_every_pinned_case(self) -> None:
        corpus = harness.load_corpus(CORPUS_PATH)
        for case in corpus.cases:
            entries = harness.historical_diff(ROOT, case)
            assert entries
            assert [path for _, path in entries if harness._QUALIFYING_PATH_RE.fullmatch(path)] == list(
                case.qualifying_python_paths
            )

    def test_historical_diff_rejects_digest_path_and_status_drift(self) -> None:
        case = harness.load_corpus(CORPUS_PATH).cases[0]
        changed = harness.CorpusCase(
            case.case_id,
            case.pr,
            case.merge_parent_sha,
            case.merge_commit_sha,
            "0" * 64,
            case.qualifying_python_paths,
        )
        with pytest.raises(harness.HarnessError, match="digest drifted"):
            harness.historical_diff(ROOT, changed)
        text = "X\ttests/x.py\n"
        changed = harness.CorpusCase("x", 1, "a" * 40, "b" * 40, harness.hashlib.sha256(text.encode()).hexdigest(), ())
        with patch.object(harness, "_git_text", return_value=text):
            with pytest.raises(harness.HarnessError, match="unsupported historical diff row"):
                harness.historical_diff(ROOT, changed)
        text = "M\ttests/x.py\n"
        changed = harness.CorpusCase("x", 1, "a" * 40, "b" * 40, harness.hashlib.sha256(text.encode()).hexdigest(), ())
        with patch.object(harness, "_git_text", return_value=text):
            with pytest.raises(harness.HarnessError, match="qualifying Python paths drifted"):
                harness.historical_diff(ROOT, changed)


class TestGitAndWorktree:
    def test_git_helpers_fail_loudly(self, tmp_path: Path) -> None:
        with pytest.raises(harness.HarnessError, match="git rev-parse HEAD failed"):
            harness._git_text(tmp_path, ["rev-parse", "HEAD"])
        with pytest.raises(harness.HarnessError, match="git show HEAD:x failed"):
            harness._git_bytes(tmp_path, ["show", "HEAD:x"])

    def test_safe_path_rejects_escape(self, tmp_path: Path) -> None:
        assert harness._safe_path(tmp_path, "tests/x.py") == tmp_path / "tests/x.py"
        for value in ("/tmp/x", "../x"):
            with pytest.raises(harness.HarnessError, match="unsafe repository path"):
                harness._safe_path(tmp_path, value)

    def test_apply_historical_diff_and_overlay_regular_delta(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        (repo / "tests").mkdir()
        (repo / "tests" / "old.py").write_text("old\n", encoding="utf-8")
        (repo / "delete.txt").write_text("delete\n", encoding="utf-8")
        base = _commit(repo, "base")
        (repo / "tests" / "old.py").write_text("merged\n", encoding="utf-8")
        merge = _commit(repo, "merge")
        text = harness._git_text(repo, ["diff", "--name-status", "--no-renames", base, merge])
        case = harness.CorpusCase("case", 1, base, merge, harness.hashlib.sha256(text.encode()).hexdigest(), ("tests/old.py",))
        worktree = tmp_path / "worktree"
        _git(repo, "worktree", "add", "--detach", str(worktree), base)
        try:
            harness._apply_historical_diff(repo, worktree, case)
            assert (worktree / "tests" / "old.py").read_text(encoding="utf-8") == "merged\n"
            (repo / "tests" / "old.py").write_text("candidate\n", encoding="utf-8")
            (repo / "new.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            (repo / "new.sh").chmod(0o755)
            (repo / "delete.txt").unlink()
            candidate = _commit(repo, "candidate")
            harness._overlay_delta(repo, worktree, merge, candidate)
            assert (worktree / "tests" / "old.py").read_text(encoding="utf-8") == "candidate\n"
            assert os.stat(worktree / "new.sh").st_mode & 0o111
            assert not (worktree / "delete.txt").exists()
        finally:
            _git(repo, "worktree", "remove", "--force", str(worktree))

    def test_overlay_rejects_unsupported_status_and_mode(self, tmp_path: Path) -> None:
        rows = ["X\tx\n", "M\tx\n"]
        with patch.object(harness, "_git_text", side_effect=["", "", rows[0]]):
            with pytest.raises(harness.HarnessError, match="unsupported engine delta row"):
                harness._overlay_delta(tmp_path, tmp_path, "a", "b")
        with patch.object(harness, "_git_text", side_effect=["", "", rows[1], "120000 blob\tx\n"]):
            with pytest.raises(harness.HarnessError, match="unsupported engine delta mode"):
                harness._overlay_delta(tmp_path, tmp_path, "a", "b")


class TestNodeCapture:
    def test_pytest_command_detection_and_instrumentation(self, tmp_path: Path, monkeypatch) -> None:
        assert harness._is_pytest_execution([sys.executable, "-m", "pytest", "tests/x.py"])
        assert not harness._is_pytest_execution([sys.executable, "-m", "pytest", "--collect-only", "tests/x.py"])
        assert not harness._is_pytest_execution(["git", "status"])
        monkeypatch.setenv("KEEP", "outer")
        stale = tmp_path / "pytest-0-nodes.jsonl"
        stale.write_text("stale", encoding="utf-8")
        command, env, junit, events = harness._instrumented_pytest_command(
            [sys.executable, "-m", "pytest", "tests/x.py"], tmp_path, 0, {"KEEP": "inner"}
        )
        assert command[-3:] == [f"--junitxml={junit}", "-p", harness.PLUGIN_NAME]
        assert env["KEEP"] == "inner"
        assert env["PYTHONPATH"].split(os.pathsep)[0] == str(tmp_path)
        assert events == stale
        assert not stale.exists()

    def test_generated_plugin_preserves_native_parameterized_nodeid(self, tmp_path: Path) -> None:
        test_file = tmp_path / "test_sample.py"
        test_file.write_text(
            "import pytest\n\n@pytest.mark.parametrize('value', [1])\ndef test_value(value):\n    assert value\n",
            encoding="utf-8",
        )
        (tmp_path / f"{harness.PLUGIN_NAME}.py").write_text(harness.PLUGIN_SOURCE, encoding="utf-8")
        command, env, junit, events = harness._instrumented_pytest_command(
            [sys.executable, "-m", "pytest", str(test_file), "-q"], tmp_path, 0, None
        )
        result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8")
        assert result.returncode == 0, result.stdout + result.stderr
        harness._validate_junit(junit)
        captured = harness._read_events(events)
        assert any(row["nodeid"].endswith("test_sample.py::test_value[1]") for row in captured)

    def test_junit_and_event_validation_fail_loudly(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing"
        with pytest.raises(harness.HarnessError, match="required JUnit"):
            harness._validate_junit(missing)
        bad_xml = tmp_path / "bad.xml"
        bad_xml.write_text("<bad", encoding="utf-8")
        with pytest.raises(harness.HarnessError, match="invalid JUnit"):
            harness._validate_junit(bad_xml)
        with pytest.raises(harness.HarnessError, match="native node events"):
            harness._read_events(missing)
        bad_events = tmp_path / "bad.jsonl"
        bad_events.write_text("[]\n", encoding="utf-8")
        with pytest.raises(harness.HarnessError, match="invalid native node events"):
            harness._read_events(bad_events)

    @pytest.mark.parametrize(
        ("event", "verdict"),
        [
            ({"when": "call", "outcome": "passed"}, "pass"),
            ({"when": "call", "outcome": "failed"}, "fail"),
            ({"when": "call", "outcome": "skipped"}, "skipped"),
            ({"when": "call", "outcome": "skipped", "wasxfail": True}, "xfailed"),
            ({"when": "call", "outcome": "passed", "wasxfail": True}, "xpassed"),
            ({"when": "setup", "outcome": "failed"}, "fail"),
            ({"when": "teardown", "outcome": "failed"}, "fail"),
            ({"when": "setup", "outcome": "skipped"}, "skipped"),
            ({"when": "setup", "outcome": "passed"}, None),
        ],
    )
    def test_event_verdict_vocabulary(self, event: dict, verdict: str | None) -> None:
        assert harness._event_verdict(event) == verdict

    def test_consolidation_and_union_comparison_keep_missing_and_deferred_distinct(self) -> None:
        events = [
            {"nodeid": "tests/a.py::test_a", "when": "call", "outcome": "passed"},
            {"nodeid": "tests/a.py::test_a", "when": "call", "outcome": "failed"},
            {"nodeid": "tests/b.py::test_b", "when": "call", "outcome": "passed"},
            {"nodeid": "tests/ignored.py::test_x", "when": "setup", "outcome": "passed"},
        ]
        nodes = harness.consolidate_nodes(events, {"tests/b.py": "duckdb"})
        assert nodes == {"tests/a.py::test_a": "fail", "tests/b.py::test_b": "deferred"}
        baseline = {"nodes": nodes, "deferred_modules": {"tests/b.py": "duckdb"}, "gate_failures": []}
        candidate = {
            "nodes": {"tests/c.py::test_c": "pass"},
            "deferred_modules": {"tests/a.py": "numpy"},
            "gate_failures": ["Tests (pytest)"],
        }
        compared = harness.compare_captures(baseline, candidate)
        assert compared["union_node_count"] == 3
        assert compared["changed_node_count"] == 3
        assert compared["gate_failures_changed"] is True
        assert compared["difference_count"] == 4
        by_id = {row["nodeid"]: row for row in compared["nodes"]}
        assert by_id["tests/a.py::test_a"] == {
            "nodeid": "tests/a.py::test_a",
            "baseline": "fail",
            "candidate": "deferred",
        }
        assert by_id["tests/c.py::test_c"]["baseline"] == "not-collected"


class TestWorkerAndOrchestration:
    def test_environment_wrapper_delegates_to_support(self, tmp_path: Path) -> None:
        expected = (Path(sys.executable), "key")
        with patch("scripts.checks.deps.fast_tier_harness_support.ensure_fast_environment", return_value=expected) as ensure:
            assert harness._ensure_fast_environment(tmp_path, tmp_path / "cache") == expected
        ensure.assert_called_once_with(tmp_path, tmp_path / "cache")

    def test_worker_drives_real_seams_and_emits_capture(self, tmp_path: Path, monkeypatch) -> None:
        repo = tmp_path / "repo"
        (repo / "tests").mkdir(parents=True)
        (repo / "logs" / "debug").mkdir(parents=True)
        (repo / "tests" / "test_sample.py").write_text("def test_sample():\n    assert True\n", encoding="utf-8")
        (repo / "requirements.txt").write_text("full\n", encoding="utf-8")
        (repo / "requirements-fast.txt").write_text("fast\n", encoding="utf-8")
        diff_path = tmp_path / "diff.json"
        diff_path.write_text('[{"status": "M", "path": "scripts/x.py"}]', encoding="utf-8")
        output = tmp_path / "capture" / "result.json"
        fake_common = types.SimpleNamespace(run=subprocess.run)

        def derive(entries, *, repo_root):
            assert entries == [("M", "scripts/x.py")]
            assert repo_root == repo
            return {"selected": ["tests/test_sample.py"], "manifest": {"selected": ["tests/test_sample.py"]}}

        def run_pytest_diff(selected, failed):
            assert selected == ["tests/test_sample.py"]
            fake_common.run([sys.executable, "-m", "pytest", "--collect-only", "-q", *selected], cwd=repo)
            result = fake_common.run(
                [sys.executable, "-m", "pytest", *selected, "-q"],
                cwd=repo,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if result.returncode:
                failed.append("Tests (pytest)")
            (repo / "logs" / "debug" / "diff-coverage-deferrals.json").write_text(
                '{"state": "ok", "deferred": {}}', encoding="utf-8"
            )

        fake_pytest_diff = types.SimpleNamespace(
            run_pytest_diff=run_pytest_diff,
            DEFERRAL_MAP_REL="logs/debug/diff-coverage-deferrals.json",
        )
        fake_affected = types.ModuleType("scripts.checks.deps.affected_tests")
        fake_affected.derive_affected_tests = derive
        import scripts.checks as checks

        monkeypatch.setattr(checks, "_common", fake_common)
        monkeypatch.setattr(checks, "_pytest_diff", fake_pytest_diff, raising=False)
        monkeypatch.setitem(sys.modules, "scripts.checks.deps.affected_tests", fake_affected)
        original_path = list(sys.path)
        try:
            harness._worker(repo, diff_path, output)
        finally:
            sys.path[:] = original_path
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["nodes"] == {"tests/test_sample.py::test_sample": "pass"}
        assert payload["gate_failures"] == []
        assert payload["commands"][0]["junit"] == "pytest-0.xml"
        assert payload["environment"]["requirements_sha256"] == harness._file_sha256(repo / "requirements.txt")
        assert harness._file_sha256(repo / "absent") is None

    def test_worker_requires_the_real_deferral_artifact(self, tmp_path: Path, monkeypatch) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        diff_path = tmp_path / "diff.json"
        diff_path.write_text("[]", encoding="utf-8")
        fake_common = types.SimpleNamespace(run=subprocess.run)
        fake_pytest_diff = types.SimpleNamespace(run_pytest_diff=lambda selected, failed: None)
        fake_affected = types.ModuleType("scripts.checks.deps.affected_tests")
        fake_affected.derive_affected_tests = lambda entries, repo_root: {"selected": [], "manifest": {}}
        import scripts.checks as checks

        monkeypatch.setattr(checks, "_common", fake_common)
        monkeypatch.setattr(checks, "_pytest_diff", fake_pytest_diff, raising=False)
        monkeypatch.setitem(sys.modules, "scripts.checks.deps.affected_tests", fake_affected)
        original_path = list(sys.path)
        try:
            with pytest.raises(harness.HarnessError, match="did not emit its deferral map"):
                harness._worker(repo, diff_path, tmp_path / "capture" / "result.json")
        finally:
            sys.path[:] = original_path

    def test_prepared_worktree_orders_patch_then_overlay(self, tmp_path: Path) -> None:
        case = harness.CorpusCase("case", 1, "a" * 40, "b" * 40, "c" * 64, ("tests/x.py",))

        @contextlib.contextmanager
        def fake_worktree(ref, repo_root):
            assert ref == case.merge_parent_sha
            yield tmp_path / "wt"

        calls: list[str] = []
        with (
            patch("scripts.verification_graduation.git_worktree", fake_worktree),
            patch.object(harness, "_apply_historical_diff", side_effect=lambda *args: calls.append("historical")),
            patch.object(harness, "_overlay_delta", side_effect=lambda *args: calls.append("overlay")),
        ):
            with harness._prepared_worktree(tmp_path, case, "base", "head") as worktree:
                assert worktree == tmp_path / "wt"
        assert calls == ["historical", "overlay"]

    def test_capture_case_handles_success_worker_failure_and_bad_output(self, tmp_path: Path) -> None:
        case = harness.CorpusCase("case", 1, "a" * 40, "b" * 40, "c" * 64, ("tests/x.py",))

        @contextlib.contextmanager
        def prepared(*args):
            yield tmp_path

        output = tmp_path / "out" / "capture.json"

        def successful_run(command, **kwargs):
            output.write_text('{"nodes": {}, "deferred_modules": {}, "environment": {}}', encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(harness, "_prepared_worktree", prepared), patch.object(harness.subprocess, "run", successful_run):
            with patch.object(harness, "_ensure_fast_environment", return_value=(Path(sys.executable), "env-key")):
                capture = harness.capture_case(
                    tmp_path, case, [("M", "tests/x.py")], "base", "base", output, tmp_path / "environments"
                )
            assert capture["nodes"] == {}
            assert capture["environment"]["fingerprint"] == "env-key"
            assert json.loads(output.read_text(encoding="utf-8"))["environment"]["fingerprint"] == "env-key"
        with (
            patch.object(harness, "_prepared_worktree", prepared),
            patch.object(harness, "_ensure_fast_environment", return_value=(Path(sys.executable), "env-key")),
            patch.object(harness.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "out", "err")),
        ):
            with pytest.raises(harness.HarnessError, match="worker failed.*outerr"):
                harness.capture_case(tmp_path, case, [], "base", "head", output, tmp_path / "environments")
        output.write_text("bad", encoding="utf-8")
        with (
            patch.object(harness, "_prepared_worktree", prepared),
            patch.object(harness, "_ensure_fast_environment", return_value=(Path(sys.executable), "env-key")),
            patch.object(harness.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")),
        ):
            with pytest.raises(harness.HarnessError, match="cannot read"):
                harness.capture_case(tmp_path, case, [], "base", "head", output, tmp_path / "environments")

    def test_run_comparison_filters_cases_and_writes_union(self, tmp_path: Path) -> None:
        corpus = harness.load_corpus(CORPUS_PATH)
        output = tmp_path / "result.json"
        captures = [
            {"nodes": {"tests/x.py::test_x": "pass"}, "deferred_modules": {}, "gate_failures": []},
            {"nodes": {}, "deferred_modules": {}, "gate_failures": []},
        ]
        with (
            patch.object(harness, "historical_diff", return_value=[]),
            patch.object(harness, "capture_case", side_effect=captures),
        ):
            result = harness.run_comparison(ROOT, corpus, "base", "head", output, {"pr-1128"})
        assert result["stratum_i"]["cases"][0]["comparison"]["changed_nodes"][0]["candidate"] == "not-collected"
        assert json.loads(output.read_text(encoding="utf-8"))["candidate_ref"] == "head"
        with pytest.raises(harness.HarnessError, match="unknown corpus case"):
            harness.run_comparison(ROOT, corpus, "base", "head", output, {"missing"})

    def test_main_validate_and_compare_dispatch(self, capsys, tmp_path: Path) -> None:
        assert harness.main(["validate-corpus", "--corpus", str(CORPUS_PATH)]) == 0
        assert "implementation=16 predictor=8" in capsys.readouterr().out
        with patch.object(harness, "run_comparison", return_value={"stratum_i": {"case_count": 0}}) as run:
            assert (
                harness.main(
                    [
                        "compare",
                        "--corpus",
                        str(CORPUS_PATH),
                        "--baseline-ref",
                        "base",
                        "--candidate-ref",
                        "head",
                        "--output",
                        str(tmp_path / "out.json"),
                        "--case",
                        "pr-1128",
                    ]
                )
                == 0
            )
        assert run.call_args.args[-1] == {"pr-1128"}
        with patch.object(harness, "_worker") as worker:
            assert harness.main(["_worker", str(tmp_path), str(tmp_path / "diff"), str(tmp_path / "out")]) == 0
        worker.assert_called_once()
