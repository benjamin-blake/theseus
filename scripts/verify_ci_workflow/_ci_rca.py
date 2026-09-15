"""VP helper: the canary and ci-rca guards for the verify_ci_workflow package."""

from __future__ import annotations

import re
from pathlib import Path

from scripts.verify_ci_workflow._shared import _assert_runtime_lock, _get_step_run_text, _get_steps_text, _load


def _check_canary() -> None:
    data = _load(".github/workflows/main-canary.yml")

    assert data.get("name") == "Main Canary", f"main-canary.yml name is {data.get('name')!r}, expected 'Main Canary'"

    on = data.get("on", {})
    schedule = on.get("schedule", [])
    assert len(schedule) >= 1, "main-canary.yml has no schedule entries"
    assert schedule[0].get("cron") == "0 */3 * * *", f"canary cron is {schedule[0].get('cron')!r}, expected '0 */3 * * *'"
    assert "workflow_dispatch" in on, "main-canary.yml missing workflow_dispatch trigger"

    jobs = data.get("jobs", {})
    assert len(jobs) >= 1, "main-canary.yml has no jobs"
    canary_job = next(iter(jobs.values()))

    runs_on = canary_job.get("runs-on")
    assert runs_on == "ubuntu-latest", f"canary runs-on is {runs_on!r}, expected 'ubuntu-latest' (CD.21)"

    steps_text = _get_steps_text(canary_job)
    assert "scripts.validate" in steps_text, "canary steps do not reference scripts.validate"
    assert "--pre" not in steps_text, "canary steps contain --pre (should not)"
    _assert_runtime_lock(canary_job, "main-canary")


# PLAN-ci-rca-ops-plane-coverage: the required-membership floor for ci-rca.yml's
# workflow_run.workflows filter. "Main Canary" is resolved dynamically from main-canary.yml's own
# name field below rather than hardcoded here, so a canary rename does not desync the two checks.
# This is a FLOOR, not an exact-set assertion (growth beyond these entries is governed by the
# per-entry adjudication requirement in docs/contracts/ci-rca-lifecycle.yaml, not by this guard) --
# its job is only to prevent silent REMOVAL, per rec-2849 (terraform-apply-sandbox was in the
# filter but unguarded here, so the CD.35 wiring could have been deleted silently).
_REQUIRED_CI_RCA_WORKFLOWS = ("CI", "terraform-apply-sandbox", "rec-autoclose", "deploy-ducklake-lambdas")


def _check_ci_rca_filter() -> None:
    canary_data = _load(".github/workflows/main-canary.yml")
    canary_name = canary_data.get("name")
    assert canary_name, "main-canary.yml has no name field"

    rca_data = _load(".github/workflows/ci-rca.yml")
    on = rca_data.get("on", {})
    workflow_run = on.get("workflow_run", {})
    workflows = workflow_run.get("workflows", [])

    required = (*_REQUIRED_CI_RCA_WORKFLOWS, canary_name)
    missing = [w for w in required if w not in workflows]
    assert not missing, f"ci-rca.yml workflows list missing required entries {missing}: {workflows}"

    assert len(workflows) == len(set(workflows)), f"ci-rca.yml workflows list has duplicate entries: {workflows}"

    rca_job_if = rca_data.get("jobs", {}).get("rca", {}).get("if", "")
    assert "head_branch" in rca_job_if, (
        f"ci-rca.yml rca job if: missing main-branch gate (head_branch not found): {rca_job_if!r}"
    )
    assert "default_branch" in rca_job_if, (
        f"ci-rca.yml rca job if: missing main-branch gate (default_branch not found): {rca_job_if!r}"
    )

    agent_doc = Path(".claude/agents/scheduled/ci-rca.md").read_text(encoding="utf-8")
    assert "FILED:" in agent_doc, (
        ".claude/agents/scheduled/ci-rca.md missing FILED: marker contract -- "
        "the prompt rewrite plan must preserve this signal for the workflow parser"
    )


_PATTERN_MATCHING_CONSTRUCT_RE = re.compile(
    r"\bgrep\b|\begrep\b|\brg\b|\bawk\b|\bsed\b|\bcase\b|=~|\bpython[0-9.]*\s+-c\b",
    re.IGNORECASE,
)

_CI_RCA_FETCH_STEP = "      - name: Fetch failed run logs"


def _read_ci_rca_authority_sources() -> tuple[str, str]:
    return tuple(Path(path).read_text(encoding="utf-8") for path in (".github/workflows/ci-rca.yml", "docs/DECISIONS.md"))  # type: ignore[return-value]


