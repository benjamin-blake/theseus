"""Tests for scripts/ci/dependabot_semver_class.py -- the fail-closed semver-class deriver.

The deriver is a FALLBACK behind dependabot/fetch-metadata, never a replacement for it
(Decision 100): a non-empty UPDATE_TYPE wins at first precedence and short-circuits every
derivation branch below it. Every fixture that exercises a DERIVED branch therefore sets
UPDATE_TYPE explicitly empty -- a fixture that left it populated would exercise branch 1 and
prove nothing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci.dependabot_semver_class import (
    MAJOR,
    MINOR,
    PATCH,
    UNKNOWN,
    _class_between,
    _parse_version,
    derive,
    main,
)

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ci" / "dependabot_semver_class.py"

MCP_TITLE = "chore(deps): update mcp requirement from <2,>=1.28.0 to >=2.1.1,<3"
PYTEST_SOCKET_TITLE = "chore(deps): update pytest-socket requirement from >=0.8.0 to >=0.8.1"

_EMPTY = {
    "UPDATE_TYPE": "",
    "UPDATED_DEPENDENCIES_JSON": "",
    "PREVIOUS_VERSION": "",
    "NEW_VERSION": "",
    "DEPENDENCY_NAMES": "",
    "PR_TITLE": "",
}


def _env(**overrides: str) -> dict[str, str]:
    return {**_EMPTY, **overrides}


class TestManagedPrimitiveWinsAtFirstPrecedence:
    """Decision 100: a non-empty fetch-metadata UPDATE_TYPE short-circuits every branch below."""

    @pytest.mark.parametrize(
        ("update_type", "expected"),
        [
            ("version-update:semver-patch", PATCH),
            ("version-update:semver-minor", MINOR),
            ("version-update:semver-major", MAJOR),
        ],
    )
    def test_recognised_update_type_passes_straight_through(self, update_type: str, expected: str) -> None:
        assert derive(_env(UPDATE_TYPE=update_type)) == expected

    def test_populated_update_type_beats_a_contradicting_derivation(self) -> None:
        """The primitive wins even when every lower branch would derive something else."""
        env = _env(
            UPDATE_TYPE="version-update:semver-patch",
            PREVIOUS_VERSION="1.0.0",
            NEW_VERSION="9.0.0",
            DEPENDENCY_NAMES="mcp",
            PR_TITLE=MCP_TITLE,
        )
        assert derive(env) == PATCH

    def test_unrecognised_non_empty_update_type_is_unknown_not_a_fallthrough(self) -> None:
        """Fail closed: an unrecognised value is still the primitive's word, so no branch below runs."""
        env = _env(UPDATE_TYPE="version-update:semver-something", PR_TITLE=PYTEST_SOCKET_TITLE)
        assert derive(env) == UNKNOWN


