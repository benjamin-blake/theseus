"""rec-4044 acceptance: platform-security-heartbeat-canary is declared exactly as specified.

Pins terraform/bootstrap/platform_security_heartbeat_canary.tf (Decision 202 clause 5): a 5-minute
ENABLED EventBridge Scheduler beat in its own schedule group, driving a STANDARD one-Task Step
Functions state machine whose only call is iam:GetRole on its own execution role, through two
least-privilege, confused-deputy-conditioned, size-preconditioned IAM roles. Also pins the
canary's PlatformAdmin management grant (platform_security_admin_policy.tf), the heartbeat's
cadence relationship to the schedule, the heartbeat alarm's description and the two canary fixture
events. Every predicate returns a problem list, so each red case drives the real predicate.
"""

from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path
from typing import Callable

import pytest
import yaml

from scripts.checks.iam_tf import _read_coverage as rc
from tests.checks.iam_tf._platform_security_hcl import _attr, _local_string, _resource_body

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP_DIR = _REPO_ROOT / "terraform" / "bootstrap"
_CANARY_FILE = _BOOTSTRAP_DIR / "platform_security_heartbeat_canary.tf"
_ALARMS_FILE = _BOOTSTRAP_DIR / "platform_security_alarms.tf"
_ADMIN_FILE = _BOOTSTRAP_DIR / "platform_security_admin_policy.tf"
_FIXTURE_EVENTS = _REPO_ROOT / "tests" / "fixtures" / "platform_security_filter_events.yaml"

HEARTBEAT = "platform-security-iam-event-heartbeat"
TAMPER = "platform-security-detector-tamper"
CANARY_ROLE = "platform_security_heartbeat_canary"
SCHEDULER_ROLE = "platform_security_heartbeat_scheduler"
CANARY_STATE_MACHINE_ARN = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:platform-security-heartbeat-canary"
CANARY_SCHEDULE_GROUP_ARN = "arn:aws:scheduler:${var.aws_region}:${var.account_id}:schedule-group/platform-security-heartbeat"
CANARY_OWN_ROLE_ARN = "arn:aws:iam::${var.account_id}:role/platform-security-heartbeat-canary"
_ADMIN_TRAIL_SIX = (
    "cloudtrail:CreateTrail",
    "cloudtrail:UpdateTrail",
    "cloudtrail:PutEventSelectors",
    "cloudtrail:StartLogging",
    "cloudtrail:AddTags",
    "cloudtrail:RemoveTags",
)


def _canary() -> str:
    return _CANARY_FILE.read_text(encoding="utf-8")


def _alarms() -> str:
    return _ALARMS_FILE.read_text(encoding="utf-8")


def _admin() -> str:
    return _ADMIN_FILE.read_text(encoding="utf-8")


def _fixture() -> str:
    return _FIXTURE_EVENTS.read_text(encoding="utf-8")


def _sub(text: str, old: str, new: str, count: int = 1) -> str:
    assert old in text, f"mutation anchor {old!r} not found"
    return text.replace(old, new, count)


def _nested_block(body: str, name: str) -> str | None:
    m = re.search(rf"\b{name}\s*\{{", body)
    if m is None:
        return None
    depth, i = 0, m.end() - 1
    for i in range(m.end() - 1, len(body)):
        if body[i] == "{":
            depth += 1
        elif body[i] == "}":
            depth -= 1
            if depth == 0:
                return body[m.end() : i]
    return None


def _bracket_attr(body: str, name: str) -> str | None:
    m = re.search(rf"{name}\s*=\s*\[(.*?)\]", body, re.S)
    return None if m is None else m.group(1)