def _ci_rca_fetch_source_comment(workflow_source: str) -> str:
    matches = re.findall(rf"((?:^      #.*\n)+)(?=^{re.escape(_CI_RCA_FETCH_STEP)}$)", workflow_source, re.MULTILINE)
    assert workflow_source.count(_CI_RCA_FETCH_STEP) == 1, "GAL-03: Fetch source anchor is missing or duplicated"
    assert len(matches) == 1, "GAL-03: Fetch anchor is missing, duplicated, or lacks immediately adjacent provenance"
    return matches[0]


def _decision_72_entry(decisions_source: str) -> str:
    headers = list(re.finditer(r"^## Decision (\d+):", decisions_source, re.MULTILINE))
    decision_72 = [match for match in headers if match.group(1) == "72"]
    assert len(decision_72) == 1, "GAL-03: docs/DECISIONS.md must contain exactly one well-formed Decision 72 H2 header"
    start = decision_72[0]
    end = next((match.start() for match in headers if match.start() > start.start()), None)
    assert end is not None, "GAL-03: Decision 72 entry has no following Decision H2 boundary"
    return decisions_source[start.start() : end]


def _check_ci_rca_authority_anchor() -> None:
    workflow_source, decisions_source = _read_ci_rca_authority_sources()
    comment = _ci_rca_fetch_source_comment(workflow_source)
    provenance = ("Decision 72 is provenance", "workflow_run-triggered CI-RCA failed-run log retrieval")
    assert all(fragment in comment for fragment in provenance), (
        "GAL-03: adjacent comment must identify Decision 72 only as CI-RCA failed-run log retrieval provenance"
    )
    assert all(fragment in comment for fragment in ("local", "YAML-side fail-closed guard")), (
        "GAL-03: adjacent comment must identify test -s as a local YAML-side fail-closed guard"
    )
    assert "Decision 143" not in comment, "GAL-03: adjacent comment retains the stale Decision 143 mitigation claim"
    assert "Decision 72 mitigation" not in comment and "Decision 72 guard" not in comment, (
        "GAL-03: adjacent comment must not claim Decision 72 owns the local guard"
    )

    authority = ("On CI failure", "`workflow_run`-triggered", ".github/workflows/ci-rca.yml", "failed run logs", "gh run view")
    missing = [fragment for fragment in authority if fragment not in _decision_72_entry(decisions_source)]
    assert not missing, f"GAL-03: bounded Decision 72 entry does not establish CI-RCA failed-run log retrieval: {missing}"


def _check_ci_rca_fetch_classification() -> None:
    """Reject pattern matching in the bounded failed-log retrieval step (rec-2857)."""
    _check_ci_rca_authority_anchor()
    data = _load(".github/workflows/ci-rca.yml")
    job = data.get("jobs", {}).get("rca", {})
    run_text = _get_step_run_text(job, "Fetch failed run logs")
    evidence_run_text = _get_step_run_text(job, "Generate evidence bundle")

    assert "scripts.ci_rca.fetch_logs" in run_text, "'Fetch failed run logs' step no longer invokes scripts.ci_rca.fetch_logs"
    assert "--out /tmp/ci-rca-log-evidence.json" in run_text, "GAL-01: fetch output is not the typed retrieval envelope"
    assert "scripts.ci_rca.log_evidence --validate" in run_text, "GAL-01: bounded retrieval envelope is not validated"
    assert "--extract-body /tmp/ci-rca-failed.log" in run_text, "GAL-01: agent log is not extracted from validated evidence"
    assert "test -s /tmp/ci-rca-log-evidence.json" in run_text, "GAL-01: retrieval envelope false-green guard is missing"
    assert "test -s /tmp/ci-rca-failed.log" in run_text, "GAL-01: extracted body false-green guard is missing"
    assert "--retrieval-envelope /tmp/ci-rca-log-evidence.json" in evidence_run_text, (
        "GAL-01: durable evidence generation does not consume the validated retrieval envelope"
    )
    assert "gh run view" not in run_text or "--log" not in run_text, (
        "GAL-01: workflow contains an uncapped direct log retrieval"
    )
    fetch_source = Path("scripts/ci_rca/fetch_logs.py").read_text(encoding="utf-8")
    for required in (
        "_run_log(primary_command, max_bytes, max_lines)",
        'remaining = max_bytes - len("".join(fragments).encode("utf-8"))',
        "remaining_lines = max_lines -",
        "_run_log(command, remaining, remaining_lines)",
        'selected.sort(key=lambda item: item["job_id"])',
    ):
        assert required in fetch_source, f"GAL-01: bounded retrieval invariant missing: {required}"

    match = _PATTERN_MATCHING_CONSTRUCT_RE.search(run_text)
    assert match is None, (
        f"'Fetch failed run logs' step run: body contains a pattern-matching construct "
        f"({match.group(0)!r}) -- the log-body content check must never be reintroduced (rec-2857)"
    )