class TestUpdatedDependenciesJson:
    """Precedence 2: per-member classes, taking the riskiest across members."""

    @staticmethod
    def _json(*members: dict) -> str:
        return json.dumps(list(members))

    def test_member_update_type_is_used(self) -> None:
        payload = self._json({"dependencyName": "mcp", "updateType": "version-update:semver-minor"})
        assert derive(_env(UPDATED_DEPENDENCIES_JSON=payload)) == MINOR

    def test_member_versions_are_derived_when_it_has_no_update_type(self) -> None:
        payload = self._json({"dependencyName": "mcp", "prevVersion": "1.28.0", "newVersion": "2.1.1"})
        assert derive(_env(UPDATED_DEPENDENCIES_JSON=payload)) == MAJOR

    def test_riskiest_member_wins_across_a_group(self) -> None:
        payload = self._json(
            {"dependencyName": "a", "updateType": "version-update:semver-patch"},
            {"dependencyName": "b", "updateType": "version-update:semver-major"},
            {"dependencyName": "c", "updateType": "version-update:semver-minor"},
        )
        assert derive(_env(UPDATED_DEPENDENCIES_JSON=payload)) == MAJOR

    def test_camel_and_snake_version_keys_are_both_accepted(self) -> None:
        payload = self._json({"dependency_name": "mcp", "prev_version": "0.8.0", "new_version": "0.8.1"})
        assert derive(_env(UPDATED_DEPENDENCIES_JSON=payload)) == PATCH

    def test_a_mixed_group_fails_closed(self) -> None:
        """Some members carrying evidence and others silent is a PARTIAL payload -- worse evidence
        than none -- so it fails closed rather than falling through to a weaker precedence."""
        payload = self._json(
            {"dependencyName": "a", "updateType": "version-update:semver-patch"},
            {"dependencyName": "b"},
        )
        assert derive(_env(UPDATED_DEPENDENCIES_JSON=payload, PR_TITLE=PYTEST_SOCKET_TITLE)) == UNKNOWN

    def test_a_member_whose_versions_do_not_parse_fails_closed(self) -> None:
        """Unparseable evidence is not the same as absent evidence: it stays unknown."""
        payload = self._json({"dependencyName": "a", "prevVersion": "latest", "newVersion": "newest"})
        assert derive(_env(UPDATED_DEPENDENCIES_JSON=payload, PR_TITLE=PYTEST_SOCKET_TITLE)) == UNKNOWN

    def test_a_non_mapping_entry_fails_closed(self) -> None:
        """A corrupt list (entries that are not objects) is never silently ignored."""
        assert derive(_env(UPDATED_DEPENDENCIES_JSON="[1, 2]", PR_TITLE=PYTEST_SOCKET_TITLE)) == UNKNOWN

    @pytest.mark.parametrize("payload", ["not json", "{}", "[]", '"a string"'])
    def test_unusable_payloads_fall_through_to_the_next_precedence(self, payload: str) -> None:
        env = _env(UPDATED_DEPENDENCIES_JSON=payload, PR_TITLE=PYTEST_SOCKET_TITLE)
        assert derive(env) == PATCH


class TestLiveDependabotPayloadShape:
    """REGRESSION (code-review round 1, High): the workflow ALWAYS supplies
    updated-dependencies-json, and on the empty-UPDATE_TYPE branch no member can carry an
    updateType by definition. For the `update <x> requirement from <spec> to <spec>` shape
    fetch-metadata extracts no versions either, so every member is SILENT. Returning unknown for
    that payload short-circuited precedence 2 and made the PR-title fallback dead code on every
    real dependabot range-update PR -- the exact shape the deriver was built for."""

    LIVE_SILENT_MEMBER = '[{"dependencyName": "pytest-socket", "directory": "/"}]'

    def test_pr_981_shape_with_a_populated_silent_payload_derives_patch(self) -> None:
        env = _env(
            UPDATED_DEPENDENCIES_JSON=self.LIVE_SILENT_MEMBER,
            DEPENDENCY_NAMES="pytest-socket",
            PR_TITLE=PYTEST_SOCKET_TITLE,
        )
        assert derive(env) == PATCH

    def test_pr_980_shape_with_a_populated_silent_payload_derives_major(self) -> None:
        env = _env(
            UPDATED_DEPENDENCIES_JSON='[{"dependencyName": "mcp", "directory": "/"}]',
            DEPENDENCY_NAMES="mcp",
            PR_TITLE=MCP_TITLE,
        )
        assert derive(env) == MAJOR

    def test_a_populated_silent_payload_still_reaches_the_scalar_pair_precedence(self) -> None:
        """Precedence 3 must be reachable too, not just the title."""
        env = _env(
            UPDATED_DEPENDENCIES_JSON=self.LIVE_SILENT_MEMBER,
            DEPENDENCY_NAMES="pytest-socket",
            PREVIOUS_VERSION="0.8.0",
            NEW_VERSION="0.9.0",
        )
        assert derive(env) == MINOR

    def test_a_populated_silent_payload_with_nothing_below_it_is_unknown(self) -> None:
        """Falling through is not the same as allowing: with no other evidence it still denies."""
        assert derive(_env(UPDATED_DEPENDENCIES_JSON=self.LIVE_SILENT_MEMBER)) == UNKNOWN

    def test_a_silent_payload_never_overrules_the_managed_primitive(self) -> None:
        env = _env(
            UPDATE_TYPE="version-update:semver-major",
            UPDATED_DEPENDENCIES_JSON=self.LIVE_SILENT_MEMBER,
            PR_TITLE=PYTEST_SOCKET_TITLE,
        )
        assert derive(env) == MAJOR


