"""Standing guard for the telemetry writer infrastructure (PLAN-telemetry-writer-infra, then PLAN-telemetry-writer-function).

Pins, over the real terraform/personal tree: the telemetry catalog env on the telemetry writer and the reader (isolated
ducklake_smoke catalog until a Decision moves it, slice 2c), the telemetry-writer-only catalog-scoped blob root, the
telemetry writer's blob grant (Get/Put on the fenced root plus a prefix-conditioned List, never a delete), the reader's lack
of any blob grant, the untouched ops catalog env on the shared writer and reader, the shared writer's lack of any telemetry
state, the telemetry writer's scoped catalog login and its distance from the production ducklake/ prefix, and the
telemetry-blobs lifecycle rule. Every predicate is a pure function of HCL text with its own red case on synthetic HCL.
"""

from __future__ import annotations

import json
import re
from fnmatch import fnmatchcase

import pytest

from tests.fixtures.terraform_hcl_blocks import (
    _TERRAFORM_PERSONAL_DIR,
    assert_every_rule_enabled,
    find_resource_block,
    split_rule_blocks,
    tf_dir_file_texts,
)

_BUCKET = "probe-bucket"
_ARN = f"arn:aws:s3:::{_BUCKET}"
_PROBE_KEY = f"{_ARN}/telemetry-blobs/ducklake_smoke/probe-key"
_PROD_KEY = f"{_ARN}/ducklake/probe-key"
_PROD_LIST_PROBE = "ducklake/probe-key"
_SCOPED_SECRET = "aws_secretsmanager_secret.ducklake_telemetry_writer_dsn"  # pragma: allowlist secret
_DELETE_ACTIONS = ("s3:deleteobject", "s3:deleteobjectversion")
_OPS_FUNCTIONS = ("ducklake_writer", "ducklake_reader")
_TELEMETRY = "ducklake_telemetry_writer"
_PIN_FUNCTIONS = (_TELEMETRY, "ducklake_reader")
_DELETE_ROLES = (*_OPS_FUNCTIONS, _TELEMETRY)
_PIN_MOVE_HINT = "the telemetry catalog pin moves only with a Decision (slice 2c), then edit this guard"
_FIELD_SEMANTICS = '"/var/task/config/lambda/ducklake/field_semantics.yaml"'
_RULE_ID = "telemetry-blobs-noncurrent-reclaim"


def _brace_slice(text: str, open_idx: int) -> str:
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx : i + 1]
    raise AssertionError("unbalanced braces")


def _locals(text: str) -> dict[str, str]:
    m = re.search(r"\blocals\s*\{", text)
    assert m is not None, "no locals block"
    body = _brace_slice(text, m.end() - 1)
    return dict(re.findall(r'^\s*(\w+)\s*=\s*"([^"]*)"', body, re.MULTILINE))


def _resolve(token: str, locs: dict[str, str]) -> str:
    token = token.strip()
    if token.startswith('"') and token.endswith('"'):
        token = token[1:-1]
    elif token == "aws_s3_bucket.data_lake.arn":
        return _ARN
    token = token.replace("${aws_s3_bucket.data_lake.arn}", _ARN).replace("${aws_s3_bucket.data_lake.bucket}", _BUCKET)
    return re.sub(r"\$\{local\.(\w+)\}", lambda m: _resolve(f'"{locs[m.group(1)]}"', locs), token)


def _items(raw: str, locs: dict[str, str]) -> list[str]:
    raw = raw.strip()
    if raw.startswith("["):
        raw = raw[1:-1]
        return [_resolve(i, locs) for i in raw.split(",") if i.strip()]
    return [_resolve(raw, locs)]


def _env(text: str, function: str) -> dict[str, str]:
    block = find_resource_block(text, "aws_lambda_function", function)
    m = re.search(r"variables\s*=\s*\{([^}]*)\}", block)
    assert m is not None, f"{function} has no environment variables block"
    return dict(re.findall(r"^\s*([A-Z_]+)\s*=\s*(.+?)\s*$", m.group(1), re.MULTILINE))


