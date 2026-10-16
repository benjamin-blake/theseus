"""rec-4335 acceptance: the PR-time terraform/github plan and its IAM prerequisite.

TestPlannerStateGrant (PLAN-terraform-github-plan-state-grant): the github_ci_planner role reads exactly
one object under tfstate/github/ and nothing else there. Pure functions of HCL text: no network, terraform
or AWS.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TF_DIR = REPO_ROOT / "terraform" / "personal"

PLANNER_FILE = "oidc_pipeline_roles.tf"
PLANNER_DOC = "github_ci_planner"
GRANT_SID = "TfstateGithubRead"
GRANT_RESOURCE = "${aws_s3_bucket.data_lake.arn}/tfstate/github/terraform.tfstate"
TARGET_ACTION = "s3:GetObject"
TARGET_ARN = "arn:aws:s3:::agent-platform-data-lake/tfstate/github/terraform.tfstate"
LITERAL = "tfstate/github"

_DOC_RE = r'data\s+"aws_iam_policy_document"\s+"{name}"\s*\{{'
_ANY_DOC_RE = re.compile(r'data\s+"aws_iam_policy_document"\s+"(\w+)"\s*\{')
_STATEMENT_RE = re.compile(r"\bstatement\s*\{")
_SOURCE_RE = re.compile(r"data\.aws_iam_policy_document\.(\w+)\.json")
_BUCKET_REF_RE = re.compile(r"\$\{aws_s3_bucket\.data_lake\.arn\}|(?<![\w.])aws_s3_bucket\.data_lake\.arn\b")
_BUCKET_ARN = "arn:aws:s3:::agent-platform-data-lake"


def strip_comments(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i : j + 1])
            i = j + 1
        elif c == "#" or text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _balanced(text: str, open_idx: int) -> int:
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    raise AssertionError("unbalanced braces")


def _doc_block(text: str, name: str) -> str | None:
    m = re.search(_DOC_RE.format(name=re.escape(name)), text)
    return None if m is None else text[m.start() : _balanced(text, m.end() - 1) + 1]


def _items(body: str, key: str) -> list[str]:
    m = re.search(rf"\b{key}\s*=\s*\[(.*?)\]", body, re.DOTALL)
    if m is None:
        return []
    raw = [part.strip() for part in m.group(1).split(",") if part.strip()]
    return [part[1:-1] if part.startswith('"') and part.endswith('"') else part for part in raw]


def _parse_statement(body: str) -> dict:
    sid = re.search(r'\bsid\s*=\s*"([^"]*)"', body)
    effect = re.search(r'\beffect\s*=\s*"([^"]*)"', body)
    return {
        "sid": sid.group(1) if sid else None,
        "effect": effect.group(1) if effect else "Allow",
        "actions": _items(body, "actions"),
        "resources": _items(body, "resources"),
        "condition": re.search(r"\bcondition\s*\{", body) is not None,
    }


def statements_of(block: str) -> list[dict]:
    found = []
    for m in _STATEMENT_RE.finditer(block):
        found.append(_parse_statement(block[m.start() : _balanced(block, m.end() - 1) + 1]))
    return found


def doc_statements(texts: dict[str, str], name: str) -> list[dict]:
    """Statements a document composes: its own plus every source_policy_documents document, recursively."""
    for text in texts.values():
        block = _doc_block(text, name)
        if block is None:
            continue
        found = statements_of(block)
        for src in _SOURCE_RE.findall(block):
            found += doc_statements(texts, src)
        return found
    return []


def _expand(resource: str) -> str:
    return _BUCKET_REF_RE.sub(_BUCKET_ARN, resource)


def _grant_violations(texts: dict[str, str]) -> list[str]:
    own = statements_of(_doc_block(texts.get(PLANNER_FILE, ""), PLANNER_DOC) or "")
    own_hits = [s for s in own if any(LITERAL in r for r in s["resources"])]
    if len(own_hits) != 1:
        return [f"planner document names {LITERAL} in {len(own_hits)} statements, want exactly 1"]
    g = own_hits[0]
    bad = []
    if g["sid"] != GRANT_SID or g["effect"] != "Allow" or g["condition"]:
        bad.append(f"grant sid/effect/condition wrong: {g}")
    if g["actions"] != [TARGET_ACTION] or g["resources"] != [GRANT_RESOURCE]:
        bad.append(f"grant actions/resources not exact: {g['actions']} {g['resources']}")
    return bad


def _other_document_violations(texts: dict[str, str]) -> list[str]:
    bad = []
    for name in {n for t in texts.values() for n in _ANY_DOC_RE.findall(t)} - {PLANNER_DOC}:
        for s in doc_statements(texts, name):
            if any(LITERAL in r for r in s["resources"]) and s["effect"] == "Allow":
                bad.append(f"document {name} statement {s['sid']} names {LITERAL}")
    return bad


def _refresh_read_violations(texts: dict[str, str]) -> list[str]:
    bad = []
    for s in doc_statements(texts, "ci_full_refresh_read"):
        if s["sid"] == "TfstateRead" and any("tfstate/personal" not in r for r in s["resources"]):
            bad.append(f"TfstateRead leaves tfstate/personal: {s['resources']}")
    return bad


def _glob_coverage_violations(texts: dict[str, str]) -> list[str]:
    bad = []
    for s in doc_statements(texts, PLANNER_DOC):
        if s["effect"] != "Allow" or s["sid"] == GRANT_SID:
            continue
        if not any(fnmatch.fnmatchcase(TARGET_ACTION.lower(), a.lower()) for a in s["actions"]):
            continue
        bad += [
            f"statement {s['sid']} resource {r} covers the github state object"
            for r in s["resources"]
            if fnmatch.fnmatchcase(TARGET_ARN, _expand(r))
        ]
    return bad


def planner_violations(texts: dict[str, str]) -> list[str]:
    """Texts: {filename: comment-stripped HCL} for terraform/personal. Empty list == grant is exactly as planned."""
    checks = (_grant_violations, _other_document_violations, _refresh_read_violations, _glob_coverage_violations)
    return [v for check in checks for v in check(texts)]


def allow_statements_naming_literal(texts: dict[str, str]) -> list[tuple[str, str | None]]:
    """(filename, sid) of every Allow statement-like block (HCL statement or jsonencode object) naming LITERAL."""
    hits: list[tuple[str, str | None]] = []
    for fname, text in texts.items():
        for m in re.finditer(re.escape(LITERAL), text):
            enclosing = _innermost_statement(text, m.start())
            if enclosing is None:
                continue
            effect = re.search(r'\b[eE]ffect\s*=\s*"([^"]*)"', enclosing)
            if effect is not None and effect.group(1) != "Allow":
                continue
            sid = re.search(r'\b[sS]id\s*=\s*"([^"]*)"', enclosing)
            hits.append((fname, sid.group(1) if sid else None))
    return hits


def _innermost_statement(text: str, pos: int) -> str | None:
    """Innermost brace block around pos that carries a resources/Resource key (an IAM statement)."""
    starts = [i for i in range(pos) if text[i] == "{"]
    for start in reversed(starts):
        end = _balanced(text, start)
        if end >= pos and re.search(r"\b[rR]esources?\b\s*=", text[start : end + 1]):
            return text[start : end + 1]
    return None


def real_texts() -> dict[str, str]:
    return {p.name: strip_comments(p.read_text(encoding="utf-8")) for p in sorted(TF_DIR.glob("*.tf"))}


GRANT_HCL = """
  statement {
    sid       = "TfstateGithubRead"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/tfstate/github/terraform.tfstate"]
  }
