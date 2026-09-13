"""CI-RCA per-workflow adjudication guard (Decision 60)."""

from __future__ import annotations

from pathlib import Path

from scripts.checks import registry

_VALID_CI_RCA_VALUES = ("watched", "excluded")


def _check_workflow_coverage(workflows_map: dict[str, object], actual_names: set[str]) -> list[str]:
    """Assertion group (a): the taxonomy's declared name set equals the real workflow name set,
    in both directions."""
    failures: list[str] = []
    declared_names = set(workflows_map)

    for n in sorted(actual_names - declared_names):
        failures.append(f"CI-RCA adjudication: workflow {n!r} is absent from workflows in config/ci_rca_taxonomy.yaml")
    for n in sorted(declared_names - actual_names):
        failures.append(f"CI-RCA adjudication: taxonomy entry {n!r} names no .github/workflows/*.yml file (stale entry)")
    return failures


def _check_entry_shape(entry: object, name: str, watched: set[str]) -> list[str]:
    """Assertion group (c) for a single entry: valid ci_rca, non-empty owner, non-empty rationale.
    Adds `name` to `watched` (in place) when ci_rca == 'watched'."""
    if not isinstance(entry, dict):
        return [f"CI-RCA adjudication: workflow {name!r} entry is not a mapping (owner/ci_rca/rationale)"]

    failures: list[str] = []
    ci_rca = entry.get("ci_rca")
    owner = entry.get("owner")
    rationale = entry.get("rationale")

    if ci_rca not in _VALID_CI_RCA_VALUES:
        failures.append(
            f"CI-RCA adjudication: workflow {name!r} declares ci_rca={ci_rca!r}, must be one of {_VALID_CI_RCA_VALUES}"
        )
    elif ci_rca == "watched":
        watched.add(name)
    if not isinstance(owner, str) or not owner.strip():
        failures.append(f"CI-RCA adjudication: workflow {name!r} is missing a non-empty owner")
    if not isinstance(rationale, str) or not rationale.strip():
        failures.append(f"CI-RCA adjudication: workflow {name!r} is missing a non-empty rationale")
    return failures


