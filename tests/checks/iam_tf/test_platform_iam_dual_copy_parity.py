"""Transitional parity guard: while both terraform/personal and terraform/bootstrap declare the
seven PlatformDev/PlatformAdmin addresses (PLAN-platform-iam-bootstrap-adopt, rec-3838 plan 1 of
2), the two copies must agree on everything that governs live IAM.

Retired by the sibling plan (PLAN-platform-iam-personal-release) once terraform/personal stops
declaring the addresses -- this module's whole subject disappears with the personal copy, so it is
deleted rather than repointed.

Condition extraction is implemented locally (not imported from
scripts/checks/iam_tf/_read_coverage.py's _locate_policy_statement_array / _split_top_level_objects,
which are reused as-is) because that module's _parse_statement_array does not carry Condition.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.checks.iam_tf._read_coverage import _extract_bracket_block, _split_top_level_objects
from tests.checks.iam_tf._platform_security_hcl import _block_body, _mask, _resource_body, _strip_comments

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PERSONAL = _REPO_ROOT / "terraform" / "personal"
_BOOTSTRAP = _REPO_ROOT / "terraform" / "bootstrap"

# personal reference -> its bootstrap-copy equivalent literal text, for statement-shape comparison.
# Two forms per reference: BARE (the element's entire, unwrapped value -- no interpolation braces,
# used when the reference is the whole list element) and WRAPPED (inside a `${...}` interpolation
# embedded in a larger string, e.g. the ":*" suffix form) -- the wrapped form keeps its braces so
# `"${X}:*"` normalizes to the same text as bootstrap's own `"${local.Y}:*"` literal.
_BARE_SUBSTITUTIONS = [
    (re.compile(r"(?<!\$\{)\baws_s3_bucket\.data_lake\.arn\b(?!\s*\})"), "local.data_lake_bucket_arn"),
    (re.compile(r"(?<!\$\{)\baws_dynamodb_table\.counters\.arn\b(?!\s*\})"), "local.counters_table_arn"),
    (
        re.compile(r"(?<!\$\{)\baws_lambda_function\.ducklake_writer\.arn\b(?!\s*\})"),
        "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:${local.ducklake_writer_function}",
    ),
    (
        re.compile(r"(?<!\$\{)\baws_lambda_function\.ducklake_reader\.arn\b(?!\s*\})"),
        "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:${local.ducklake_reader_function}",
    ),
    (
        re.compile(r"(?<!data\.)\baws_secretsmanager_secret\.deepseek_api_key\.arn\b"),
        "data.aws_secretsmanager_secret.deepseek_api_key.arn",
    ),
    (
        re.compile(r"(?<!data\.)\baws_secretsmanager_secret\.anthropic_api_key\.arn\b"),
        "data.aws_secretsmanager_secret.anthropic_api_key.arn",
    ),
    (
        re.compile(r"(?<!data\.)\baws_secretsmanager_secret\.ducklake_neon_catalog_dsn\.arn\b"),
        "data.aws_secretsmanager_secret.ducklake_neon_catalog_dsn.arn",
    ),
]

_WRAPPED_SUBSTITUTIONS = [
    (re.compile(r"\$\{\s*aws_s3_bucket\.data_lake\.arn\s*\}"), "${local.data_lake_bucket_arn}"),
    (re.compile(r"\$\{\s*aws_dynamodb_table\.counters\.arn\s*\}"), "${local.counters_table_arn}"),
    (
        re.compile(r"\$\{\s*aws_lambda_function\.ducklake_writer\.arn\s*\}"),
        "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:${local.ducklake_writer_function}",
    ),
    (
        re.compile(r"\$\{\s*aws_lambda_function\.ducklake_reader\.arn\s*\}"),
        "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:${local.ducklake_reader_function}",
    ),
]

_TELEMETRY_WRITER = re.compile(
    r"arn:aws:lambda:\$\{var\.aws_region\}:\$\{var\.account_id\}:function:agent-platform-ducklake-telemetry-writer"
)
_TELEMETRY_WRITER_REPLACEMENT = (
    "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:${local.ducklake_telemetry_writer_function}"
)


def _normalize(raw: str) -> str:
    for pattern, replacement in _WRAPPED_SUBSTITUTIONS:
        raw = pattern.sub(replacement, raw)
    for pattern, replacement in _BARE_SUBSTITUTIONS:
        raw = pattern.sub(replacement, raw)
    raw = _TELEMETRY_WRITER.sub(_TELEMETRY_WRITER_REPLACEMENT, raw)
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    return re.sub(r"\s+", " ", raw).strip()


def _split_list_elements(bracket_body: str) -> list[str]:
    """Comma-separated elements of a `[...]` body, quoted or bare, trailing comma tolerated."""
    elements, depth, current = [], 0, ""
    in_string = False
    i = 0
    while i < len(bracket_body):
        c = bracket_body[i]
        if c == '"' and (i == 0 or bracket_body[i - 1] != "\\"):
            in_string = not in_string
            current += c
        elif not in_string and c in "[{(":
            depth += 1
            current += c
        elif not in_string and c in "]})":
            depth -= 1
            current += c
        elif not in_string and c == "," and depth == 0:
            elements.append(current.strip())
            current = ""
        else:
            current += c
        i += 1
    if current.strip():
        elements.append(current.strip())
    return elements


def _field_list(body: str, name: str) -> list[str] | None:
    m = re.search(rf"{name}\s*=\s*(\[[^\]]*\]|\"[^\"]*\")", body, re.M | re.S)
    if m is None:
        return None
    raw = m.group(1)
    if raw.startswith("["):
        return _split_list_elements(raw[1:-1])
    return [raw.strip('"')]


def _conditions(body: str) -> list[tuple[str, str, list[str]]]:
    head = re.search(r"\bCondition\s*=\s*\{", _mask(body))
    if head is None:
        return []
    inner = _block_body(body, head.end() - 1)
    out = []
    for op in re.finditer(r"(\w+)\s*=\s*\{", _mask(inner)):
        op_body = _block_body(inner, op.end() - 1)
        for key_m in re.finditer(r'"([^"]+)"\s*=\s*(\[[^\]]*\]|"[^"]*")', op_body):
            out.append((op.group(1), key_m.group(1), re.findall(r'"([^"]*)"', key_m.group(2))))
    return out


def _statements(text: str) -> dict[str, dict]:
    text = _strip_comments(text)
    out: dict[str, dict] = {}
    for head in re.finditer(r"\bStatement\s*=\s*\[", text):
        array = _extract_bracket_block(text, head.end() - 1)
        for obj in _split_top_level_objects(array):
            sid_m = re.search(r'Sid\s*=\s*"([^"]+)"', obj)
            if sid_m is None:
                continue
            out[sid_m.group(1)] = {
                "effect": (re.search(r'Effect\s*=\s*"([^"]+)"', obj) or re.match(r"()", "")).group(1)
                if re.search(r'Effect\s*=\s*"([^"]+)"', obj)
                else None,
                "actions": sorted(_normalize(a) for a in (_field_list(obj, "Action") or [])),
                "resources": sorted(_normalize(r) for r in (_field_list(obj, "Resource") or [])),
                "conditions": sorted(_conditions(obj)),
            }
    return out


def _policy_json_text(dir_texts: dict[str, str], local_name: str) -> str | None:
    for text in dir_texts.values():
        m = re.search(rf"\b{re.escape(local_name)}\s*=\s*jsonencode\s*\(\s*\{{", _strip_comments(text))
        if m is not None:
            return _block_body(text, m.end() - 1)
    return None


def _dir_texts(d: Path) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(d.glob("*.tf"))}


# (personal local name, bootstrap local name) for each of the five inline policies.
_POLICY_LOCALS = [
    ("platform_dev_runtime_policy_json", "platform_dev_runtime_policy_json"),
    ("platform_admin_ops_policy_json", "platform_admin_ops_policy_json"),
    ("", "platform_admin_datalake_policy_json"),  # personal declares this one inline, not hoisted
    ("", "platform_admin_bootstrap_state_policy_json"),
    ("", "platform_admin_ducklake_breakglass_policy_json"),
]


def statement_problems() -> list[str]:
    personal, bootstrap = _dir_texts(_PERSONAL), _dir_texts(_BOOTSTRAP)
    personal_text, bootstrap_text = "\n".join(personal.values()), "\n".join(bootstrap.values())
    problems: list[str] = []

    pairs = [
        ("DailyOps", "aws_iam_role_policy", "platform_dev_runtime", "platform_dev_runtime_policy_json"),
        ("AdminOps", "aws_iam_role_policy", "platform_admin_ops", "platform_admin_ops_policy_json"),
        (
            "PlatformDataLakeProvisioning",
            "aws_iam_role_policy",
            "platform_admin_datalake",
            "platform_admin_datalake_policy_json",
        ),
        (
            "BootstrapStateProvisioning",
            "aws_iam_role_policy",
            "platform_admin_bootstrap_state",
            "platform_admin_bootstrap_state_policy_json",
        ),
        (
            "DuckLakeBreakGlass",
            "aws_iam_role_policy",
            "platform_admin_ducklake_breakglass",
            "platform_admin_ducklake_breakglass_policy_json",
        ),
    ]
    for label, rtype, rname, local_name in pairs:
        p_body = _resource_body(personal_text, rtype, rname)
        b_body = _resource_body(bootstrap_text, rtype, rname)
        if p_body is None or b_body is None:
            problems.append(
                f"{label}: not declared in both roots (personal={p_body is not None}, bootstrap={b_body is not None})"
            )
            continue
        p_json = _policy_json_text(personal, local_name) if f"local.{local_name}" in p_body else p_body
        b_json = _policy_json_text(bootstrap, local_name) if f"local.{local_name}" in b_body else b_body
        if p_json is None or b_json is None:
            problems.append(f"{label}: could not locate its Statement array in one of the two roots")
            continue
        p_stmts, b_stmts = _statements(p_json), _statements(b_json)
        if set(p_stmts) != set(b_stmts):
            personal_only, bootstrap_only = set(p_stmts) - set(b_stmts), set(b_stmts) - set(p_stmts)
            problems.append(f"{label}: Sid sets differ (personal only: {personal_only}, bootstrap only: {bootstrap_only})")
            continue
        for sid, p_stmt in p_stmts.items():
            b_stmt = b_stmts[sid]
            if p_stmt != b_stmt:
                problems.append(f"{label} Sid {sid}: personal {p_stmt} != bootstrap {b_stmt}")
    return problems


def _role_scalar_problems() -> list[str]:
    personal_text, bootstrap_text = "\n".join(_dir_texts(_PERSONAL).values()), "\n".join(_dir_texts(_BOOTSTRAP).values())
    problems: list[str] = []
    for rname, role_label in (("platform_dev", "PlatformDev"), ("platform_admin", "PlatformAdmin")):
        p_body, b_body = (
            _resource_body(personal_text, "aws_iam_role", rname),
            _resource_body(bootstrap_text, "aws_iam_role", rname),
        )
        if p_body is None or b_body is None:
            problems.append(f"{role_label}: not declared in both roots")
            continue
        for attr in ("name", "description", "max_session_duration"):
            p_m = re.search(rf"^\s*{attr}\s*=\s*(.+?)\s*$", _strip_comments(p_body), re.M)
            b_m = re.search(rf"^\s*{attr}\s*=\s*(.+?)\s*$", _strip_comments(b_body), re.M)
            if (p_m and p_m.group(1)) != (b_m and b_m.group(1)):
                problems.append(
                    f"{role_label}.{attr}: personal {p_m and p_m.group(1)!r} != bootstrap {b_m and b_m.group(1)!r}"
                )
        p_boundary = "permissions_boundary" in _strip_comments(p_body)
        b_boundary = "permissions_boundary" in _strip_comments(b_body)
        if p_boundary != b_boundary:
            problems.append(
                f"{role_label}: permissions_boundary presence differs (personal={p_boundary}, bootstrap={b_boundary})"
            )

        for form, body in (("personal", p_body), ("bootstrap", b_body)):
            trust_m = re.search(r"assume_role_policy\s*=\s*jsonencode\s*\(\s*\{", _strip_comments(body))
            if trust_m is None:
                problems.append(f"{role_label} ({form}): no assume_role_policy found")
                continue
            trust_body = _block_body(body, trust_m.end() - 1)
            if "sts:AssumeRole" not in trust_body and "AssumeRole" not in trust_body:
                problems.append(f"{role_label} ({form}): trust statement does not grant sts:AssumeRole")
            ext_var = "platform_dev_external_id" if rname == "platform_dev" else "platform_admin_external_id"
            if f"var.{ext_var}" not in trust_body or "sts:ExternalId" not in trust_body:
                problems.append(
                    f"{role_label} ({form}): trust statement missing its sts:ExternalId condition on var.{ext_var}"
                )
    return problems


def _tag_problems() -> list[str]:
    personal_main = (_PERSONAL / "main.tf").read_text(encoding="utf-8")
    bootstrap_main = (_BOOTSTRAP / "main.tf").read_text(encoding="utf-8")
    personal_roles = "\n".join(_dir_texts(_PERSONAL).values())
    bootstrap_roles = "\n".join(_dir_texts(_BOOTSTRAP).values())

    def _default_tags(text: str) -> dict[str, str]:
        m = re.search(r"default_tags\s*\{\s*tags\s*=\s*\{", _strip_comments(text))
        if m is None:
            return {}
        body = _block_body(text, m.end() - 1)
        return {k: (f"var.{v}" if v else lit) for k, v, lit in re.findall(r'(\w+)\s*=\s*(?:var\.(\w+)|"([^"]*)")', body)}

    def _resource_tags(text: str, rname: str) -> dict[str, str]:
        body = _resource_body(text, "aws_iam_role", rname) or ""
        tags_m = re.search(r"\btags\s*=\s*\{", _strip_comments(body))
        if tags_m is None:
            return {}
        return dict(re.findall(r'(\w+)\s*=\s*"([^"]*)"', _block_body(body, tags_m.end() - 1)))

    problems: list[str] = []
    for rname, label in (("platform_dev", "PlatformDev"), ("platform_admin", "PlatformAdmin")):
        p_effective = {**_default_tags(personal_main), **_resource_tags(personal_roles, rname)}
        b_effective = {**_default_tags(bootstrap_main), **_resource_tags(bootstrap_roles, rname)}
        if p_effective != b_effective:
            problems.append(f"{label}: effective tag set differs -- personal {p_effective} != bootstrap {b_effective}")
    return problems


class TestDualCopyParity:
    def test_statements_match(self) -> None:
        assert statement_problems() == []

    def test_role_scalars_and_trust_shape_match(self) -> None:
        assert _role_scalar_problems() == []

    def test_effective_tags_match(self) -> None:
        assert _tag_problems() == []

    def test_resource_edit_is_detected(self) -> None:
        bootstrap = _dir_texts(_BOOTSTRAP)
        mutated_dev = bootstrap["platform_dev_policies.tf"].replace(
            'Resource = ["${local.data_lake_bucket_arn}/*"]', 'Resource = ["${local.data_lake_bucket_arn}/other/*"]', 1
        )
        assert mutated_dev != bootstrap["platform_dev_policies.tf"]
        personal_text = "\n".join(_dir_texts(_PERSONAL).values())
        mutated_bootstrap_text = "\n".join({**bootstrap, "platform_dev_policies.tf": mutated_dev}.values())
        p_stmts = _statements(_policy_json_text(_dir_texts(_PERSONAL), "platform_dev_runtime_policy_json") or personal_text)
        b_stmts = _statements(
            _block_body(
                mutated_bootstrap_text,
                re.search(r"platform_dev_runtime_policy_json\s*=\s*jsonencode\s*\(\s*\{", mutated_bootstrap_text).end() - 1,
            )
        )
        assert p_stmts["S3ReadWrite"] != b_stmts["S3ReadWrite"]

    def test_role_description_edit_is_detected(self) -> None:
        bootstrap_text = "\n".join(_dir_texts(_BOOTSTRAP).values())
        personal_text = "\n".join(_dir_texts(_PERSONAL).values())
        original_desc = 'description          = "Daily agent ops (runtime): S3 read/write on the data lake, '
        original_desc += 'DynamoDB counters, DuckLake verb invokes"'
        mutated = bootstrap_text.replace(original_desc, 'description          = "mutated"', 1)
        assert mutated != bootstrap_text
        p_body = _resource_body(personal_text, "aws_iam_role", "platform_dev")
        b_body = _resource_body(mutated, "aws_iam_role", "platform_dev")
        p_desc = re.search(r"description\s*=\s*(.+?)\s*$", _strip_comments(p_body), re.M).group(1)
        b_desc = re.search(r"description\s*=\s*(.+?)\s*$", _strip_comments(b_body), re.M).group(1)
        assert p_desc != b_desc
