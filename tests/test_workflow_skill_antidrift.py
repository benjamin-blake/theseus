"""Anti-drift contract for the /plan and /implement workflow surfaces.

Each assertion here pins a decision that has no other enforcement counterpart: the shared
preflight venv row, the one-full-tier rule, the verify-do-not-re-derive shape of the critique
checks, the single author-side `plan_obligations` run, and the plan context-block cap.
"""

from pathlib import Path

_IMPLEMENT_SKILL = Path(".claude/skills/implement/SKILL.md")
_PLANNING_SKILL = Path(".claude/skills/planning/SKILL.md")
_CRITIQUE_SKILL = Path(".claude/skills/plan-critique/SKILL.md")
_IMPLEMENT_CMD = Path(".claude/commands/implement.md")
_PLAN_CMD = Path(".claude/commands/plan.md")
_DQ_RUNNER = Path("scripts/data_quality_runner.py")

_FULL_TIER = "bin/venv-python -m scripts.validate"

_VENV_ROW = (
    '- **`venv_ok: false`** -- Verify `bin/venv-python -c "import sys; print(sys.executable)"` '
    "resolves to the venv interpreter and rerun preflight. If still false, STOP."
)


def test_preflight_venv_row_is_shared_verbatim_between_planning_and_implement() -> None:
    """The two skills' venv_ok remediation must not drift (AGENTS.md `## Shell invocations`)."""
    planning = _PLANNING_SKILL.read_text(encoding="utf-8")
    implement = _IMPLEMENT_SKILL.read_text(encoding="utf-8")
    assert _VENV_ROW in planning
    assert _VENV_ROW in implement
    for text in (planning, implement):
        assert "Auto-activate venv" not in text
        assert "source .venv/bin/activate" not in text


def test_full_tier_runs_once_and_only_in_the_step7_closure() -> None:
    """The full `scripts.validate` tier runs once per /implement session, in Step 7's closure."""
    workflow = _IMPLEMENT_CMD.read_text(encoding="utf-8")
    step6 = workflow[workflow.index("## Step 6") : workflow.index("## Step 7")]
    assert f"{_FULL_TIER} --pre" in step6
    assert "One-full-tier rule" in step6
    assert not any(line.strip().rstrip("`").endswith(_FULL_TIER) and "--pre" not in line for line in step6.splitlines())

    skill = _IMPLEMENT_SKILL.read_text(encoding="utf-8")
    closure = skill[skill.index("### Run the full gate locally first") :]
    assert skill.count(f"`{_FULL_TIER}`") == 1
    assert f"`{_FULL_TIER}`" in closure


def test_critique_verifies_rather_than_rederives() -> None:
    """12b/12k cross-check the plan's stated answer instead of recomputing it from raw sources."""
    critique = _CRITIQUE_SKILL.read_text(encoding="utf-8")
    lambda_check = critique[critique.index("12b.") : critique.index("12c.")]
    assert "VERIFY, do not re-derive" in lambda_check
    assert "--list-patterns" not in lambda_check
    assert "compute_affected_artifacts" in lambda_check
    assert "src/lambdas/<slug>/manifest.yaml" in lambda_check

    closure = critique[critique.index("12k.") : critique.index("12l.")]
    assert "VERIFY the plan's own declarations" in closure
    assert "**Closure Obligation (12k)" in critique


def test_planning_enforcement_names_the_critique_check_id() -> None:
    """Planning's closure-obligation enforcement must name the critique check that fires (12k)."""
    planning = _PLANNING_SKILL.read_text(encoding="utf-8")
    assert "fails plan-critique 12k" in planning


def test_plan_workflow_invokes_obligations_once_at_step_6b() -> None:
    """`plan_obligations` runs once author-side, at Step 6b, against a draft written OUTSIDE the repo.

    The draft path must stay outside `docs/plans/`: `{slug}` is not derived until Step 7, and a
    Write to the tracked plan path while on `main` is denied by `.claude/hooks/never_on_main.py`
    two steps before Step 7's designed clean STOP.
    """
    workflow = _PLAN_CMD.read_text(encoding="utf-8")
    assert workflow.count("scripts.roadmap.plan_obligations") == 1
    step4 = workflow[workflow.index("## Step 4") : workflow.index("## Step 5")]
    assert "plan_obligations" not in step4
    step6 = workflow[workflow.index("## Step 6") : workflow.index("## Step 7")]
    assert "scripts.roadmap.plan_obligations" in step6
    assert "a scratch path outside the repo" in step6
    assert "--plan docs/plans/" not in step6


def test_plan_context_block_cap_is_declared_on_both_surfaces() -> None:
    """The 40-line context cap appears in the PLAN template and as an authoring rule."""
    planning = _PLANNING_SKILL.read_text(encoding="utf-8")
    workflow = _PLAN_CMD.read_text(encoding="utf-8")
    assert "context: # <= 40 rendered lines" in planning
    assert "**Context-block discipline (<= 40 rendered lines).**" in workflow
    assert "`commit_message_conventions.change_record_content_rule`" in workflow


def test_critique_gate_convergence_is_finding_shaped() -> None:
    """The Step 9 convergence rule is finding-shaped, not a round count (rec-2944 / B3-R2/R3)."""
    planning = _PLANNING_SKILL.read_text(encoding="utf-8")
    assert "after 3 REVISE rounds" not in planning
    assert "Oscillation interrupts, not the count" in planning
    assert "recurring at a tag+anchor you recorded fixed" in planning
    assert "tagged findings first" in planning
    assert "starts a new series" in planning
    assert "Apply the Step 9 Convergence rule in kind" in planning


def test_critic_tags_every_finding_with_a_stable_anchor() -> None:
    """B3-R5: every finding carries a mechanical/judgement tag with a stable anchor grammar."""
    critique = _CRITIQUE_SKILL.read_text(encoding="utf-8")
    assert "tag each finding, with a stable anchor (plan field path or VP step id)" in critique
    assert "mechanical (a deterministic check could catch it -- name it)" in critique
    assert "tag each registration-closure finding" not in critique
    assert "mechanical (scripts.roadmap.plan_obligations)" not in critique


def test_implementation_branch_asks_the_split_question() -> None:
    """PDB-02: the IMPLEMENTATION branch asks the split question and names the deferred half's disposition."""
    critique = _CRITIQUE_SKILL.read_text(encoding="utf-8")
    assert "For IMPLEMENTATION: Are all scope entries necessary? Too large (suggest split)?" in critique
    assert "deferred half filed as a follow-on rec" in critique


def test_escalation_menu_is_identical_on_command_and_skill() -> None:
    """PDB-05: plan.md's Step 9 escalation menu is the planning skill's menu, verbatim."""
    planning = _PLANNING_SKILL.read_text(encoding="utf-8")
    plan_cmd = _PLAN_CMD.read_text(encoding="utf-8")
    menu = "accept-with-deferral / re-scope / split / abandon / one more round"
    assert menu in planning
    assert menu in plan_cmd


def test_data_quality_semantics_live_with_their_producer() -> None:
    """The two-layer DQ health picture relocates to its producer; planning/SKILL.md keeps only a pointer."""
    planning = _PLANNING_SKILL.read_text(encoding="utf-8")
    runner = _DQ_RUNNER.read_text(encoding="utf-8")
    assert "### What Data-Quality Health Represents" not in planning
    assert "checks_defined == 0" in planning
    assert "config/agent/data_quality/" in planning
    assert str(_DQ_RUNNER) in planning
    assert "Two-layer health picture" in runner
    assert "checks_defined > 0" in runner
    assert "last_run.verdict == PASS" in runner