"""


def _planner_file(extra: str = "", grant: str = GRANT_HCL, source: str = "ci_full_refresh_read") -> str:
    return (
        'data "aws_iam_policy_document" "github_ci_planner" {\n'
        f"  source_policy_documents = [data.aws_iam_policy_document.{source}.json]\n"
        f"{grant}{extra}}}\n"
    )


def _refresh_file(extra: str = "") -> str:
    return (
        'data "aws_iam_policy_document" "ci_full_refresh_read" {\n'
        "  statement {\n"
        '    sid       = "TfstateRead"\n'
        '    effect    = "Allow"\n'
        '    actions   = ["s3:GetObject"]\n'
        '    resources = ["${aws_s3_bucket.data_lake.arn}/tfstate/personal/*"]\n'
        "  }\n"
        "  statement {\n"
        '    sid       = "SSMDescribeParameters"\n'
        '    actions   = ["ssm:DescribeParameters"]\n'
        '    resources = ["*"]\n'
        "  }\n"
        f"{extra}}}\n"
        'data "aws_iam_policy_document" "ci_ssm_refresh_read" {\n'
        "}\n"
    )


def _pr_file(extra: str = "") -> str:
    return f'data "aws_iam_policy_document" "github_ci_pr" {{\n{extra}}}\n'


def synthetic(**kw: str) -> dict[str, str]:
    return {
        PLANNER_FILE: strip_comments(_planner_file(kw.get("planner_extra", ""), kw.get("grant", GRANT_HCL))),
        "oidc.tf": strip_comments(_refresh_file(kw.get("refresh_extra", ""))),
        "oidc_ci_roles.tf": strip_comments(_pr_file(kw.get("pr_extra", ""))),
    }


def _stmt(sid: str, actions: str, resources: str, effect: str = "Allow") -> str:
    return (
        f'  statement {{\n    sid = "{sid}"\n    effect = "{effect}"\n'
        f"    actions = [{actions}]\n    resources = [{resources}]\n  }}\n"
    )


class TestPlannerStateGrant:
    def test_real_hcl_grant_is_exactly_as_planned(self) -> None:
        assert planner_violations(real_texts()) == []

    def test_real_hcl_no_other_allow_statement_names_the_state_prefix(self) -> None:
        assert allow_statements_naming_literal(real_texts()) == [(PLANNER_FILE, GRANT_SID)]

    def test_real_hcl_refresh_read_still_scoped_to_tfstate_personal(self) -> None:
        stmts = {s["sid"]: s for s in doc_statements(real_texts(), "ci_full_refresh_read")}
        assert stmts["TfstateRead"]["resources"] == ["${aws_s3_bucket.data_lake.arn}/tfstate/personal/*"]

    def test_synthetic_green_baseline_passes(self) -> None:
        texts = synthetic()
        assert planner_violations(texts) == []
        assert allow_statements_naming_literal(texts) == [(PLANNER_FILE, GRANT_SID)]

    def test_red_wildcard_resource(self) -> None:
        grant = GRANT_HCL.replace("terraform.tfstate", "*")
        assert planner_violations(synthetic(grant=grant))

    def test_red_added_put_object(self) -> None:
        grant = GRANT_HCL.replace('["s3:GetObject"]', '["s3:GetObject", "s3:PutObject"]')
        assert planner_violations(synthetic(grant=grant))

    def test_red_grant_placed_in_refresh_read(self) -> None:
        texts = synthetic(grant="", refresh_extra=GRANT_HCL)
        assert planner_violations(texts)

    def test_red_grant_placed_in_pr_role_policy(self) -> None:
        texts = synthetic(grant="", pr_extra=GRANT_HCL)
        assert planner_violations(texts)
        assert (("oidc_ci_roles.tf", GRANT_SID)) in allow_statements_naming_literal(texts)

    def test_red_broader_resource_on_another_get_object_statement(self) -> None:
        for broad in ('"${aws_s3_bucket.data_lake.arn}/tfstate/*"', '"${aws_s3_bucket.data_lake.arn}/*"', '"*"'):
            extra = _stmt("Broad", '"s3:GetObject"', broad)
            assert planner_violations(synthetic(planner_extra=extra)), broad

    def test_red_action_glob_on_another_statement(self) -> None:
        for action in ('"s3:Get*"', '"s3:*"', '"*"'):
            extra = _stmt("Glob", action, '"${aws_s3_bucket.data_lake.arn}/*"')
            assert planner_violations(synthetic(planner_extra=extra)), action

    def test_resource_star_statements_without_get_object_are_excluded_by_action(self) -> None:
        extra = _stmt("CloudWatchLogsRead", '"logs:Describe*", "logs:Get*"', '"*"')
        assert planner_violations(synthetic(planner_extra=extra)) == []

    def test_deny_statement_on_state_prefix_is_out_of_scope(self) -> None:
        deny = _stmt("DenyGithubState", '"s3:*"', '"${aws_s3_bucket.data_lake.arn}/tfstate/github/*"', effect="Deny")
        texts = synthetic()
        texts["platform_dev_policies.tf"] = strip_comments(f'data "aws_iam_policy_document" "dev" {{\n{deny}}}\n')
        assert planner_violations(texts) == []
        assert allow_statements_naming_literal(texts) == [(PLANNER_FILE, GRANT_SID)]

    def test_jsonencode_allow_in_another_file_is_caught(self) -> None:
        texts = synthetic()
        texts["other.tf"] = strip_comments(
            'resource "aws_iam_policy" "x" {\n  policy = jsonencode({\n    Statement = [{\n      Effect = "Allow"\n'
            '      Action = ["s3:GetObject"]\n      Resource = ["arn:aws:s3:::b/tfstate/github/terraform.tfstate"]\n'
            "    }]\n  })\n}\n"
        )
        assert ("other.tf", None) in allow_statements_naming_literal(texts)

    def test_comment_mentions_are_ignored(self) -> None:
        stripped = strip_comments('# tfstate/github\nx = 1 // tfstate/github\n/* tfstate/github */\ny = "a#b"\n')
        assert LITERAL not in stripped
        assert 'y = "a#b"' in stripped
