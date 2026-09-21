"""Shared HCL-text helpers for the DuckLake maintenance test modules (tests/checks/iam_tf/).

Hoisted here rather than duplicated: tests.checks.iam_tf.test_ducklake_maintenance_tf_invariants
(lifecycle) and tests.checks.iam_tf.test_ducklake_maintenance_gc_rule_invariants (GC/alarm) both
need brace-balanced resource-block slicing and a directory-wide *.tf text sweep. tests/fixtures/
is an importable package whose names do not start with "test_", so it is exempt by construction
from validate_no_cross_test_imports (Decision 131 clause 2).
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TERRAFORM_PERSONAL_DIR = _REPO_ROOT / "terraform" / "personal"


def find_resource_block(text: str, resource_type: str, resource_name: str) -> str:
    """Brace-balanced slice for one named resource block."""
    pattern = re.compile(rf'resource\s+"{re.escape(resource_type)}"\s+"{re.escape(resource_name)}"\s*\{{')
    match = pattern.search(text)
    assert match is not None, f"resource {resource_type!r} {resource_name!r} not found"
    depth = 0
    end = match.end() - 1
    for i in range(match.end() - 1, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    return text[match.start() : end + 1]


def tf_dir_file_texts(tf_dir: Path) -> dict[str, str]:
    """{filename: text}, factored out so red-case fixtures can substitute a synthetic mapping."""
    return {tf_file.name: tf_file.read_text(encoding="utf-8") for tf_file in sorted(tf_dir.glob("*.tf"))}


_RULE_HEADER_RE = re.compile(r"\brule\s*\{")


def split_rule_blocks(resource_block: str) -> list[str]:
    """Brace-balanced split of every top-level `rule { ... }` block inside a resource block.

    Rule bodies nest (filter, noncurrent_version_expiration, expiration,
    abort_incomplete_multipart_upload), so a flat ``rule\\s*\\{([^}]*)\\}`` regex cannot split
    them -- the first closing brace it sees belongs to a nested block, not the rule itself.
    """
    blocks: list[str] = []
    for match in _RULE_HEADER_RE.finditer(resource_block):
        depth = 0
        end = match.end() - 1
        for i in range(match.end() - 1, len(resource_block)):
            if resource_block[i] == "{":
                depth += 1
            elif resource_block[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        blocks.append(resource_block[match.start() : end + 1])
    return blocks


# ---------------------------------------------------------------------------
# Reshaped per-rule lifecycle guards (PLAN-smoke-prefix-lifecycle-coverage), extracted as
# module-level predicates so a red case can invoke the real guard via pytest.raises(AssertionError)
# instead of merely re-asserting that its own fixture text was mutated.
# ---------------------------------------------------------------------------

_STATUS_RE = re.compile(r'status\s*=\s*"([^"]*)"')
_PREFIX_ASSIGN_RE = re.compile(r'prefix\s*=\s*"([^"]*)"')
_PREFIX_FROM_DATA_PREFIX_LOCAL_WITH_SLASH_RE = re.compile(r"^\$\{local\.\w+_data_prefix\}/$")
_NONCURRENT_VERSION_EXPIRATION_RE = re.compile(r"noncurrent_version_expiration\s*\{([^}]*)\}", re.DOTALL)
_NONCURRENT_DAYS_RE = re.compile(r"noncurrent_days\s*=\s*(\d+)")


def assert_every_rule_enabled(rule_blocks: list[str]) -> None:
    for rule in rule_blocks:
        m = _STATUS_RE.search(rule)
        assert m is not None, f"rule has no status attribute: {rule[:200]!r}"
        assert m.group(1) == "Enabled", (
            f"rule status is {m.group(1)!r}, not Enabled -- a Disabled rule satisfies every other "
            "assertion while reclaiming nothing"
        )


def assert_every_rule_prefix_derived_with_trailing_slash(rule_blocks: list[str]) -> None:
    for rule in rule_blocks:
        m = _PREFIX_ASSIGN_RE.search(rule)
        assert m is not None, f"rule has no filter.prefix attribute: {rule[:200]!r}"
        prefix = m.group(1)
        assert _PREFIX_FROM_DATA_PREFIX_LOCAL_WITH_SLASH_RE.match(prefix), (
            f"rule prefix {prefix!r} is not derived from a declared *_data_prefix local with a "
            "trailing slash -- a retyped literal or a missing slash would also match a sibling prefix"
        )


def assert_every_rule_has_expired_object_delete_marker(rule_blocks: list[str]) -> None:
    for rule in rule_blocks:
        assert re.search(r"expired_object_delete_marker\s*=\s*true", rule), (
            f"rule has no expired_object_delete_marker = true: {rule[:200]!r}"
        )


def assert_every_rule_noncurrent_days(rule_blocks: list[str], expected_days: int) -> None:
    for rule in rule_blocks:
        nve = _NONCURRENT_VERSION_EXPIRATION_RE.search(rule)
        assert nve is not None, f"rule carries no noncurrent_version_expiration block: {rule[:200]!r}"
        days_match = _NONCURRENT_DAYS_RE.search(nve.group(1))
        assert days_match is not None, "noncurrent_version_expiration block has no noncurrent_days"
        assert int(days_match.group(1)) == expected_days, f"noncurrent_days={days_match.group(1)} != expected {expected_days}"


def assert_every_declared_prefix_covered(roster: dict[str, str], resource_block: str, exclusions: dict[str, str]) -> None:
    uncovered = [
        local_name for local_name in roster if f"local.{local_name}" not in resource_block and not exclusions.get(local_name)
    ]
    assert not uncovered, (
        f"data-prefix local(s) {uncovered} are neither covered nor declared excluded -- a future "
        "prefix must not pass this coverage sweep vacuously (Decision 191)"
    )