def _statements(policy_block: str, locs: dict[str, str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for m in re.finditer(r'\bSid\s*=\s*"(\w+)"', policy_block):
        stmt = _brace_slice(policy_block, policy_block.rfind("{", 0, m.start()))
        action = re.search(r"\b(Action|NotAction)\s*=\s*(\[[^\]]*\]|\"[^\"]*\")", stmt)
        resource = re.search(r"\bResource\s*=\s*(\[[^\]]*\]|\"[^\"]*\"|[\w.]+)", stmt)
        prefix = re.search(r'"s3:prefix"\s*=\s*(\[[^\]]*\])', stmt)
        effect = re.search(r'\bEffect\s*=\s*"(\w+)"', stmt)
        out[m.group(1)] = {
            "effect": effect.group(1) if effect else "",
            "not_action": bool(action and action.group(1) == "NotAction"),
            "actions": _items(action.group(2), locs) if action else [],
            "resources": _items(resource.group(1), locs) if resource else [],
            "prefixes": _items(prefix.group(1), locs) if prefix else [],
        }
    return out


def _role_statements(text: str, role: str) -> dict[str, dict]:
    return _statements(find_resource_block(text, "aws_iam_role_policy", role), _locals(text))


def assert_pins_target_smoke(text: str) -> None:
    locs = _locals(text)
    assert locs.get("ducklake_telemetry_meta_schema") == "ducklake_smoke", f"meta schema local moved: {_PIN_MOVE_HINT}"
    for fn in _PIN_FUNCTIONS:
        env = _env(text, fn)
        assert env.get("TELEMETRY_META_SCHEMA") == "local.ducklake_telemetry_meta_schema", (
            f"{fn} TELEMETRY_META_SCHEMA is {env.get('TELEMETRY_META_SCHEMA')!r}: {_PIN_MOVE_HINT}"
        )
        assert env.get("TELEMETRY_DATA_PATH") == "local.ducklake_smoke_data_path", (
            f"{fn} TELEMETRY_DATA_PATH is {env.get('TELEMETRY_DATA_PATH')!r}: {_PIN_MOVE_HINT}"
        )


def assert_blob_root_only_on_writer(text: str) -> None:
    locs = _locals(text)
    assert _env(text, _TELEMETRY).get("TELEMETRY_BLOB_ROOT") == "local.ducklake_telemetry_blob_root", (
        "telemetry writer TELEMETRY_BLOB_ROOT must be local.ducklake_telemetry_blob_root"
    )
    root = _resolve('"${local.ducklake_telemetry_blob_root}"', locs)
    expected = f"s3://{_BUCKET}/telemetry-blobs/{locs.get('ducklake_telemetry_meta_schema')}/"
    assert root == expected, f"blob root {root!r} must be catalog-scoped ({expected!r}): {_PIN_MOVE_HINT}"
    for fn in ("ducklake_reader", "ducklake_writer"):
        assert "TELEMETRY_BLOB_ROOT" not in _env(text, fn), f"{fn} must not carry a blob root"


def assert_no_delete_on_prefix(text: str) -> None:
    for role in _DELETE_ROLES:
        for sid, s in _role_statements(text, role).items():
            if s["effect"] != "Allow":
                continue
            deletes = s["not_action"] or any(fnmatchcase(d, a.lower()) for a in s["actions"] for d in _DELETE_ACTIONS)
            covers = any(fnmatchcase(_PROBE_KEY, r) for r in s["resources"])
            assert not (deletes and covers), (
                f"{role} statement {sid} can delete telemetry-blobs/ objects (rec-4033 owns deletes)"
            )


def assert_writer_blob_grant_shape(text: str) -> None:
    st = _role_statements(text, _TELEMETRY)
    rw, lst = st.get("TelemetryBlobReadWrite"), st.get("TelemetryBlobList")
    assert rw is not None and lst is not None, "telemetry writer policy lacks TelemetryBlobReadWrite or TelemetryBlobList"
    assert rw["effect"] == "Allow" and not rw["not_action"], "TelemetryBlobReadWrite must be a plain Allow"
    assert sorted(rw["actions"]) == ["s3:GetObject", "s3:PutObject"], f"TelemetryBlobReadWrite actions {rw['actions']}"
    assert rw["resources"] == [f"{_ARN}/telemetry-blobs/ducklake_smoke/*"], (
        f"TelemetryBlobReadWrite resources {rw['resources']}"
    )
    assert lst["effect"] == "Allow" and lst["actions"] == ["s3:ListBucket"], f"TelemetryBlobList actions {lst['actions']}"
    assert lst["resources"] == [_ARN], f"TelemetryBlobList resources {lst['resources']}"
    assert lst["prefixes"] == ["telemetry-blobs/ducklake_smoke/*"], f"TelemetryBlobList must be fenced, got {lst['prefixes']}"
    assert_no_delete_on_prefix(text)


def assert_reader_has_no_blob_grant(text: str) -> None:
    for sid, s in _role_statements(text, "ducklake_reader").items():
        if s["effect"] != "Allow":
            continue
        s3_grant = s["not_action"] or any(a == "*" or a.lower().startswith("s3:") for a in s["actions"])
        covers = any(fnmatchcase(_PROBE_KEY, r) for r in s["resources"])
        named = any(p.startswith("telemetry-blobs") for p in s["prefixes"])
        assert not ((s3_grant and covers) or named), (
            f"reader statement {sid} grants access to telemetry-blobs/ (2b adds it if needed)"
        )


def assert_blob_lifecycle_rule(main_text: str, lambdas_text: str) -> None:
    assert _locals(lambdas_text).get("telemetry_blob_data_prefix") == "telemetry-blobs", "telemetry_blob_data_prefix moved"
    block = find_resource_block(main_text, "aws_s3_bucket_lifecycle_configuration", "data_lake")
    rules = [r for r in split_rule_blocks(block) if re.search(rf'\bid\s*=\s*"{_RULE_ID}"', r)]
    assert len(rules) == 1, f"expected exactly one {_RULE_ID} rule, found {len(rules)}"
    assert_every_rule_enabled(rules)
    assert re.search(r'prefix\s*=\s*"\$\{local\.telemetry_blob_data_prefix\}/"', rules[0]), (
        "the telemetry rule prefix must derive from local.telemetry_blob_data_prefix with a trailing slash"
    )


def _covers_secrets(s: dict) -> bool:
    return s["not_action"] or any(a == "*" or a.lower().startswith("secretsmanager:") for a in s["actions"])


def assert_telemetry_writer_reads_only_its_scoped_login(text: str) -> None:
    st = _role_statements(text, _TELEMETRY)
    granting = {sid: s for sid, s in st.items() if s["effect"] == "Allow" and _covers_secrets(s)}
    assert list(granting) == ["TelemetryDsnRead"], (
        f"secretsmanager grants must be TelemetryDsnRead only, got {sorted(granting)}"
    )
    dsn = granting["TelemetryDsnRead"]
    assert not dsn["not_action"] and dsn["actions"] == ["secretsmanager:GetSecretValue"], f"DSN actions {dsn['actions']}"
    assert dsn["resources"] == [f"{_SCOPED_SECRET}.arn"], f"DSN resources {dsn['resources']} must be the scoped login secret"
    env = _env(text, _TELEMETRY)
    assert env.get("TELEMETRY_DSN_SECRET_ID") == f"{_SCOPED_SECRET}.name", "TELEMETRY_DSN_SECRET_ID must name the scoped login"
    assert "ducklake_neon_catalog_dsn" not in find_resource_block(text, "aws_iam_role_policy", _TELEMETRY), (
        "the telemetry writer must never reference the shared catalog DSN"
    )


def assert_writer_carries_no_telemetry_state(text: str) -> None:
    env = _env(text, "ducklake_writer")
    leaked = sorted(k for k in env if k.startswith("TELEMETRY_"))
    assert not leaked, f"the shared writer env carries telemetry state {leaked}"
    for sid, s in _role_statements(text, "ducklake_writer").items():
        assert not sid.startswith("Telemetry"), f"the shared writer policy carries telemetry statement {sid}"
        assert not any(fnmatchcase(_PROBE_KEY, r) and "telemetry" in r for r in s["resources"]), (
            f"the shared writer statement {sid} grants telemetry-blobs/"
        )


def assert_telemetry_writer_cannot_reach_the_production_prefix(text: str) -> None:
    for sid, s in _role_statements(text, _TELEMETRY).items():
        if s["effect"] != "Allow":
            continue
        s3_any = s["not_action"] or any(a == "*" or a.lower().startswith("s3:") for a in s["actions"])
        assert not (s3_any and any(fnmatchcase(_PROD_KEY, r) for r in s["resources"])), (
            f"telemetry writer statement {sid} covers the production ducklake/ prefix"
        )
        lists = s["not_action"] or any(fnmatchcase("s3:listbucket", a.lower()) for a in s["actions"])
        if lists and any(fnmatchcase(_ARN, r) for r in s["resources"]):
            covering = not s["prefixes"] or any(fnmatchcase(_PROD_LIST_PROBE, p) for p in s["prefixes"])
            assert not covering, f"telemetry writer statement {sid} can list the production ducklake/ prefix"
    env = _env(text, _TELEMETRY)
    for key in ("DUCKLAKE_DATA_PATH", "DUCKLAKE_META_SCHEMA"):
        assert key not in env, f"the telemetry writer must not set {key}"


def assert_ops_catalog_env_untouched(text: str) -> None:
    for fn in _OPS_FUNCTIONS:
        env = _env(text, fn)
        assert "DUCKLAKE_META_SCHEMA" not in env, f"{fn} sets DUCKLAKE_META_SCHEMA, which re-points every ops verb"
        assert env.get("DUCKLAKE_DATA_PATH") == "local.ducklake_prod_data_path", f"{fn} DUCKLAKE_DATA_PATH moved"
        assert env.get("DUCKLAKE_EXTENSION_DIRECTORY") == "local.ducklake_extension_dir", f"{fn} extension dir moved"
        assert env.get("DUCKLAKE_FIELD_SEMANTICS_PATH") == _FIELD_SEMANTICS, f"{fn} field semantics path moved"


_FENCE = "${local.telemetry_blob_data_prefix}/${local.ducklake_telemetry_meta_schema}/*"
_RW = {
    "Sid": "TelemetryBlobReadWrite",
    "Action": ["s3:GetObject", "s3:PutObject"],
    "Resource": ["${aws_s3_bucket.data_lake.arn}/" + _FENCE],
}
_LIST = {
    "Sid": "TelemetryBlobList",
    "Action": ["s3:ListBucket"],
    "Resource": ["${aws_s3_bucket.data_lake.arn}"],
    "prefix": [_FENCE],
}
_DSN = {
    "Sid": "TelemetryDsnRead",
    "Action": ["secretsmanager:GetSecretValue"],
    "Resource": [f"{_SCOPED_SECRET}.arn"],
}
_CATALOG_LIST = {
    "Sid": "TelemetryCatalogDataList",
    "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
    "Resource": ["${aws_s3_bucket.data_lake.arn}"],
    "prefix": ["${local.ducklake_smoke_data_prefix}/*"],
}
_CATALOG_RW = {
    "Sid": "TelemetryCatalogDataReadWrite",
    "Action": ["s3:GetObject", "s3:PutObject"],
    "Resource": ["${aws_s3_bucket.data_lake.arn}/${local.ducklake_smoke_data_prefix}/*"],
}
_OPS_RW = {
    "Sid": "S3DataReadWrite",
    "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
    "Resource": ["${aws_s3_bucket.data_lake.arn}/${local.ducklake_prod_data_prefix}/*"],
}
_OPS_RO = {**_OPS_RW, "Sid": "S3DataReadOnly", "Action": ["s3:GetObject"]}
_TELEMETRY_STMTS = [_DSN, _CATALOG_RW, _CATALOG_LIST, _RW, _LIST]


def _stmt(s: dict) -> str:
    lines = ["{", f"  Sid = {json.dumps(s['Sid'])}", '  Effect = "Allow"']
    lines.append(f"  {'NotAction' if 'NotAction' in s else 'Action'} = {json.dumps(s.get('NotAction', s.get('Action')))}")
    resource = ", ".join(s["Resource"])
    lines.append(
        f"  Resource = [{resource}]"
        if "." in resource and '"' not in resource and "$" not in resource
        else f"  Resource = {json.dumps(s['Resource'])}"
    )
    if "prefix" in s:
        lines.append(f'  Condition = {{ StringLike = {{ "s3:prefix" = {json.dumps(s["prefix"])} }} }}')
    return "\n".join([*lines, "},"])


def _doc(
    writer_env: dict[str, str] | None = None,
    reader_env: dict[str, str] | None = None,
    telemetry_env: dict[str, str] | None = None,
    writer_stmts: list[dict] | None = None,
    reader_stmts: list[dict] | None = None,
    telemetry_stmts: list[dict] | None = None,
    meta_schema: str = "ducklake_smoke",
    blob_root: str = "s3://${aws_s3_bucket.data_lake.bucket}/${local.telemetry_blob_data_prefix}/${local.ducklake_telemetry_meta_schema}/",
) -> str:
    ops = {
        "DUCKLAKE_DATA_PATH": "local.ducklake_prod_data_path",
        "DUCKLAKE_EXTENSION_DIRECTORY": "local.ducklake_extension_dir",
        "DUCKLAKE_FIELD_SEMANTICS_PATH": _FIELD_SEMANTICS,
    }
    pins = {
        "TELEMETRY_META_SCHEMA": "local.ducklake_telemetry_meta_schema",
        "TELEMETRY_DATA_PATH": "local.ducklake_smoke_data_path",
    }
    telemetry_base = {
        **pins,
        "TELEMETRY_BLOB_ROOT": "local.ducklake_telemetry_blob_root",
        "TELEMETRY_DSN_SECRET_ID": f"{_SCOPED_SECRET}.name",
        "DUCKLAKE_EXTENSION_DIRECTORY": "local.ducklake_extension_dir",
        "DUCKLAKE_FIELD_SEMANTICS_PATH": _FIELD_SEMANTICS,
    }
    envs = {
        "ducklake_writer": {**ops, **(writer_env or {})},
        "ducklake_reader": {**ops, **pins, **(reader_env or {})},
        _TELEMETRY: {**telemetry_base, **(telemetry_env or {})},
    }
    stmts = {
        "ducklake_writer": writer_stmts if writer_stmts is not None else [_OPS_RW],
        "ducklake_reader": reader_stmts if reader_stmts is not None else [_OPS_RO],
        _TELEMETRY: telemetry_stmts if telemetry_stmts is not None else _TELEMETRY_STMTS,
    }
    parts = [
        "locals {",
        '  ducklake_telemetry_meta_schema = "' + meta_schema + '"',
        '  telemetry_blob_data_prefix = "telemetry-blobs"',
        '  ducklake_prod_data_prefix = "ducklake"',
        '  ducklake_smoke_data_prefix = "ducklake-neon-smoke"',
        '  ducklake_telemetry_blob_root = "' + blob_root + '"',
        "}",
    ]
    for fn, env in envs.items():
        body = "\n".join(f"      {k} = {v}" for k, v in env.items())
        parts.append(
            f'resource "aws_lambda_function" "{fn}" {{\n  environment {{\n    variables = {{\n{body}\n    }}\n  }}\n}}'
        )
        policy = "\n".join(_stmt(s) for s in stmts[fn])
        parts.append(f'resource "aws_iam_role_policy" "{fn}" {{\n  policy = jsonencode({{ Statement = [\n{policy}\n] }})\n}}')
    return "\n".join(parts)


def _real() -> tuple[str, str]:
    texts = tf_dir_file_texts(_TERRAFORM_PERSONAL_DIR)
    return texts["ducklake_lambdas.tf"] + "\n" + texts["ducklake_telemetry_writer.tf"], texts["main.tf"]


def test_telemetry_pins_target_the_smoke_catalog() -> None:
    assert_pins_target_smoke(_real()[0])


def test_blob_root_only_on_the_writer() -> None:
    assert_blob_root_only_on_writer(_real()[0])


def test_writer_blob_grant_shape() -> None:
    assert_writer_blob_grant_shape(_real()[0])


def test_blob_lifecycle_rule_covers_the_prefix() -> None:
    lambdas, main = _real()
    assert_blob_lifecycle_rule(main, lambdas)


def test_ops_catalog_env_is_untouched() -> None:
    assert_ops_catalog_env_untouched(_real()[0])


def test_reader_has_no_blob_grant() -> None:
    assert_reader_has_no_blob_grant(_real()[0])


def test_telemetry_writer_reads_only_its_scoped_login() -> None:
    assert_telemetry_writer_reads_only_its_scoped_login(_real()[0])


def test_writer_carries_no_telemetry_state() -> None:
    assert_writer_carries_no_telemetry_state(_real()[0])


def test_telemetry_writer_cannot_reach_the_production_prefix() -> None:
    assert_telemetry_writer_cannot_reach_the_production_prefix(_real()[0])


def test_pin_guard_rejects_a_moved_pin() -> None:
    assert_pins_target_smoke(_doc())
    moved = [
        _doc(meta_schema="ducklake_ops"),
        _doc(telemetry_env={"TELEMETRY_META_SCHEMA": "local.ducklake_prod_meta_schema"}),
        _doc(reader_env={"TELEMETRY_DATA_PATH": "local.ducklake_prod_data_path"}),
    ]
    for doc in moved:
        with pytest.raises(AssertionError, match="Decision"):
            assert_pins_target_smoke(doc)


def test_blob_root_guard_rejects_a_reader_root() -> None:
    assert_blob_root_only_on_writer(_doc())
    reader_root = _doc(reader_env={"TELEMETRY_BLOB_ROOT": "local.ducklake_telemetry_blob_root"})
    ops_writer_root = _doc(writer_env={"TELEMETRY_BLOB_ROOT": "local.ducklake_telemetry_blob_root"})
    unscoped = _doc(blob_root="s3://${aws_s3_bucket.data_lake.bucket}/${local.telemetry_blob_data_prefix}/")
    for doc in (reader_root, ops_writer_root, unscoped):
        with pytest.raises(AssertionError):
            assert_blob_root_only_on_writer(doc)


def _grant_variants() -> list[str]:
    arn = "${aws_s3_bucket.data_lake.arn}"
    docs = []
    for action in ("s3:DeleteObject", "s3:DeleteObjectVersion", "s3:Delete*", "s3:*", "s3:*Object*"):
        extra = {**_RW, "Sid": "Extra", "Action": [action]}
        docs.append(_doc(telemetry_stmts=[*_TELEMETRY_STMTS, extra]))
    for resource in (f"{arn}/telemetry-*", f"{arn}/*", f"{arn}/*blobs*"):
        extra = {**_OPS_RW, "Sid": "Extra", "Resource": [resource]}
        docs.append(_doc(telemetry_stmts=[*_TELEMETRY_STMTS, extra]))
    not_action = {"Sid": "Open", "NotAction": ["s3:ListBucket"], "Resource": [f"{arn}/*"]}
    docs.append(_doc(telemetry_stmts=[*_TELEMETRY_STMTS, not_action]))
    for bad_list in ({**_LIST, "prefix": []}, {**_LIST, "Resource": [f"{arn}/*"]}, {**_LIST, "prefix": ["telemetry-blobs/*"]}):
        docs.append(_doc(telemetry_stmts=[_RW, bad_list]))
    docs.append(_doc(telemetry_stmts=[{**_RW, "Resource": [f"{arn}/telemetry-blobs/*"]}, _LIST]))
    docs.append(_doc(telemetry_stmts=[{**_RW, "Action": [*_RW["Action"], "s3:AbortMultipartUpload"]}, _LIST]))
    docs.append(_doc(telemetry_stmts=[_LIST]))
    return docs


def test_grant_guard_rejects_delete() -> None:
    assert_writer_blob_grant_shape(_doc())
    variants = _grant_variants()
    for doc in variants:
        with pytest.raises(AssertionError):
            assert_writer_blob_grant_shape(doc)
    reader_delete = _doc(reader_stmts=[{**_RW, "Sid": "ReaderDelete", "Action": ["s3:DeleteObjectVersion"]}])
    with pytest.raises(AssertionError, match="delete"):
        assert_no_delete_on_prefix(reader_delete)
    writer_delete = _doc(writer_stmts=[{**_RW, "Sid": "WriterDelete", "Action": ["s3:DeleteObject"]}])
    with pytest.raises(AssertionError, match="delete"):
        assert_no_delete_on_prefix(writer_delete)


def test_lifecycle_guard_rejects_a_missing_rule() -> None:
    lambdas, main = _real()
    block = find_resource_block(main, "aws_s3_bucket_lifecycle_configuration", "data_lake")
    for bad in (
        main.replace(block, block.replace(_RULE_ID, "other-rule")),
        main.replace(block, block.replace("${local.telemetry_blob_data_prefix}/", "${local.telemetry_blob_data_prefix}")),
    ):
        with pytest.raises(AssertionError):
            assert_blob_lifecycle_rule(bad, lambdas)


def test_ops_env_guard_rejects_a_moved_ops_catalog() -> None:
    assert_ops_catalog_env_untouched(_doc())
    bad_envs = [
        {"DUCKLAKE_META_SCHEMA": "local.ducklake_telemetry_meta_schema"},
        {"DUCKLAKE_DATA_PATH": "local.ducklake_smoke_data_path"},
        {"DUCKLAKE_EXTENSION_DIRECTORY": "local.elsewhere"},
        {"DUCKLAKE_FIELD_SEMANTICS_PATH": '"/tmp/other.yaml"'},
    ]
    for env in bad_envs:
        with pytest.raises(AssertionError):
            assert_ops_catalog_env_untouched(_doc(reader_env=env))


def test_reader_guard_rejects_a_blob_grant() -> None:
    assert_reader_has_no_blob_grant(_doc())
    bad_stmts = [
        {**_RW, "Sid": "ReaderBlob", "Action": ["s3:GetObject"]},
        {**_OPS_RO, "Resource": ["${aws_s3_bucket.data_lake.arn}/*"]},
        {**_LIST, "Sid": "ReaderList"},
    ]
    for stmt in bad_stmts:
        with pytest.raises(AssertionError):
            assert_reader_has_no_blob_grant(_doc(reader_stmts=[_OPS_RO, stmt]))


def test_scoped_login_guard_rejects_the_shared_login() -> None:
    assert_telemetry_writer_reads_only_its_scoped_login(_doc())
    shared = "aws_secretsmanager_secret.ducklake_neon_catalog_dsn"
    bad = [
        _doc(telemetry_stmts=[*_TELEMETRY_STMTS, {**_DSN, "Sid": "SharedDsn", "Resource": [f"{shared}.arn"]}]),
        _doc(telemetry_stmts=[{**_DSN, "Resource": [f"{shared}.arn"]}, *_TELEMETRY_STMTS[1:]]),
        _doc(telemetry_stmts=[{**_DSN, "Action": ["secretsmanager:*"]}, *_TELEMETRY_STMTS[1:]]),
        _doc(telemetry_stmts=[{**_DSN, "Resource": [f"{_SCOPED_SECRET}.arn", f"{shared}.arn"]}, *_TELEMETRY_STMTS[1:]]),
        _doc(telemetry_stmts=[*_TELEMETRY_STMTS, {"Sid": "Any", "NotAction": ["s3:GetObject"], "Resource": ["*"]}]),
        _doc(telemetry_stmts=_TELEMETRY_STMTS[1:]),
        _doc(telemetry_env={"TELEMETRY_DSN_SECRET_ID": f"{shared}.name"}),
    ]
    for doc in bad:
        with pytest.raises(AssertionError):
            assert_telemetry_writer_reads_only_its_scoped_login(doc)


def test_no_telemetry_state_guard_rejects_a_leaky_writer() -> None:
    assert_writer_carries_no_telemetry_state(_doc())
    bad = [
        _doc(writer_env={"TELEMETRY_META_SCHEMA": "local.ducklake_telemetry_meta_schema"}),
        _doc(writer_env={"TELEMETRY_BLOB_ROOT": "local.ducklake_telemetry_blob_root"}),
        _doc(writer_stmts=[_OPS_RW, _RW]),
        _doc(writer_stmts=[_OPS_RW, {**_RW, "Sid": "Blob"}]),
    ]
    for doc in bad:
        with pytest.raises(AssertionError):
            assert_writer_carries_no_telemetry_state(doc)


def test_production_prefix_guard_rejects_reach() -> None:
    assert_telemetry_writer_cannot_reach_the_production_prefix(_doc())
    arn = "${aws_s3_bucket.data_lake.arn}"
    prod = "${local.ducklake_prod_data_prefix}"
    bad = [
        _doc(telemetry_stmts=[*_TELEMETRY_STMTS, {**_OPS_RW, "Sid": "ProdRW"}]),
        _doc(telemetry_stmts=[*_TELEMETRY_STMTS, {**_OPS_RW, "Sid": "ProdGet", "Action": ["s3:GetObject"]}]),
        _doc(telemetry_stmts=[*_TELEMETRY_STMTS, {**_OPS_RW, "Sid": "Wild", "Action": ["s3:*"], "Resource": [f"{arn}/*"]}]),
        _doc(telemetry_stmts=[*_TELEMETRY_STMTS, {**_OPS_RW, "Sid": "Star", "Action": ["*"], "Resource": ["*"]}]),
        _doc(
            telemetry_stmts=[
                *_TELEMETRY_STMTS,
                {"Sid": "Not", "NotAction": ["s3:DeleteObject"], "Resource": [f"{arn}/{prod}/*"]},
            ]
        ),
        _doc(telemetry_stmts=[*_TELEMETRY_STMTS, {**_LIST, "Sid": "ListAll", "prefix": ["*"]}]),
        _doc(telemetry_stmts=[*_TELEMETRY_STMTS, {**_LIST, "Sid": "ListProd", "prefix": [f"{prod}/*"]}]),
        _doc(telemetry_stmts=[*_TELEMETRY_STMTS, {"Sid": "ListNoCond", "Action": ["s3:ListBucket"], "Resource": [arn]}]),
        _doc(telemetry_env={"DUCKLAKE_DATA_PATH": "local.ducklake_prod_data_path"}),
        _doc(telemetry_env={"DUCKLAKE_META_SCHEMA": "ducklake"}),
    ]
    for doc in bad:
        with pytest.raises(AssertionError):
            assert_telemetry_writer_cannot_reach_the_production_prefix(doc)