class TestScalarVersionPair:
    """Precedence 3: the scalar pair is trusted ONLY for a single dependency name."""

    def test_single_name_derives_from_the_scalar_pair(self) -> None:
        env = _env(PREVIOUS_VERSION="0.8.0", NEW_VERSION="0.9.0", DEPENDENCY_NAMES="pytest-socket")
        assert derive(env) == MINOR

    @pytest.mark.parametrize("names", ["a, b", "a b", "a\nb", "a,b,c"])
    def test_multi_name_group_with_one_scalar_pair_does_not_guess(self, names: str) -> None:
        env = _env(PREVIOUS_VERSION="1.0.0", NEW_VERSION="2.0.0", DEPENDENCY_NAMES=names)
        assert derive(env) == UNKNOWN

    def test_single_name_with_an_unparseable_pair_falls_through_to_the_title(self) -> None:
        env = _env(
            PREVIOUS_VERSION="latest",
            NEW_VERSION="newest",
            DEPENDENCY_NAMES="pytest-socket",
            PR_TITLE=PYTEST_SOCKET_TITLE,
        )
        assert derive(env) == PATCH

    def test_empty_scalar_pair_is_not_a_derivation(self) -> None:
        assert derive(_env(DEPENDENCY_NAMES="pytest-socket")) == UNKNOWN


class TestPrTitleFallback:
    """Precedence 4: the `update <x> requirement from <spec> to <spec>` shape only."""

    def test_live_pr_980_range_pair_derives_major(self) -> None:
        assert derive(_env(PR_TITLE=MCP_TITLE)) == MAJOR

    def test_live_pr_981_range_pair_derives_patch(self) -> None:
        assert derive(_env(PR_TITLE=PYTEST_SOCKET_TITLE)) == PATCH

    @pytest.mark.parametrize(
        "title",
        [
            "chore(deps): bump actions/checkout from 4 to 5",
            "Bump the pip group with 3 updates",
            "chore(deps-dev): update ruff requirement",
            "",
        ],
    )
    def test_unmatched_title_shapes_are_unknown(self, title: str) -> None:
        """The grouped `bump X from A to B` shape is deliberately NOT matched: fetch-metadata
        already classifies it at precedence 1, and a title-only auto-merge surface is not worth
        widening."""
        assert derive(_env(PR_TITLE=title)) == UNKNOWN

    def test_title_match_is_case_insensitive(self) -> None:
        assert derive(_env(PR_TITLE="Update MCP Requirement From >=1.0.0 To >=1.1.0")) == MINOR


