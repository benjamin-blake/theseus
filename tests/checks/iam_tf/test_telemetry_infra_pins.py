"""Standing guard for the telemetry writer infrastructure (PLAN-telemetry-writer-infra, T2.36 slice 2a-2 plan 2).

Pins, over the real terraform/personal tree: the telemetry catalog env on both DuckLake Lambdas (isolated
ducklake_smoke catalog until a Decision moves it, slice 2c), the writer-only catalog-scoped blob root, the
writer's blob grant (Get/Put plus a prefix-conditioned List, never a delete), the reader's lack of any blob
grant, the untouched ops catalog env, and the telemetry-blobs lifecycle rule. Every predicate is a pure
function of HCL text with its own red case on synthetic HCL.
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
_DELETE_ACTIONS = ("s3:deleteobject", "s3:deleteobjectversion")
_FUNCTIONS = ("ducklake_writer", "ducklake_reader")
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
    for fn in _FUNCTIONS:
        env = _env(text, fn)
        assert env.get("TELEMETRY_META_SCHEMA") == "local.ducklake_telemetry_meta_schema", (
            f"{fn} TELEMETRY_META_SCHEMA is {env.get('TELEMETRY_META_SCHEMA')!r}: {_PIN_MOVE_HINT}"
        )
        assert env.get("TELEMETRY_DATA_PATH") == "local.ducklake_smoke_data_path", (
            f"{fn} TELEMETRY_DATA_PATH is {env.get('TELEMETRY_DATA_PATH')!r}: {_PIN_MOVE_HINT}"
        )


def assert_blob_root_only_on_writer(text: str) -> None:
    locs = _locals(text)
    assert _env(text, "ducklake_writer").get("TELEMETRY_BLOB_ROOT") == "local.ducklake_telemetry_blob_root", (
        "writer TELEMETRY_BLOB_ROOT must be local.ducklake_telemetry_blob_root"
    )
    root = _resolve('"${local.ducklake_telemetry_blob_root}"', locs)
    expected = f"s3://{_BUCKET}/telemetry-blobs/{locs.get('ducklake_telemetry_meta_schema')}/"
    assert root == expected, f"blob root {root!r} must be catalog-scoped ({expected!r}): {_PIN_MOVE_HINT}"
    assert "TELEMETRY_BLOB_ROOT" not in _env(text, "ducklake_reader"), "the reader must not carry a blob root"


def assert_no_delete_on_prefix(text: str) -> None:
    for role in _FUNCTIONS:
        for sid, s in _role_statements(text, role).items():
            if s["effect"] != "Allow":
                continue
            deletes = s["not_action"] or any(fnmatchcase(d, a.lower()) for a in s["actions"] for d in _DELETE_ACTIONS)
            covers = any(fnmatchcase(_PROBE_KEY, r) for r in s["resources"])
            assert not (deletes and covers), (
                f"{role} statement {sid} can delete telemetry-blobs/ objects (rec-4033 owns deletes)"
            )


def assert_writer_blob_grant_shape(text: str) -> None:
    st = _role_statements(text, "ducklake_writer")
    rw, lst = st.get("TelemetryBlobReadWrite"), st.get("TelemetryBlobList")
    assert rw is not None and lst is not None, "writer policy lacks TelemetryBlobReadWrite or TelemetryBlobList"
    assert rw["effect"] == "Allow" and not rw["not_action"], "TelemetryBlobReadWrite must be a plain Allow"
    assert sorted(rw["actions"]) == ["s3:GetObject", "s3:PutObject"], f"TelemetryBlobReadWrite actions {rw['actions']}"
    assert rw["resources"] == [f"{_ARN}/telemetry-blobs/*"], f"TelemetryBlobReadWrite resources {rw['resources']}"
    assert lst["effect"] == "Allow" and lst["actions"] == ["s3:ListBucket"], f"TelemetryBlobList actions {lst['actions']}"
    assert lst["resources"] == [_ARN], f"TelemetryBlobList resources {lst['resources']}"
    assert lst["prefixes"] == ["telemetry-blobs/*"], f"TelemetryBlobList must be prefix-conditioned, got {lst['prefixes']}"
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


def assert_ops_catalog_env_untouched(text: str) -> None:
    for fn in _FUNCTIONS:
        env = _env(text, fn)
        assert "DUCKLAKE_META_SCHEMA" not in env, f"{fn} sets DUCKLAKE_META_SCHEMA, which re-points every ops verb"
        assert env.get("DUCKLAKE_DATA_PATH") == "local.ducklake_prod_data_path", f"{fn} DUCKLAKE_DATA_PATH moved"
        assert env.get("DUCKLAKE_EXTENSION_DIRECTORY") == "local.ducklake_extension_dir", f"{fn} extension dir moved"
        assert env.get("DUCKLAKE_FIELD_SEMANTICS_PATH") == _FIELD_SEMANTICS, f"{fn} field semantics path moved"


_RW = {
    "Sid": "TelemetryBlobReadWrite",
    "Action": ["s3:GetObject", "s3:PutObject"],
    "Resource": ["${aws_s3_bucket.data_lake.arn}/${local.telemetry_blob_data_prefix}/*"],
}
_LIST = {
    "Sid": "TelemetryBlobList",
    "Action": ["s3:ListBucket"],
    "Resource": ["${aws_s3_bucket.data_lake.arn}"],
    "prefix": ["${local.telemetry_blob_data_prefix}/*"],
}
_OPS_RW = {
    "Sid": "S3DataReadWrite",
    "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
    "Resource": ["${aws_s3_bucket.data_lake.arn}/${local.ducklake_prod_data_prefix}/*"],
}
_OPS_RO = {**_OPS_RW, "Sid": "S3DataReadOnly", "Action": ["s3:GetObject"]}


def _stmt(s: dict) -> str:
    lines = ["{", f"  Sid = {json.dumps(s['Sid'])}", '  Effect = "Allow"']
    lines.append(f"  {'NotAction' if 'NotAction' in s else 'Action'} = {json.dumps(s.get('NotAction', s.get('Action')))}")
    lines.append(f"  Resource = {json.dumps(s['Resource'])}")
    if "prefix" in s:
        lines.append(f'  Condition = {{ StringLike = {{ "s3:prefix" = {json.dumps(s["prefix"])} }} }}')
    return "\n".join([*lines, "},"])


def _doc(
    writer_env: dict[str, str] | None = None,
    reader_env: dict[str, str] | None = None,
    writer_stmts: list[dict] | None = None,
    reader_stmts: list[dict] | None = None,
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
    envs = {
        "ducklake_writer": {**ops, **pins, "TELEMETRY_BLOB_ROOT": "local.ducklake_telemetry_blob_root", **(writer_env or {})},
        "ducklake_reader": {**ops, **pins, **(reader_env or {})},
    }
    stmts = {
        "ducklake_writer": writer_stmts if writer_stmts is not None else [_OPS_RW, _RW, _LIST],
        "ducklake_reader": reader_stmts if reader_stmts is not None else [_OPS_RO],
    }
    parts = [
        "locals {",
        '  ducklake_telemetry_meta_schema = "' + meta_schema + '"',
        '  telemetry_blob_data_prefix = "telemetry-blobs"',
        '  ducklake_prod_data_prefix = "ducklake"',
        '  ducklake_telemetry_blob_root = "' + blob_root + '"',
        "}",
    ]
    for fn in _FUNCTIONS:
        body = "\n".join(f"      {k} = {v}" for k, v in envs[fn].items())
        parts.append(
            f'resource "aws_lambda_function" "{fn}" {{\n  environment {{\n    variables = {{\n{body}\n    }}\n  }}\n}}'
        )
        policy = "\n".join(_stmt(s) for s in stmts[fn])
        parts.append(f'resource "aws_iam_role_policy" "{fn}" {{\n  policy = jsonencode({{ Statement = [\n{policy}\n] }})\n}}')
    return "\n".join(parts)


def _real() -> tuple[str, str]:
    texts = tf_dir_file_texts(_TERRAFORM_PERSONAL_DIR)
    return texts["ducklake_lambdas.tf"], texts["main.tf"]


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


def test_pin_guard_rejects_a_moved_pin() -> None:
    assert_pins_target_smoke(_doc())
    moved = [
        _doc(meta_schema="ducklake_ops"),
        _doc(writer_env={"TELEMETRY_META_SCHEMA": "local.ducklake_prod_meta_schema"}),
        _doc(reader_env={"TELEMETRY_DATA_PATH": "local.ducklake_prod_data_path"}),
    ]
    for doc in moved:
        with pytest.raises(AssertionError, match="Decision"):
            assert_pins_target_smoke(doc)


def test_blob_root_guard_rejects_a_reader_root() -> None:
    assert_blob_root_only_on_writer(_doc())
    reader_root = _doc(reader_env={"TELEMETRY_BLOB_ROOT": "local.ducklake_telemetry_blob_root"})
    unscoped = _doc(blob_root="s3://${aws_s3_bucket.data_lake.bucket}/${local.telemetry_blob_data_prefix}/")
    for doc in (reader_root, unscoped):
        with pytest.raises(AssertionError):
            assert_blob_root_only_on_writer(doc)


def _grant_variants() -> list[str]:
    arn = "${aws_s3_bucket.data_lake.arn}"
    docs = []
    for action in ("s3:DeleteObject", "s3:DeleteObjectVersion", "s3:Delete*", "s3:*", "s3:*Object*"):
        extra = {**_RW, "Sid": "Extra", "Action": [action]}
        docs.append(_doc(writer_stmts=[_OPS_RW, _RW, _LIST, extra]))
    for resource in (f"{arn}/telemetry-*", f"{arn}/*", f"{arn}/*blobs*"):
        extra = {**_OPS_RW, "Sid": "Extra", "Resource": [resource]}
        docs.append(_doc(writer_stmts=[_OPS_RW, _RW, _LIST, extra]))
    not_action = {"Sid": "Open", "NotAction": ["s3:ListBucket"], "Resource": [f"{arn}/*"]}
    docs.append(_doc(writer_stmts=[_OPS_RW, _RW, _LIST, not_action]))
    for bad_list in ({**_LIST, "prefix": []}, {**_LIST, "Resource": [f"{arn}/*"]}):
        docs.append(_doc(writer_stmts=[_RW, bad_list]))
    docs.append(_doc(writer_stmts=[{**_RW, "Action": [*_RW["Action"], "s3:AbortMultipartUpload"]}, _LIST]))
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
