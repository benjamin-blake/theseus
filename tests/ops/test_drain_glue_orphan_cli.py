"""Sub-command routing, the facade surface, the per-leg profile wiring, the step-record chain,
and the next_action contract for scripts/ops/drain_glue_orphan (the CLI package).
"""

from __future__ import annotations

import ast
import json
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.ci import reconcile_target
from scripts.ops.drain_glue_orphan.__main__ import main
from scripts.ops.drain_glue_orphan._phases import (
    converge_verify,
    phase_close,
    remove_correlate,
    remove_verify,
)
from scripts.ops.drain_glue_orphan._world import (
    _TFSTATE_BUCKET,
    _TFSTATE_KEY,
    WorldMovedError,
    derive_remove_state,
    gate_converge_preconditions,
    gate_remove_preconditions,
)
from tests.fixtures.drain_glue_orphan import (
    RED_RECORD,
    apply_sandbox_jobs,
    job_log,
    load_payload,
    make_s3,
    reader_returning,
    recording_boto3,
    unreachable_file_rec,
)

_ORIGIN_MAIN_PATH = "origin/main:scripts/ops/drain_glue_orphan.py"


def _write_json(tmp_path: Path, name: str, data: Any) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return str(path)


def _run_main(tmp_path: Path, phase: str, step: str, out_name: str = "out.json", **flags: Any) -> tuple[int, dict[str, Any]]:
    """Builds one main() invocation from short kwarg names (e.g. run_json=... becomes
    --run-json ...; dispatch_timestamp_from_record=True becomes the bare flag) and returns
    (exit_code, parsed --out JSON or {} if nothing was written)."""
    args = ["--phase", phase, "--step", step]
    for key, value in flags.items():
        flag = "--" + key.replace("_", "-")
        args += [flag] if value is True else [flag, str(value)]
    out = tmp_path / out_name
    args += ["--out", str(out)]
    rc = main(args)
    return rc, (json.loads(out.read_text()) if out.exists() else {})


