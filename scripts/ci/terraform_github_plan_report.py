#!/usr/bin/env python3
"""PR-time terraform/github plan reporter (rec-4335).

Reads `terraform show -json` output and a visibility probe file, and writes a markdown report of counts,
actions and changed attribute NAMES to stdout. It never prints a value from the plan. Stdlib only, invoked by
path with python3 from .github/workflows/terraform-github-plan.yml.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RULESET_TYPE = "github_repository_ruleset"
BYPASS = "bypass_actors"
FIELDS = ("security_and_analysis", "ruleset_bypass_actors")


@dataclass
class Row:
    address: str
    actions: list[str]
    changed: list[str]
    gated: bool = False


@dataclass
class Report:
    rows: list[Row] = field(default_factory=list)
    drift: list[str] = field(default_factory=list)
    visibility: dict[str, str] = field(default_factory=dict)
    imports: int = 0
    add: int = 0
    change: int = 0
    destroy: int = 0
    replace: int = 0
    conflict: bool = False

    @property
    def gated(self) -> int:
        return sum(1 for r in self.rows if r.gated)

    @property
    def verdict(self) -> str:
        if not self.rows:
            return "NO_CHANGES"
        if all(r.gated for r in self.rows):
            return "VISIBILITY_GATED_ONLY"
        return "CHANGES"

    @property
    def destructive(self) -> bool:
        return self.destroy + self.replace > 0


def load_visibility(path: str | Path | None) -> dict[str, str]:
    raw: Any = {}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    out: dict[str, str] = {}
    for key in FIELDS:
        val = raw.get(key)
        out[key] = "hidden" if val == "false" else "visible" if val == "true" else "unknown"
    return out


def _has_true(node: Any) -> bool:
    if node is True:
        return True
    if isinstance(node, dict):
        return any(_has_true(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_true(v) for v in node)
    return False


def _changed_names(change: dict[str, Any]) -> list[str]:
    before = change.get("before") or {}
    after = change.get("after") or {}
    unknown = change.get("after_unknown") or {}
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    unknown = unknown if isinstance(unknown, dict) else {}
    names = set()
    for key in set(before) | set(after) | set(unknown):
        if before.get(key) != after.get(key) or _has_true(unknown.get(key)):
            names.add(key)
    return sorted(names)


def classify(plan: dict[str, Any], visibility: dict[str, str]) -> Report:
    rep = Report(visibility=dict(visibility))
    bypass_vis = visibility.get("ruleset_bypass_actors", "unknown")
    for rc in plan.get("resource_changes") or []:
        if rc.get("mode") == "data":
            continue
        change = rc.get("change") or {}
        actions = list(change.get("actions") or [])
        importing = bool(change.get("importing"))
        if importing:
            rep.imports += 1
        elif actions in (["no-op"], ["read"], []):
            continue
        elif actions == ["create"]:
            rep.add += 1
        elif actions == ["update"]:
            rep.change += 1
        elif actions == ["delete"]:
            rep.destroy += 1
        elif sorted(actions) == ["create", "delete"]:
            rep.replace += 1
            rep.add += 1
            rep.destroy += 1
        names = _changed_names(change)
        bypass_only = (
            rc.get("type") == RULESET_TYPE
            and actions == ["update"]
            and not importing
            and names == [BYPASS]
            and (change.get("before") or {}).get(BYPASS) in (None, [])
        )
        gated = bypass_only and bypass_vis == "hidden"
        if bypass_only and bypass_vis == "visible":
            rep.conflict = True
        rep.rows.append(Row(str(rc.get("address", "")), actions, names, gated))
    rep.rows.sort(key=lambda r: r.address)
    rep.drift = sorted(str(d.get("address", "")) for d in plan.get("resource_drift") or [])
    return rep


def render(report: Report, head_sha: str, run_url: str, plan_exit_code: int | str) -> str:
    vis = report.visibility
    lines = [
        "### terraform/github PR-time plan (rec-4335)",
        f"PR head `{head_sha}` - [run]({run_url}) - read-only and advisory: it never applies.",
        (
            f"**{report.verdict}**: {report.imports} to import, {report.add} to add, {report.change} to change, "
            f"{report.destroy} to destroy ({report.replace} replaced, {report.gated} visibility-gated, "
            f"{len(report.drift)} drifted; terraform exit {plan_exit_code})"
        ),
        (
            f"VISIBILITY: security_and_analysis={vis.get('security_and_analysis', 'unknown')} "
            f"ruleset_bypass_actors={vis.get('ruleset_bypass_actors', 'unknown')}"
        ),
    ]
    if vis.get("security_and_analysis") != "visible":
        lines.append(
            "Secret-scanning fields are UNVERIFIED by this plan (the App cannot read them); "
            "ghas-probe.yml is the live control."
        )
    if report.gated:
        lines.append(
            "Visibility-gated rows change only a field the App cannot read; the operator's own plan is authoritative "
            "for it (github-org-transfer.yaml breakage_map.terraform_github_root)."
        )
    if report.conflict:
        lines.append(
            "VISIBILITY CONFLICT: the probe reports bypass_actors visible but the refreshed state has none; its "
            "visibility is UNPROVEN and this run proves nothing about it."
        )
    if report.destructive:
        lines.append("DESTROY OR REPLACE present: this job fails; do not apply without reading this.")
    if report.rows:
        lines += ["", "| Resource | Action | Changed attributes |", "|---|---|---|"]
        for r in report.rows:
            mark = " (visibility-gated)" if r.gated else ""
            lines.append(f"| {r.address}{mark} | {','.join(r.actions)} | {', '.join(r.changed)} |")
    else:
        lines += ["", "No changes."]
    if report.drift:
        lines += ["", "Drift detected outside Terraform: " + ", ".join(f"`{a}`" for a in report.drift)]
    lines.append(
        f"TF_GITHUB_PLAN_REPORT verdict={report.verdict} import={report.imports} add={report.add} "
        f"change={report.change} destroy={report.destroy} replace={report.replace} gated={report.gated} "
        f"drift={len(report.drift)} conflict={1 if report.conflict else 0} exit={plan_exit_code}"
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-json", required=True)
    ap.add_argument("--visibility", required=True)
    ap.add_argument("--plan-exit-code", required=True, choices=["0", "2"])
    ap.add_argument("--head-sha", required=True)
    ap.add_argument("--run-url", required=True)
    ap.add_argument("--github-output")
    args = ap.parse_args(argv)
    try:
        plan = json.loads(Path(args.plan_json).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        plan = None
    if not isinstance(plan, dict) or not isinstance(plan.get("resource_changes"), list):
        print("terraform_github_plan_report: plan JSON missing, unreadable or malformed", file=sys.stderr)
        return 2
    report = classify(plan, load_visibility(args.visibility))
    sys.stdout.write(render(report, args.head_sha, args.run_url, args.plan_exit_code))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as fh:
            fh.write(
                f"verdict={report.verdict}\ndestructive={str(report.destructive).lower()}\n"
                f"conflict={str(report.conflict).lower()}\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