def _load_ci_rca_filter(ci_rca_yml_path) -> tuple[set[str] | None, str | None]:  # noqa: ANN001
    """Read ci-rca.yml's on.workflow_run.workflows filter. Returns (filter_set, error)."""
    import yaml  # noqa: PLC0415

    try:
        ci_rca_yml = yaml.safe_load(ci_rca_yml_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return None, f"CI-RCA adjudication: could not read/parse {ci_rca_yml_path}: {exc}"

    on_block = ci_rca_yml.get(True, ci_rca_yml.get("on", {})) if isinstance(ci_rca_yml, dict) else {}
    filter_list = (on_block or {}).get("workflow_run", {}).get("workflows", [])
    return set(filter_list), None


def _check_filter_equals_watched(filter_set: set[str], watched: set[str]) -> list[str]:
    """Assertion group (b): ci-rca.yml's runtime filter equals the watched set, both directions."""
    failures: list[str] = []
    for n in sorted(filter_set - watched):
        failures.append(f"CI-RCA adjudication: ci-rca.yml's workflow_run filter names {n!r}, which is not ci_rca: watched")
    for n in sorted(watched - filter_set):
        failures.append(f"CI-RCA adjudication: {n!r} is ci_rca: watched but absent from ci-rca.yml's workflow_run filter")
    return failures


def _check_agent_loop_caps(workflows_map: dict[str, object], root: Path) -> tuple[list[str], int]:
    """Assertion group (d): each workflow row's optional agent_loop_caps list, resolved to its
    file through enumerate_workflow_name_paths (the row key already is the site -- no site or
    pattern is ever named in the row itself), shape-and-floor validated, then derived-and-asserted
    against the live workflow-region cap census. Returns (failures, examined_count)."""
    from scripts.checks.ci_guards._agent_loop_caps import check_cap_entry_shape, compare_caps, scan_cap_literals
    from scripts.ci_rca.taxonomy import enumerate_workflow_name_paths

    failures: list[str] = []
    declared: dict[str, dict[str, int]] = {}
    examined = 0

    name_to_path = dict(enumerate_workflow_name_paths())
    for row_name, entry in workflows_map.items():
        # Guarded upstream by group (c)'s own shape check (returns before this group runs on a
        # non-mapping entry); re-checked here only for mypy's narrowing, never expected to skip.
        if not isinstance(entry, dict):
            continue
        caps = entry.get("agent_loop_caps")
        if caps is None:
            continue
        if not isinstance(caps, list):
            failures.append(f"agent-loop cap (workflow): {row_name!r} agent_loop_caps must be a list")
            continue
        wf_path = name_to_path.get(row_name)
        if wf_path is None:
            # Guarded upstream by group (a)'s coverage check; defensive only.
            failures.append(f"agent-loop cap (workflow): {row_name!r} does not resolve to a workflow file")
            continue
        rel = wf_path.relative_to(root).as_posix()
        for cap in caps:
            examined += 1
            shape_failures, kind, value = check_cap_entry_shape(cap, context=f"workflow {row_name!r}")
            failures.extend(shape_failures)
            if shape_failures:
                continue
            assert kind is not None and value is not None  # guaranteed by check_cap_entry_shape's own contract
            declared.setdefault(rel, {})[kind] = value

    discovered, scan_errors = scan_cap_literals(root)
    failures.extend(scan_errors)
    workflow_discovered = {f: kinds for f, kinds in discovered.items() if f.startswith(".github/workflows/")}
    failures.extend(compare_caps(declared, workflow_discovered, "workflow"))

    return failures, examined


@registry.register("validate_ci_rca_adjudication", owner="platform")
def validate_ci_rca_adjudication(failed: list[str]) -> None:
    """Fail unless every workflow is adjudicated and the ci-rca.yml filter matches the watched set.

    Four assertion groups, all against config/ci_rca_taxonomy.yaml's `workflows:` map:
    (a) the map's key set equals .github/workflows/*.yml display names, in both directions;
    (b) .github/workflows/ci-rca.yml's on.workflow_run.workflows list equals exactly the entries
        marked ci_rca: watched, in both directions;
    (c) every entry declares a valid ci_rca value, a non-empty owner, and a non-empty rationale;
    (d) every entry's optional agent_loop_caps list is shape-valid and DERIVED-AND-ASSERTED equal
        to the live workflow-region agent-loop cap census (scripts/checks/ci_guards/
        _agent_loop_caps.py), in both directions -- see docs/plans/PLAN-declared-caps.yaml.

    Pure file-glob + YAML parse (no subprocess, no network); --pre eligible (Decision 60).

    Decision 170 accounting: this check was a baselined, undeclared entry in
    config/check_accounting_baseline.yaml until this plan's edit made adoption mandatory
    (touch-it-fix-it). All four groups' existing early returns append to `failed` first, so no
    early-return path is observable as vacuous or undeclared; one registry.examined() on the
    single non-failing exit, aggregating all four groups' counts, covers every reachable outcome.
    """
    from scripts.ci_rca.taxonomy import ROOT, enumerate_workflow_names, load_taxonomy  # noqa: PLC0415

    print("\n=== CI-RCA per-workflow adjudication ===")

    try:
        taxonomy = load_taxonomy()
    except (FileNotFoundError, ValueError) as exc:
        failed.append(f"CI-RCA adjudication: {exc}")
        return

    workflows_map: dict[str, object] = taxonomy.get("workflows") or {}
    actual_names = set(enumerate_workflow_names())

    coverage_failures = _check_workflow_coverage(workflows_map, actual_names)
    failed.extend(coverage_failures)
    if coverage_failures:
        return

    watched: set[str] = set()
    shape_failures: list[str] = []
    for name, entry in workflows_map.items():
        shape_failures.extend(_check_entry_shape(entry, name, watched))
    failed.extend(shape_failures)
    if shape_failures:
        return

    filter_set, load_error = _load_ci_rca_filter(ROOT / ".github" / "workflows" / "ci-rca.yml")
    if filter_set is None:
        failed.append(load_error or "CI-RCA adjudication: could not load ci-rca.yml's workflow_run filter")
        return

    filter_failures = _check_filter_equals_watched(filter_set, watched)
    failed.extend(filter_failures)

    cap_failures, cap_examined = _check_agent_loop_caps(workflows_map, ROOT)
    failed.extend(cap_failures)

    total_examined = len(actual_names) + len(filter_set | watched) + len(workflows_map) + cap_examined
    registry.examined(total_examined, unit="adjudication_assertions")

    if not filter_failures and not cap_failures:
        print(f"All {len(actual_names)} workflow(s) adjudicated; filter == watched set ({len(watched)} entries).")