class TestVersionParsing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1.2.3", (1, 2, 3)),
            ("v1.2.3", (1, 2, 3)),
            ("1.2", (1, 2, 0)),
            ("1", (1, 0, 0)),
            (">=1.2.3", (1, 2, 3)),
            # A lower-bound clause may itself carry the leading `v` (>=v1.2.3), which the
            # bare-version fallback never sees.
            (">=v1.2.3", (1, 2, 3)),
            ("<3,>=V2.0", (2, 0, 0)),
            ("==1.2.3", (1, 2, 3)),
            ("~=1.2.3", (1, 2, 3)),
            (">1.2.3", (1, 2, 3)),
            ("<2,>=1.28.0", (1, 28, 0)),
            (">=2.1.1,<3", (2, 1, 1)),
            # No lower-bound clause: the documented fallback takes the first clause whose value
            # starts with a digit, so a ceiling-only or exclusion-only specifier still yields a
            # triple. Safe because the caller denies anything it cannot allow outright.
            ("<2", (2, 0, 0)),
            ("!=1.0", (1, 0, 0)),
            ("1.2.3.post1", (1, 2, 3)),
            ("1.2.3rc1", (1, 2, 3)),
            ("1.2.3.dev4", (1, 2, 3)),
            ("1.2.3+local.1", (1, 2, 3)),
            ("1.2.3-beta", (1, 2, 3)),
        ],
    )
    def test_parsed_shapes(self, raw: str, expected: tuple[int, int, int]) -> None:
        assert _parse_version(raw) == expected

    @pytest.mark.parametrize("raw", ["", "latest", "main", "v", ">=", "  ", "!=abc"])
    def test_unparseable_shapes_return_none(self, raw: str) -> None:
        assert _parse_version(raw) is None

    @pytest.mark.parametrize(
        ("previous", "new", "expected"),
        [
            ("1.0.0", "2.0.0", MAJOR),
            ("1.0.0", "1.1.0", MINOR),
            ("1.0.0", "1.0.1", PATCH),
            ("0.8.0", "0.9.0", MINOR),
            ("0.8.0", "0.8.1", PATCH),
            ("0.8.0", "1.0.0", MAJOR),
            ("2.0.0", "1.0.0", MAJOR),
            ("1.2.3", "1.2.3", PATCH),
            ("1.2.3rc1", "1.2.3", PATCH),
        ],
    )
    def test_class_between(self, previous: str, new: str, expected: str) -> None:
        assert _class_between(previous, new) == expected

    @pytest.mark.parametrize(("previous", "new"), [("latest", "1.0.0"), ("1.0.0", "latest"), ("", "")])
    def test_class_between_is_unknown_when_either_side_is_unparseable(self, previous: str, new: str) -> None:
        assert _class_between(previous, new) is None


class TestEmptyInputSurfaceFailsClosed:
    def test_everything_empty_is_unknown(self) -> None:
        assert derive(_EMPTY) == UNKNOWN

    def test_missing_keys_entirely_is_unknown(self) -> None:
        assert derive({}) == UNKNOWN


class TestCommandLineContract:
    """Prints exactly one of patch|minor|major|unknown, always exits 0."""

    @staticmethod
    def _run(**env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env={"PATH": "/usr/bin:/bin", **_EMPTY, **env},
        )

    @pytest.mark.parametrize(
        ("env", "expected"),
        [
            ({"UPDATE_TYPE": "version-update:semver-minor"}, MINOR),
            ({"PR_TITLE": MCP_TITLE}, MAJOR),
            ({"PR_TITLE": PYTEST_SOCKET_TITLE}, PATCH),
            ({}, UNKNOWN),
        ],
    )
    def test_prints_one_token_and_exits_zero(self, env: dict[str, str], expected: str) -> None:
        result = self._run(**env)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected
        assert result.stdout.count("\n") == 1

    def test_exits_zero_even_on_hostile_input(self) -> None:
        result = self._run(UPDATED_DEPENDENCIES_JSON="[" * 5000, PR_TITLE="\u0001\ufffd " + "x" * 5000)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() in {PATCH, MINOR, MAJOR, UNKNOWN}

    def test_main_returns_zero_and_prints(self, capsys, monkeypatch) -> None:
        for key, value in _EMPTY.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv("PR_TITLE", MCP_TITLE)
        assert main() == 0
        assert capsys.readouterr().out.strip() == MAJOR

    def test_an_internal_error_fails_closed_and_still_exits_zero(self, capsys, monkeypatch) -> None:
        """An unexpected error must deny the merge, never red the workflow step."""
        import scripts.ci.dependabot_semver_class as module  # noqa: PLC0415

        monkeypatch.setattr(module, "derive", lambda env: (_ for _ in ()).throw(RuntimeError("boom")))
        assert module.main() == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == UNKNOWN
        assert "failing closed" in captured.err

    def test_module_never_raises_at_import(self) -> None:
        """AGENTS.md: no exceptions during module import, under any environment."""
        result = subprocess.run(
            [sys.executable, "-c", "import scripts.ci.dependabot_semver_class as m; print(m.UNKNOWN)"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env={"PATH": "/usr/bin:/bin", "UPDATE_TYPE": "garbage", "UPDATED_DEPENDENCIES_JSON": "{{{"},
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == UNKNOWN