def _local_jsonencode_body(text: str, name: str) -> str | None:
    m = re.search(rf"\b{re.escape(name)}\s*=\s*jsonencode\(\s*\{{", text)
    if m is None:
        return None
    depth, i = 0, m.end() - 1
    for i in range(m.end() - 1, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[m.end() : i]
    return None


def _json_action_resource(body: str) -> tuple[str | None, str | None]:
    action_m = re.search(r'Action\s*=\s*"([^"]*)"', body)
    resource_m = re.search(r'Resource\s*=\s*"([^"]*)"', body)
    return (action_m.group(1) if action_m else None, resource_m.group(1) if resource_m else None)


def _canary_definition(canary_text: str) -> dict:
    m = re.search(r"<<-?(\w+)\s*\n(.*?)\n[ \t]*\1", canary_text, re.S)
    assert m is not None, "no heredoc definition found"
    return json.loads(textwrap.dedent(m.group(2)))


def _rate_seconds(expr: str) -> int | None:
    m = re.fullmatch(r"rate\((\d+)\s*(minute|minutes|hour|hours)\)", expr)
    if m is None:
        return None
    n = int(m.group(1))
    return n * 60 if m.group(2).startswith("minute") else n * 3600


def _schedule_basic_problems(sched_body: str) -> list[str]:
    problems: list[str] = []
    if (_attr(sched_body, "group_name") or "") != "aws_scheduler_schedule_group.platform_security_heartbeat.name":
        problems.append("schedule group_name is not the dedicated platform-security-heartbeat group")
    if (_attr(sched_body, "state") or "").strip('"') != "ENABLED":
        problems.append("schedule state is not ENABLED")
    ftw = _nested_block(sched_body, "flexible_time_window") or ""
    if (_attr(ftw, "mode") or "").strip('"') != "OFF":
        problems.append("flexible_time_window mode is not OFF")
    if (_attr(sched_body, "schedule_expression") or "").strip('"') != "rate(5 minutes)":
        problems.append("schedule_expression is not rate(5 minutes)")

    depends = _bracket_attr(sched_body, "depends_on") or ""
    for needed in (
        "aws_iam_role_policy.platform_security_heartbeat_canary",
        "aws_iam_role_policy.platform_security_heartbeat_scheduler",
    ):
        if needed not in depends:
            problems.append(f"schedule depends_on is missing {needed}")
    return problems


def _schedule_target_problems(sched_body: str) -> list[str]:
    problems: list[str] = []
    target = _nested_block(sched_body, "target") or ""
    if "aws_sfn_state_machine.platform_security_heartbeat_canary.arn" not in (_attr(target, "arn") or ""):
        problems.append("schedule target arn is not the canary state machine")
    if "aws_iam_role.platform_security_heartbeat_scheduler.arn" not in (_attr(target, "role_arn") or ""):
        problems.append("schedule target role_arn is not the scheduler role")

    retry = _nested_block(target, "retry_policy") or ""
    attempts = _attr(retry, "maximum_retry_attempts") or ""
    max_age = _attr(retry, "maximum_event_age_in_seconds") or ""
    if not attempts.isdigit() or int(attempts) > 2:
        problems.append(f"retry_policy maximum_retry_attempts {attempts!r} > 2")
    if not max_age.isdigit() or int(max_age) > 300:
        problems.append(f"retry_policy maximum_event_age_in_seconds {max_age!r} > 300")
    return problems


def _state_machine_shape_problems(sfn_body: str) -> list[str]:
    problems: list[str] = []
    if (_attr(sfn_body, "type") or "").strip('"') != "STANDARD":
        problems.append("state machine type is not STANDARD")
    if "aws_iam_role.platform_security_heartbeat_canary.arn" not in (_attr(sfn_body, "role_arn") or ""):
        problems.append("state machine role_arn is not the canary role")
    return problems


def _definition_problems(definition: dict) -> list[str]:
    problems: list[str] = []
    timeout = definition.get("TimeoutSeconds")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout > 60:
        problems.append(f"TimeoutSeconds {timeout!r} > 60")
    states = definition.get("States") or {}
    if len(states) != 1:
        problems.append(f"state machine has {len(states)} states (expected 1)")
        return problems
    (state,) = states.values()
    if state.get("Type") != "Task":
        problems.append("the one state is not a Task")
    if state.get("Resource") != "arn:aws:states:::aws-sdk:iam:getRole":
        problems.append(f"state Resource is {state.get('Resource')!r}, not the IAM getRole integration")
    if (state.get("Parameters") or {}).get("RoleName") != "platform-security-heartbeat-canary":
        problems.append("state Parameters.RoleName is not the canary role's own name")
    if "Retry" in state:
        problems.append("state carries a Retry")
    if "Catch" in state:
        problems.append("state carries a Catch")
    return problems


def canary_problems(canary_text: str) -> list[str]:
    addresses = {
        "aws_iam_role.platform_security_heartbeat_canary": _resource_body(canary_text, "aws_iam_role", CANARY_ROLE),
        "aws_iam_role_policy.platform_security_heartbeat_canary": _resource_body(
            canary_text, "aws_iam_role_policy", CANARY_ROLE
        ),
        "aws_iam_role.platform_security_heartbeat_scheduler": _resource_body(canary_text, "aws_iam_role", SCHEDULER_ROLE),
        "aws_iam_role_policy.platform_security_heartbeat_scheduler": _resource_body(
            canary_text, "aws_iam_role_policy", SCHEDULER_ROLE
        ),
        "aws_sfn_state_machine.platform_security_heartbeat_canary": _resource_body(
            canary_text, "aws_sfn_state_machine", CANARY_ROLE
        ),
        "aws_scheduler_schedule_group.platform_security_heartbeat": _resource_body(
            canary_text, "aws_scheduler_schedule_group", "platform_security_heartbeat"
        ),
        "aws_scheduler_schedule.platform_security_heartbeat_canary": _resource_body(
            canary_text, "aws_scheduler_schedule", CANARY_ROLE
        ),
    }
    problems = [f"{label} missing" for label, body in addresses.items() if body is None]
    if problems:
        return problems

    sched_body = addresses["aws_scheduler_schedule.platform_security_heartbeat_canary"] or ""
    sfn_body = addresses["aws_sfn_state_machine.platform_security_heartbeat_canary"] or ""
    problems += _schedule_basic_problems(sched_body)
    problems += _schedule_target_problems(sched_body)
    problems += _state_machine_shape_problems(sfn_body)

    try:
        definition = _canary_definition(canary_text)
    except (AssertionError, ValueError, json.JSONDecodeError) as exc:
        problems.append(f"state machine definition does not parse: {exc}")
        return problems
    problems += _definition_problems(definition)
    return problems


def role_problems(canary_text: str) -> list[str]:
    problems: list[str] = []
    trust_checks = (
        (CANARY_ROLE, "states.amazonaws.com", CANARY_STATE_MACHINE_ARN),
        (SCHEDULER_ROLE, "scheduler.amazonaws.com", CANARY_SCHEDULE_GROUP_ARN),
    )
    for rname, principal, source_arn in trust_checks:
        body = _resource_body(canary_text, "aws_iam_role", rname) or ""
        principals = set(re.findall(r'Service\s*=\s*"([^"]+)"', body))
        if principals != {principal}:
            problems.append(f"{rname} trust names principal(s) {sorted(principals)} != {{{principal!r}}}")
        if not re.search(r'"aws:SourceAccount"\s*=\s*var\.account_id\b', body):
            problems.append(f"{rname} trust lacks aws:SourceAccount = var.account_id")
        arn_m = re.search(r'"aws:SourceArn"\s*=\s*"([^"]*)"', body)
        if arn_m is None:
            problems.append(f"{rname} trust lacks aws:SourceArn")
        elif arn_m.group(1) != source_arn:
            problems.append(f"{rname} trust aws:SourceArn = {arn_m.group(1)!r} != {source_arn!r}")

    canary_json = _local_jsonencode_body(canary_text, "platform_security_heartbeat_canary_role_policy_json") or ""
    canary_action, canary_resource = _json_action_resource(canary_json)
    if canary_action != "iam:GetRole":
        problems.append(f"canary inline policy Action = {canary_action!r} != 'iam:GetRole'")
    if canary_resource != CANARY_OWN_ROLE_ARN:
        problems.append(f"canary inline policy Resource = {canary_resource!r} != its own role ARN template")

    scheduler_json = _local_jsonencode_body(canary_text, "platform_security_heartbeat_scheduler_role_policy_json") or ""
    scheduler_action, scheduler_resource = _json_action_resource(scheduler_json)
    if scheduler_action != "states:StartExecution":
        problems.append(f"scheduler inline policy Action = {scheduler_action!r} != 'states:StartExecution'")
    if scheduler_resource != CANARY_STATE_MACHINE_ARN:
        problems.append(f"scheduler inline policy Resource = {scheduler_resource!r} != the state machine ARN template")

    for rname in (CANARY_ROLE, SCHEDULER_ROLE):
        body = _resource_body(canary_text, "aws_iam_role_policy", rname) or ""
        if "<= 10240" not in body:
            problems.append(f"aws_iam_role_policy.{rname} lacks the 10,240 B size precondition")
    return problems


def cadence_problems(canary_text: str, alarms_text: str) -> list[str]:
    sched_body = _resource_body(canary_text, "aws_scheduler_schedule", CANARY_ROLE)
    heartbeat_body = _resource_body(alarms_text, "aws_cloudwatch_metric_alarm", "platform_security_iam_event_heartbeat")
    if sched_body is None or heartbeat_body is None:
        return ["cadence: schedule or heartbeat alarm resource missing"]
    expr = (_attr(sched_body, "schedule_expression") or "").strip('"')
    beat_seconds = _rate_seconds(expr)
    if not beat_seconds:
        return [f"cadence: unparsable schedule_expression {expr!r}"]
    period_raw = _attr(heartbeat_body, "period") or "0"
    period = int(period_raw) if period_raw.isdigit() else 0
    if period <= 0 or (period / beat_seconds) < 3:
        ratio = period / beat_seconds if beat_seconds else 0
        return [f"cadence: only {ratio:.1f} beats per heartbeat period (< 3)"]
    return []


def admin_grant_problems(admin_text: str) -> list[str]:
    stmts = rc._parse_managed_policy_statements(admin_text, "platform_security_admin")
    if not stmts:
        return ["platform-security-detector-admin policy statements not found"]
    problems: list[str] = []
    trail = [s for s in stmts if s.get("sid") == "PlatformSecurityTrailManage"]
    if not trail:
        problems.append("PlatformSecurityTrailManage Sid missing")
    elif tuple(trail[0].get("actions") or []) != _ADMIN_TRAIL_SIX:
        problems.append(f"PlatformSecurityTrailManage actions changed: {trail[0].get('actions')} != {_ADMIN_TRAIL_SIX}")

    heartbeat_sids = [s for s in stmts if (s.get("sid") or "").startswith("PlatformSecurityHeartbeat")]
    if not heartbeat_sids:
        problems.append("no PlatformSecurityHeartbeat* Sid found")
    for stmt in heartbeat_sids:
        sid = stmt.get("sid")
        for action in stmt.get("actions") or []:
            service, _, verb = action.partition(":")
            if service not in {"states", "scheduler"}:
                problems.append(f"{sid}: action {action} is not a states:/scheduler: verb")
            if verb.startswith("Delete") or action in {"*", "states:*", "scheduler:*"}:
                problems.append(f"{sid}: forbidden Delete verb or wildcard {action}")
        for raw in re.findall(r'"([^"]+)"', stmt.get("resources_raw") or ""):
            if "platform-security-" not in raw:
                problems.append(f"{sid}: resource {raw} is outside the platform-security-* family")
    return problems


def description_problems(alarms_text: str) -> list[str]:
    body = _resource_body(alarms_text, "aws_cloudwatch_metric_alarm", "platform_security_iam_event_heartbeat")
    if body is None:
        return ["heartbeat alarm resource missing"]
    raw = _attr(body, "alarm_description") or ""
    desc = raw[1:-1] if raw.startswith('"') and raw.endswith('"') else raw
    problems = []
    if "platform-security-heartbeat-canary" not in desc:
        problems.append("alarm_description does not name platform-security-heartbeat-canary")
    if "IncomingLogEvents" not in desc:
        problems.append("alarm_description does not name IncomingLogEvents")
    triage = _local_string(alarms_text, "platform_security_alarm_triage") or ""
    placeholder = "X" * 14
    rendered = desc.replace("${local.platform_security_alarm_triage}", triage).replace("${var.aws_region}", placeholder)
    if len(rendered) > 1024:
        problems.append(f"rendered alarm_description length {len(rendered)} > 1024")
    return problems


def fixture_canary_problems(fixture_text: str) -> list[str]:
    events = (yaml.safe_load(fixture_text) or {}).get("events") or []
    named = {e.get("name"): set(e.get("must_match") or []) for e in events}
    expected = {
        "heartbeat-canary-get-role": {HEARTBEAT},
        "heartbeat-canary-schedule-disable": {TAMPER},
    }
    problems = []
    for name, want in expected.items():
        got = named.get(name)
        if got is None:
            problems.append(f"fixture missing event {name}")
        elif got != want:
            problems.append(f"fixture event {name} must_match {sorted(got)} != {sorted(want)}")
    return problems


_HEREDOC_JSON = (
    '        "Resource": "arn:aws:states:::aws-sdk:iam:getRole",\n'
    '        "Parameters": {\n'
    '          "RoleName": "platform-security-heartbeat-canary"\n'
    "        },\n"
    '        "ResultPath": null,\n'
    '        "End": true\n'
    "      }\n"
    "    }\n"
)
_HEREDOC_TWO_STATES = (
    '        "Resource": "arn:aws:states:::aws-sdk:iam:getRole",\n'
    '        "Parameters": {\n'
    '          "RoleName": "platform-security-heartbeat-canary"\n'
    "        },\n"
    '        "ResultPath": null,\n'
    '        "End": true\n'
    "      },\n"
    '      "Second": {\n'
    '        "Type": "Pass",\n'
    '        "End": true\n'
    "      }\n"
    "    }\n"
)
_HEREDOC_RETRY = (
    '        "Resource": "arn:aws:states:::aws-sdk:iam:getRole",\n'
    '        "Parameters": {\n'
    '          "RoleName": "platform-security-heartbeat-canary"\n'
    "        },\n"
    '        "ResultPath": null,\n'
    '        "Retry": [{"ErrorEquals": ["States.ALL"], "MaxAttempts": 1}],\n'
    '        "End": true\n'
    "      }\n"
    "    }\n"
)

_RED_CASES: dict[str, Callable[[], list[str]]] = {
    "schedule depends_on dropped": lambda: canary_problems(
        _sub(
            _canary(),
            "  depends_on = [\n"
            "    aws_iam_role_policy.platform_security_heartbeat_canary,\n"
            "    aws_iam_role_policy.platform_security_heartbeat_scheduler,\n"
            "  ]\n",
            "",
        )
    ),
    "schedule disabled": lambda: canary_problems(
        _sub(_canary(), 'state               = "ENABLED"', 'state               = "DISABLED"')
    ),
    "schedule in the default group": lambda: canary_problems(
        _sub(_canary(), "  group_name = aws_scheduler_schedule_group.platform_security_heartbeat.name\n", "")
    ),
    "state machine role_arn pointing at the scheduler role": lambda: canary_problems(
        _sub(
            _canary(),
            "  role_arn   = aws_iam_role.platform_security_heartbeat_canary.arn",
            "  role_arn   = aws_iam_role.platform_security_heartbeat_scheduler.arn",
        )
    ),
    "scheduler trust SourceArn on a schedule/ ARN": lambda: role_problems(
        _sub(
            _canary(),
            "arn:aws:scheduler:${var.aws_region}:${var.account_id}:schedule-group/platform-security-heartbeat",
            "arn:aws:scheduler:${var.aws_region}:${var.account_id}:schedule/platform-security-heartbeat/platform-security-heartbeat-canary",
        )
    ),
    "flexible window": lambda: canary_problems(_sub(_canary(), 'mode = "OFF"', 'mode = "ON"')),
    "slow beat rate(60 minutes) (cadence)": lambda: cadence_problems(
        _sub(_canary(), 'schedule_expression = "rate(5 minutes)"', 'schedule_expression = "rate(60 minutes)"'), _alarms()
    ),
    "sts instead of iam": lambda: canary_problems(
        _sub(_canary(), '"arn:aws:states:::aws-sdk:iam:getRole"', '"arn:aws:states:::aws-sdk:sts:getCallerIdentity"')
    ),
    "iam write task": lambda: canary_problems(
        _sub(_canary(), '"arn:aws:states:::aws-sdk:iam:getRole"', '"arn:aws:states:::aws-sdk:iam:tagRole"')
    ),
    "a second state": lambda: canary_problems(_sub(_canary(), _HEREDOC_JSON, _HEREDOC_TWO_STATES)),
    "Retry added": lambda: canary_problems(_sub(_canary(), _HEREDOC_JSON, _HEREDOC_RETRY)),
    "EXPRESS type": lambda: canary_problems(_sub(_canary(), 'type       = "STANDARD"', 'type       = "EXPRESS"')),
    "canary policy iam:*": lambda: role_problems(_sub(_canary(), 'Action   = "iam:GetRole"', 'Action   = "iam:*"')),
    "canary policy Resource *": lambda: role_problems(_sub(_canary(), CANARY_OWN_ROLE_ARN, "*")),
    "scheduler policy extra verb": lambda: role_problems(
        _sub(
            _canary(),
            'Action   = "states:StartExecution"',
            'Action   = ["states:StartExecution", "states:DescribeStateMachine"]',
        )
    ),
    "trust without aws:SourceArn": lambda: role_problems(
        _sub(
            _canary(),
            f'          ArnLike      = {{ "aws:SourceArn" = "{CANARY_STATE_MACHINE_ARN}" }}\n',
            "",
        )
    ),
    "trust principal *": lambda: role_problems(
        _sub(_canary(), 'Principal = { Service = "states.amazonaws.com" }', 'Principal = "*"')
    ),
    "admin grant Delete verb": lambda: admin_grant_problems(
        _sub(_admin(), '"states:CreateStateMachine",', '"states:CreateStateMachine",\n          "states:DeleteStateMachine",')
    ),
    "admin grant outside the family": lambda: admin_grant_problems(
        _sub(
            _admin(),
            'Resource = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:platform-security-*"',
            'Resource = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:*"',
        )
    ),
    "description without the canary": lambda: description_problems(
        _sub(_alarms(), "platform-security-heartbeat-canary schedule and its Step Functions executions", "the canary")
    ),
    "fixture canary GetRole also matching tamper": lambda: fixture_canary_problems(
        _sub(
            _fixture(),
            f"  - name: heartbeat-canary-get-role\n    must_match: [{HEARTBEAT}]",
            f"  - name: heartbeat-canary-get-role\n    must_match: [{HEARTBEAT}, {TAMPER}]",
        )
    ),
}


class TestPlatformSecurityHeartbeatCanary:
    def test_canary(self) -> None:
        assert canary_problems(_canary()) == []

    def test_roles(self) -> None:
        assert role_problems(_canary()) == []

    def test_cadence(self) -> None:
        assert cadence_problems(_canary(), _alarms()) == []

    def test_admin_grant(self) -> None:
        assert admin_grant_problems(_admin()) == []

    def test_description(self) -> None:
        assert description_problems(_alarms()) == []

    def test_fixture_canary(self) -> None:
        assert fixture_canary_problems(_fixture()) == []

    @pytest.mark.parametrize("label", sorted(_RED_CASES))
    def test_red_case(self, label: str) -> None:
        assert _RED_CASES[label]() != [], f"red case {label!r} was not detected"