class TestFacadeSurface:
    """VP2: the facade re-exports the full public surface of the deleted module, derived from the
    pre-change file at origin/main rather than a hand-listed set, so a name dropped in the move
    reds instead of surfacing as an ImportError at drain time.

    _EXEMPT names ten symbols the pre-split module carried that this restructure deliberately
    retires rather than renames -- each superseded, documented in scripts/ops/drain_glue_orphan/
    __init__.py's own module docstring (that docstring is the durable record; this dict exists so
    the test can subtract it, not to duplicate the rationale)."""

    _EXEMPT = {
        "wait_for_terminal",
        "correlate_dispatch",
        "phase_remove",
        "phase_converge",
        "CorrelationResult",
        "_gh_json",
        "_live_run_lister_for",
        "_live_run_viewer",
        "_live_converge_run_viewer",
        "_live_dispatch_reconcile",
        "_live_dispatch_apply_sandbox",
    }

    @staticmethod
    def _module_level_names(source: str) -> set[str]:
        """Collects names DEFINED at module top level: function/class defs and assignment
        targets. Deliberately excludes bare `import x` / `from x import y` bindings -- Decision
        124's facade precedent re-exports a SPECIFIC, enumerated set of imported-name "traps"
        (chosen because tests patch them), not every transitively-imported library reference; a
        blanket import re-export would force this facade to expose argparse/json/subprocess/sys/
        time/yaml/Path/Any/Callable/Optional/reconcile_target as its own attributes for no reason
        any caller needs."""
        tree = ast.parse(source)
        names: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
        return names

    def test_every_non_exempt_name_from_origin_main_is_importable(self) -> None:
        result = subprocess.run(["git", "show", _ORIGIN_MAIN_PATH], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            pytest.skip(f"{_ORIGIN_MAIN_PATH} unreachable: {result.stderr.strip()}")
        names = self._module_level_names(result.stdout)
        assert names, "AST walk found zero module-level names -- accessor broken, not an empty module"
        non_dunder = {n for n in names if not (n.startswith("__") and n.endswith("__"))}
        expected = non_dunder - self._EXEMPT
        assert expected, "expected-name set collapsed to empty -- the exemption list has grown to swallow everything"
        unknown_exemptions = self._EXEMPT - non_dunder
        assert not unknown_exemptions, (
            f"exempted name(s) no longer exist in origin/main -- stale exemption(s): {unknown_exemptions}"
        )

        import scripts.ops.drain_glue_orphan as facade

        missing = sorted(n for n in expected if not hasattr(facade, n))
        assert not missing, f"facade gap -- name(s) dropped in the move, not deliberately exempted: {missing}"

    def test_module_entry_point_resolves_to_main(self) -> None:
        import scripts.ops.drain_glue_orphan.__main__ as entry

        assert entry.main is main


class TestPreconditionGates:
    """Moved from tests/ops/test_drain_glue_orphan.py::TestPhasePreconditions (VP10) -- proves
    fresh-world-proceeds / moved-world-fails-closed (naming the fluent) and the CROSS-PHASE rec
    lifecycle, adapted to the two-client (profile_s3_client, state_s3_client) signature Decision
    143 / VP5 requires."""

    def test_fresh_world_derives_and_gates_cleanly(self) -> None:
        s3 = make_s3(RED_RECORD, orphan_present=True)
        state = derive_remove_state(s3, s3, reader_returning("closed"))
        gate_remove_preconditions(state)  # must not raise

    def test_moved_world_fails_closed(self) -> None:
        s3 = make_s3({"status": "green"}, orphan_present=True)
        state = derive_remove_state(s3, s3, reader_returning("closed"))
        with pytest.raises(WorldMovedError, match="not reconcilable"):
            gate_remove_preconditions(state)

    def test_moved_world_orphan_already_drained_fails_closed(self) -> None:
        s3 = make_s3(RED_RECORD, orphan_present=False)
        state = derive_remove_state(s3, s3, reader_returning("closed"))
        with pytest.raises(WorldMovedError, match="no longer in tfstate"):
            gate_remove_preconditions(state)

    def test_moved_world_bundled_rec_still_open_fails_closed(self) -> None:
        s3 = make_s3(RED_RECORD, orphan_present=True)
        state = derive_remove_state(s3, s3, reader_returning("open"))
        with pytest.raises(WorldMovedError, match="still open"):
            gate_remove_preconditions(state)

    def test_one_rec_state_satisfies_both_remove_and_close(self) -> None:
        """Cross-phase lifecycle pin: remove and close must be satisfiable by ONE rec state, or
        remove is unreachable in its own sequence (rec-autoclose.yml flips both recs at the merge
        the drain itself depends on)."""
        reader = reader_returning("closed")
        s3 = make_s3(RED_RECORD, orphan_present=True)
        gate_remove_preconditions(derive_remove_state(s3, s3, reader))
        close_s3 = make_s3(None, orphan_present=False)
        outcome = phase_close(
            profile_s3_client=close_s3,
            state_s3_client=close_s3,
            rec_reader=reader,
            file_rec=lambda fields, profile=None: "rec-9999",
            get_rec_write_guidance=lambda **kw: None,
        )
        assert outcome.status != "recs_still_open", outcome

    def test_pre_merge_open_rec_state_satisfies_neither_phase(self) -> None:
        reader = reader_returning("open")
        s3 = make_s3(RED_RECORD, orphan_present=True)
        with pytest.raises(WorldMovedError, match="still open"):
            gate_remove_preconditions(derive_remove_state(s3, s3, reader))
        close_s3 = make_s3(None, orphan_present=False)
        outcome = phase_close(
            profile_s3_client=close_s3,
            state_s3_client=close_s3,
            rec_reader=reader,
            file_rec=unreachable_file_rec,
            get_rec_write_guidance=lambda **kw: None,
        )
        assert outcome.status == "recs_still_open"

    def test_converge_moved_world_record_not_red_fails_closed(self) -> None:
        with pytest.raises(WorldMovedError, match="not CONVERGENCE_RED"):
            gate_converge_preconditions({"status": "green"}, orphan_in_state=False)

    def test_converge_moved_world_orphan_still_present_fails_closed(self) -> None:
        with pytest.raises(WorldMovedError, match="still in tfstate"):
            gate_converge_preconditions(RED_RECORD, orphan_in_state=True)

    def test_orphan_still_in_state_refuses_close(self) -> None:
        outcome = phase_close(
            profile_s3_client=make_s3(None, orphan_present=True),
            state_s3_client=make_s3(None, orphan_present=True),
            rec_reader=reader_returning("closed"),
            file_rec=unreachable_file_rec,
            get_rec_write_guidance=lambda **kw: {},
        )
        assert outcome.status == "orphan_still_in_state"

    def test_close_files_removal_rec_once_both_preconditions_confirmed(self) -> None:
        filed: dict[str, Any] = {}
        calls: list[str] = []

        def _tracked_file_rec(fields: dict[str, Any], profile: str | None = None) -> str:
            calls.append("file_rec")
            filed.update(fields)
            return "rec-9999"

        outcome = phase_close(
            profile_s3_client=make_s3(None, orphan_present=False),
            state_s3_client=make_s3(None, orphan_present=False),
            rec_reader=reader_returning("closed"),
            file_rec=_tracked_file_rec,
            get_rec_write_guidance=lambda **kw: calls.append("guidance"),
        )
        assert outcome.status == "filed"
        assert outcome.fluents["removal_rec_id"] == "rec-9999"
        assert filed["priority"] == "High" and filed["effort"] == "XS" and filed["source"] == "manual"
        assert calls == ["guidance", "file_rec"], calls


class TestProfileLegs:
    """VP5: the tfstate read is the ONLY leg using --state-profile; the convergence-record read,
    the DuckLake reader and the portal write all run as --profile, wired structurally via a
    recording session factory rather than probed. Defaults are agent_platform for --profile and
    agent_platform_admin for --state-profile."""

    @pytest.mark.parametrize(
        "extra_args,expected_state_profile,expected_profile",
        [
            ([], "agent_platform_admin", "agent_platform"),
            (["--profile", "custom-dev", "--state-profile", "custom-admin"], "custom-admin", "custom-dev"),
        ],
        ids=["defaults", "explicit-flags"],
    )
    def test_tfstate_convergence_and_reader_use_the_right_profile(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        extra_args: list[str],
        expected_state_profile: str,
        expected_profile: str,
    ) -> None:
        objects = {
            (_TFSTATE_BUCKET, _TFSTATE_KEY): {"resources": [{"type": "aws_glue_catalog_database", "name": "ops"}]},
            (reconcile_target.CONVERGENCE_BUCKET, reconcile_target.CONVERGENCE_KEY): RED_RECORD,
        }
        fake_boto3, calls = recording_boto3(objects)
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        reader_profiles: list[str | None] = []
        monkeypatch.setattr(
            reconcile_target,
            "_default_reader",
            lambda profile: (reader_profiles.append(profile), reader_returning("closed"))[1],
        )
        runs = tmp_path / "runs.json"
        runs.write_text("[]")

        rc = main(
            ["--phase", "remove", "--step", "gate", "--runs-json", str(runs), "--out", str(tmp_path / "out.json"), *extra_args]
        )
        assert rc == 0

        tfstate_profiles = {p for p, b, k in calls if (b, k) == (_TFSTATE_BUCKET, _TFSTATE_KEY)}
        convergence_profiles = {
            p for p, b, k in calls if (b, k) == (reconcile_target.CONVERGENCE_BUCKET, reconcile_target.CONVERGENCE_KEY)
        }
        assert tfstate_profiles == {expected_state_profile}
        assert convergence_profiles == {expected_profile}
        assert reader_profiles == [expected_profile]

    def test_close_phase_files_rec_under_profile_flag(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        objects = {(_TFSTATE_BUCKET, _TFSTATE_KEY): {"resources": []}}
        fake_boto3, _ = recording_boto3(objects)
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        monkeypatch.setattr(reconcile_target, "_default_reader", lambda profile: reader_returning("closed"))

        import scripts.ops_data_portal as portal_module

        captured: dict[str, Any] = {}

        def _fake_file_rec(fields: dict[str, Any], profile: str | None = None) -> str:
            captured["profile"] = profile
            return "rec-4242"

        monkeypatch.setattr(portal_module, "file_rec", _fake_file_rec)
        rc = main(["--phase", "close", "--profile", "close-profile", "--out", str(tmp_path / "out.json")])
        assert rc == 0
        assert captured["profile"] == "close-profile"


class TestFailClosedChain:
    """VP4: every step refuses without its predecessor's on-disk record, and verify refuses to
    emit a destructive-licensing verdict from a truncated log or an uncorrelated/mismatched run."""

    def test_correlate_without_a_gate_record_exits_non_zero(self, tmp_path: Path) -> None:
        rc, _ = _run_main(
            tmp_path,
            "remove",
            "correlate",
            dispatch_timestamp_from_record=True,
            gate_record=tmp_path / "does-not-exist.json",
            runs_json=tmp_path / "also-missing.json",
        )
        assert rc == 1

    def test_verify_without_a_correlation_record_exits_non_zero(self, tmp_path: Path) -> None:
        rc, _ = _run_main(
            tmp_path,
            "remove",
            "verify",
            correlation_record=tmp_path / "missing.json",
            run_json=tmp_path / "missing2.json",
            job_logs_json=tmp_path / "missing3.json",
        )
        assert rc == 1

    @pytest.mark.parametrize("phase", ["remove", "converge"], ids=["remove-correlate", "converge-correlate"])
    def test_correlate_step_requires_dispatch_timestamp_from_record_flag(self, tmp_path: Path, phase: str) -> None:
        gate_record = _write_json(
            tmp_path, "gate.json", {"verdict": "dispatch", "fluents": {"dispatch_timestamp": "2026-01-01T00:00:00Z"}}
        )
        rc, _ = _run_main(
            tmp_path, phase, "correlate", gate_record=gate_record, runs_json=_write_json(tmp_path, "runs.json", [])
        )
        assert rc == 1

    def test_correlate_refuses_a_gate_record_without_dispatch_verdict(self) -> None:
        with pytest.raises(WorldMovedError, match="verdict=dispatch"):
            remove_correlate(gate_record={"verdict": "resume", "fluents": {}}, runs_payload=[])

    def test_correlate_refuses_a_gate_record_with_no_dispatch_timestamp(self) -> None:
        with pytest.raises(WorldMovedError, match="no dispatch_timestamp"):
            remove_correlate(gate_record={"verdict": "dispatch", "fluents": {}}, runs_payload=[])

    def test_verify_refuses_a_correlation_record_without_correlated_verdict(self) -> None:
        with pytest.raises(WorldMovedError, match="verdict=correlated"):
            remove_verify(
                correlation_record={"verdict": "no_candidates", "fluents": {}},
                run_payload={"id": 1, "status": "completed"},
                job_logs_payload={"logs_content": "", "original_length": 0},
            )

    def test_verify_refuses_a_run_id_that_disagrees_with_the_recorded_one(self) -> None:
        with pytest.raises(WorldMovedError, match="disagrees with recorded"):
            remove_verify(
                correlation_record={"verdict": "correlated", "fluents": {"run_id": 111}},
                run_payload={"id": 222, "status": "completed"},
                job_logs_payload={"logs_content": "", "original_length": 0},
            )

    def test_verify_more_than_one_correlation_candidate_raises(self) -> None:
        runs = [{"id": 1, "created_at": "2026-01-01T00:00:01Z"}, {"id": 2, "created_at": "2026-01-01T00:00:02Z"}]
        with pytest.raises(WorldMovedError, match="more than one"):
            remove_correlate(
                gate_record={"verdict": "dispatch", "fluents": {"dispatch_timestamp": "2026-01-01T00:00:00Z"}},
                runs_payload=runs,
            )

    def test_verify_truncated_log_raises_rather_than_terminal_without_destruction(self) -> None:
        truncated = load_payload("job_logs_envelope.json")
        with pytest.raises(WorldMovedError, match="truncated"):
            remove_verify(
                correlation_record={"verdict": "correlated", "fluents": {"run_id": 1}},
                run_payload={"id": 1, "status": "completed"},
                job_logs_payload=truncated,
            )

    def test_converge_verify_truncated_log_raises(self) -> None:
        truncated = load_payload("job_logs_envelope.json")
        jobs = apply_sandbox_jobs("success", job_id=truncated["job_id"])
        with pytest.raises(WorldMovedError, match="truncated"):
            converge_verify(
                correlation_record={"verdict": "correlated", "fluents": {"run_id": 1}},
                run_payload={"id": 1, "status": "completed"},
                jobs_payload=jobs,
                job_logs_payload=truncated,
                profile_s3_client=make_s3(None, orphan_present=False),
            )


class TestMainCli:
    def test_phase_step_pairing_is_enforced(self, tmp_path: Path) -> None:
        out = str(tmp_path / "out.json")
        with pytest.raises(SystemExit):
            main(["--phase", "remove", "--out", out])
        with pytest.raises(SystemExit):
            main(["--phase", "close", "--step", "gate", "--out", out])

    def test_out_file_is_written_on_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        objects = {
            (_TFSTATE_BUCKET, _TFSTATE_KEY): {"resources": [{"type": "aws_glue_catalog_database", "name": "ops"}]},
            (reconcile_target.CONVERGENCE_BUCKET, reconcile_target.CONVERGENCE_KEY): RED_RECORD,
        }
        fake_boto3, _ = recording_boto3(objects)
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        monkeypatch.setattr(reconcile_target, "_default_reader", lambda profile: reader_returning("closed"))
        rc, record = _run_main(tmp_path, "remove", "gate", runs_json=_write_json(tmp_path, "runs.json", []))
        assert rc == 0
        assert record["verdict"] == "dispatch"
        assert "next_action" in record

    def test_world_moved_is_reported_on_stderr_and_writes_no_out_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        objects = {
            (_TFSTATE_BUCKET, _TFSTATE_KEY): {"resources": [{"type": "aws_glue_catalog_database", "name": "ops"}]},
            (reconcile_target.CONVERGENCE_BUCKET, reconcile_target.CONVERGENCE_KEY): {"status": "green"},
        }
        fake_boto3, _ = recording_boto3(objects)
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        monkeypatch.setattr(reconcile_target, "_default_reader", lambda profile: reader_returning("closed"))
        rc, _ = _run_main(tmp_path, "remove", "gate", runs_json=_write_json(tmp_path, "runs.json", []))
        assert rc == 1
        assert "world_moved" in capsys.readouterr().err
        assert not (tmp_path / "out.json").exists()

    def test_close_phase_end_to_end(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        objects = {(_TFSTATE_BUCKET, _TFSTATE_KEY): {"resources": []}}
        fake_boto3, _ = recording_boto3(objects)
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        monkeypatch.setattr(reconcile_target, "_default_reader", lambda profile: reader_returning("closed"))
        import scripts.ops_data_portal as portal_module

        monkeypatch.setattr(portal_module, "file_rec", lambda fields, profile=None: "rec-1234")
        rc = main(["--phase", "close", "--out", str(tmp_path / "out.json")])
        assert rc == 0

    # This module is already imported at collection time by other test files in this package
    # (and by this file's own top-level `from ...__main__ import main`), so it is already in
    # sys.modules by the time runpy re-executes it below -- the standard, benign runpy caveat
    # for this pattern (docs.python.org/3/library/runpy.html), same precedent as
    # tests/verify_ci_workflow/test_cli_main.py::TestCliMain.
    @pytest.mark.filterwarnings("ignore:.*found in sys.modules.*:RuntimeWarning")
    def test_runpy_entrypoint_exits_with_mains_return_code(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(
            sys, "argv", ["drain_glue_orphan", "--phase", "close", "--step", "gate", "--out", str(tmp_path / "out.json")]
        )
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("scripts.ops.drain_glue_orphan.__main__", run_name="__main__")
        assert exc_info.value.code == 2  # argparse usage error: --phase close does not take --step


class TestMainCliFullDispatch:
    """Exercises every --phase/--step branch through main() itself as a REAL gate->correlate->
    verify chain (not just the underlying _phases functions directly, and not just each step in
    isolation against a hand-written predecessor record) -- each phase's own gate/verify --out
    file feeds the next step's --gate-record/--correlation-record, the way the runbook actually
    chains. Also covers the omitted-required-flag path (--runs-json entirely absent, not merely
    pointing at a missing file) -- _load_json's `not path` branch."""

    def test_gate_step_without_runs_json_flag_exits_non_zero(self, tmp_path: Path) -> None:
        rc, _ = _run_main(tmp_path, "remove", "gate")
        assert rc == 1

    def test_remove_gate_correlate_verify_chain_through_cli(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        objects = {
            (_TFSTATE_BUCKET, _TFSTATE_KEY): {"resources": [{"type": "aws_glue_catalog_database", "name": "ops"}]},
            (reconcile_target.CONVERGENCE_BUCKET, reconcile_target.CONVERGENCE_KEY): RED_RECORD,
        }
        fake_boto3, _ = recording_boto3(objects)
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        monkeypatch.setattr(reconcile_target, "_default_reader", lambda profile: reader_returning("closed"))

        rc, gate = _run_main(tmp_path, "remove", "gate", "gate.json", runs_json=_write_json(tmp_path, "runs.json", []))
        assert rc == 0 and gate["verdict"] == "dispatch"

        runs_after = _write_json(
            tmp_path, "runs-after.json", [{"id": 1, "status": "completed", "created_at": "2099-01-01T00:00:00Z"}]
        )
        rc, correlate = _run_main(
            tmp_path,
            "remove",
            "correlate",
            "correlate.json",
            dispatch_timestamp_from_record=True,
            gate_record=tmp_path / "gate.json",
            runs_json=runs_after,
        )
        assert rc == 0 and correlate["verdict"] == "correlated"

        run_json = _write_json(tmp_path, "run.json", {"id": 1, "status": "completed"})
        job_logs = _write_json(
            tmp_path,
            "job_logs.json",
            job_log("aws_glue_catalog_database.ops: Destruction complete"),
        )
        rc, verify = _run_main(
            tmp_path,
            "remove",
            "verify",
            "verify.json",
            correlation_record=tmp_path / "correlate.json",
            run_json=run_json,
            job_logs_json=job_logs,
        )
        assert rc == 0 and verify["verdict"] == "drained"

    def test_converge_gate_correlate_verify_chain_through_cli(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        objects = {
            (_TFSTATE_BUCKET, _TFSTATE_KEY): {"resources": []},
            (reconcile_target.CONVERGENCE_BUCKET, reconcile_target.CONVERGENCE_KEY): RED_RECORD,
        }
        fake_boto3, _ = recording_boto3(objects)
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

        rc, gate = _run_main(tmp_path, "converge", "gate", "gate.json", runs_json=_write_json(tmp_path, "runs.json", []))
        assert rc == 0 and gate["verdict"] == "dispatch"
        assert gate["next_action"]["inputs"]["acknowledge_red_commit"] == RED_RECORD["commit_sha"]

        runs_after = _write_json(
            tmp_path, "runs-after.json", [{"id": 2, "status": "completed", "created_at": "2099-01-01T00:00:00Z"}]
        )
        rc, correlate = _run_main(
            tmp_path,
            "converge",
            "correlate",
            "correlate.json",
            dispatch_timestamp_from_record=True,
            gate_record=tmp_path / "gate.json",
            runs_json=runs_after,
        )
        assert rc == 0 and correlate["verdict"] == "correlated"

        monkeypatch.setitem(
            sys.modules,
            "boto3",
            recording_boto3(
                {
                    # run_id names the run that WROTE the record -- fact 4 is correlated, so an
                    # anonymous green no longer licenses converge.
                    (reconcile_target.CONVERGENCE_BUCKET, reconcile_target.CONVERGENCE_KEY): {
                        "status": "green",
                        "run_id": "2",
                    }
                }
            )[0],
        )
        run_json = _write_json(tmp_path, "run.json", {"id": 2, "status": "completed"})
        jobs_json = _write_json(
            tmp_path,
            "jobs.json",
            apply_sandbox_jobs("success"),
        )
        job_logs = _write_json(tmp_path, "job_logs.json", job_log())
        rc, verify = _run_main(
            tmp_path,
            "converge",
            "verify",
            "verify.json",
            correlation_record=tmp_path / "correlate.json",
            run_json=run_json,
            jobs_json=jobs_json,
            job_logs_json=job_logs,
        )
        assert rc == 0 and verify["verdict"] == "converged"
