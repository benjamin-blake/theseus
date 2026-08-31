"""Differential admission gate self-test (T3.1, Decision 104)."""

from __future__ import annotations

from scripts.checks import _common, registry


@registry.register("validate_differential_gate_baseline", owner="platform")
def validate_differential_gate_baseline(failed: list[str]) -> None:
    """Exercise the REAL differential admission gate on the kernel's own self-test (full tier, T3.1).

    Two real, non-simulated legs (PLAN-verification-graduation-gate-fix -- the prior hardcoded-FAIL
    revert_runner contradicted scripts.verification_graduation's own "a REAL worktree, never
    simulated" contract):
      (i)  Interpreter parity -- a bin/venv-python command_exit_zero probe that passes live must
           also pass in a freshly materialized `git worktree` of HEAD. Stable with or without a
           `.venv` present (CI has neither; bin/venv-python's own PATH+pydantic fallback covers
           that case) -- a live-pass/scratch-fail split means the .venv-provisioning fix in
           scripts.verification_graduation.git_worktree regressed.
      (ii) The same probe, run end-to-end through run_differential, must be REJECTED as
           tautological -- the exact defect this plan removes. Before the fix, an unprovisioned
           revert worktree made the probe FAIL there for environmental reasons, which
           run_differential misread as content discrimination and silently admitted.

    Production baseline execution surfaces: the validate.py CI hard-gate (this function, live)
    and the Step-Functions executor verify-state (named surface, deferred per CD.27).
    """
    print("\n=== Differential admission gate baseline (T3.1) ===")
    root_str = str(_common.ROOT)
    import sys as _sys  # noqa: PLC0415

    injected = root_str not in _sys.path
    if injected:
        _sys.path.insert(0, root_str)
    try:
        from scripts import verification_graduation as vg  # noqa: PLC0415
        from scripts.verification_checks import CANONICAL_SLOTS, CheckStatus  # noqa: PLC0415
    finally:
        if injected and root_str in _sys.path:
            _sys.path.remove(root_str)

    if len(CANONICAL_SLOTS) != 6:
        failed.append(f"Differential gate baseline: CANONICAL_SLOTS has {len(CANONICAL_SLOTS)} entries, expected 6")
        registry.skipped("CANONICAL_SLOTS invariant violated")
        return

    probe_row = {
        "check_id": "differential-gate-baseline-tautology-probe",
        "primitive_slot": "command_exit_zero",
        "check_spec": {"command": ["bin/venv-python", "-c", "print(1)"]},
    }

    # (i) interpreter parity: the identical probe command, live vs. a scratch worktree of HEAD.
    live_status = vg.materialize_check_in_tree(probe_row, _common.ROOT).run().status
    if live_status != CheckStatus.PASS:
        failed.append(f"Differential gate baseline: bin/venv-python probe FAILED live (status={live_status.value})")
        registry.skipped("bin/venv-python failing live")
        return

    try:
        with vg.git_worktree("HEAD", repo_root=_common.ROOT) as wt_root:
            scratch_status = vg.materialize_check_in_tree(probe_row, wt_root).run().status
    except vg.GraduationError as exc:
        failed.append(f"Differential gate baseline: could not materialize a scratch worktree for parity check: {exc}")
        registry.skipped("scratch worktree unavailable")
        return

    if scratch_status != CheckStatus.PASS:
        failed.append(
            "Differential gate baseline: bin/venv-python passes live but FAILS in a scratch worktree of HEAD "
            f"(status={scratch_status.value}) -- the .venv-provisioning fix in "
            "scripts.verification_graduation.git_worktree may have regressed"
        )
        registry.examined(1, unit="differential_gate_self_checks")
        return
    print("  OK: bin/venv-python resolves identically live and in a scratch worktree of HEAD.")

    # (ii) the same probe, run end-to-end, must be REJECTED -- never silently admitted.
    try:
        outcome = vg.run_differential(probe_row, repo_root=_common.ROOT)
    except vg.GraduationError as exc:
        failed.append(f"Differential gate baseline: tautology probe raised unexpectedly: {exc}")
        registry.examined(1, unit="differential_gate_self_checks")
        return
    if outcome.admitted:
        failed.append(
            "Differential gate baseline: known-tautological bin/venv-python probe was ADMITTED "
            f"(should be rejected as tautological): {outcome.reason}"
        )
        registry.examined(2, unit="differential_gate_self_checks")
        return

    print(f"  OK: tautological probe correctly rejected -- {outcome.reason}")
    print(f"  OK: differential gate baseline passed; CANONICAL_SLOTS={sorted(CANONICAL_SLOTS)}")
    registry.examined(2, unit="differential_gate_self_checks")
