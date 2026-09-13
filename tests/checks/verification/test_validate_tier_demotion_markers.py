"""Mirror test for scripts/checks/verification/validate_tier_demotion_markers.py (LSA-01 leg a,
Decision 187, PLAN-verifier-weakening-guards).

Every fixture is a synthetic git repository built fresh in tmp_path (the TestAuditorOnSyntheticRepo
idiom, mirroring tests/checks/verification/validate_scope_boundary/conftest.py's
_init_repo/_commit_all/refs-remotes-origin-main pattern) -- never a committed snapshot file, since
the gate itself reads only git and disk. `_common.ROOT` is patched AND `root=` is passed explicitly
(Decision 159 cl.1's double-binding idiom), so the gate's own git probes and the shared mechanism's
`_common.ROOT`-reading functions both see the fixture repo.

NO LIVE CHECK NAME OTHER THAN THE GATE'S OWN appears as a literal anywhere in this file -- every
fixture Entry uses a synthetic name (`synthetic_check_*`), and TestAntiRitualPins asserts this
mechanically against registry._ALL_ENTRIES, with the gate's own name DERIVED
(`gate.validate_tier_demotion_markers.__name__`), never spelled out.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.checks import _common, registry
from scripts.checks.verification import validate_tier_demotion_markers as gate

# A synthetic authorizing corpus -- present at both base and head in every fixture repo, so
# authorization_failure has real Decision bodies to consult without touching the real
# docs/DECISIONS.md. dec-500 is the deliberate skeleton-key decoy (mentions scripts/checks
# generically, no specific check); dec-501 authorizes synthetic_check_a by its own bare name.
_FAKE_DECISIONS_MD = (
    "## Decision 500: Skeleton-key decoy, mentions only scripts/checks generically (Decided)\n\n"
    "**Status:** Decided\n**Date:** 2026-01-01\n"
    "**Decision:** Governs scripts/checks broadly, names no specific check by name.\n\n---\n\n"
    "## Decision 501: Authorizes synthetic_check_a's tier demotion for testing (Decided)\n\n"
    "**Status:** Decided\n**Date:** 2026-01-01\n"
    "**Decision:** Authorizes synthetic_check_a's tier demotion.\n\n---\n"
)


def _git(repo: Path, args: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _write_files(repo: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _entry(
    name: str,
    *,
    pre: bool,
    full_segment: str | None,
    pre_globs: tuple[str, ...] | None,
    marker: str | None = None,
) -> str:
    """One `Entry(...)` call's source text, with an optional marker comment on its own closing
    line -- inside the AST call's own line span, per the entry-line-span placement rule."""
    globs_src = "None" if pre_globs is None else "(" + ", ".join(f'"{g}"' for g in pre_globs) + ",)"
    comment = f"  # {marker}" if marker else ""
    return (
        "    Entry(\n"
        f'        name="{name}",\n'
        f'        module="scripts.checks.fake.{name}",\n'
        f'        attr="{name}",\n'
        f"        pre={pre!r},\n"
        f"        pre_globs={globs_src},\n"
        f"        full_segment={full_segment!r},\n"
        f"    ),{comment}\n"
    )


def _manifest_src(*entries_src: str) -> str:
    return "from scripts.checks._schema import Entry\n\nENTRIES = (\n" + "".join(entries_src) + ")\n"


def _alt_form_manifest_src(call: str) -> str:
    """ONE Entry spelled a legal-but-non-canonical way -- attribute form or positional name."""
    return f"from scripts.checks import _schema\nfrom scripts.checks._schema import Entry\n\nENTRIES = (\n{call}\n)\n"


def _repo(
    tmp_path: Path,
    base_manifest: str | None,
    head_manifest: str | None,
    *,
    manifest_rel: str = "scripts/checks/fake/_manifest.py",
    extra_base: dict[str, str] | None = None,
    extra_head: dict[str, str] | None = None,
) -> Path:
    """A fresh git repo: a base commit (pinned to refs/remotes/origin/main) then a head commit,
    each carrying one domain manifest's text (None means the file is absent) plus any extra
    tracked files (for the glob-coverage fixtures, which need real files git ls-files can see)."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, ["init", "-q"])
    _git(repo, ["config", "user.email", "test@example.com"])
    _git(repo, ["config", "user.name", "Test"])

    base_files = dict(extra_base or {})
    base_files["docs/DECISIONS.md"] = _FAKE_DECISIONS_MD
    if base_manifest is not None:
        base_files[manifest_rel] = base_manifest
    _write_files(repo, base_files)
    _git(repo, ["add", "-A"])
    _git(repo, ["commit", "-q", "-m", "base"])
    base_sha = _git(repo, ["rev-parse", "HEAD"]).stdout.strip()
    _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

    for rel in extra_base or {}:
        if rel not in (extra_head or {}):
            (repo / rel).unlink()
    if base_manifest is not None and head_manifest is None:
        (repo / manifest_rel).unlink()

    head_files = dict(extra_head or {})
    if head_manifest is not None:
        head_files[manifest_rel] = head_manifest
    _write_files(repo, head_files)
    _git(repo, ["add", "-A"])
    _git(repo, ["commit", "-q", "-m", "head"])
    return repo


def _run(repo: Path) -> list[str]:
    failed: list[str] = []
    with patch.object(_common, "ROOT", repo):
        gate.validate_tier_demotion_markers(failed, root=repo)
    return failed


def _run_with_failing_git(repo: Path, failing: tuple[str, ...]) -> tuple[list[str], registry._Declaration | None]:
    """Run the gate with exactly ONE git subcommand forced to fail -- every other probe runs for
    real. It reproduces git's real failure shape (non-zero rc AND empty stdout)."""
    original_run = _common.run

    def _selective(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        result = original_run(cmd, **kwargs)
        if tuple(cmd[1 : 1 + len(failing)]) == failing:
            empty = b"" if isinstance(result.stdout, bytes) else ""
            return subprocess.CompletedProcess(cmd, 128, empty, result.stderr)
        return result

    failed: list[str] = []
    with patch.object(_common, "ROOT", repo), patch.object(_common, "run", _selective):
        with registry.outcome_scope("validate_tier_demotion_markers"):
            gate.validate_tier_demotion_markers(failed, root=repo)
            declaration = registry.pop_declaration()
    return failed, declaration


class TestKnownBadFixtures:
    """VP step 1's eleven known-bad fixtures plus three from code review -- each a real weakening."""

    def test_unmarked_pre_true_to_false_fails(self, tmp_path: Path) -> None:
        base = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=None))
        head = _manifest_src(_entry("synthetic_check_a", pre=False, full_segment=None, pre_globs=None))
        assert _run(_repo(tmp_path, base, head)) != []

    def test_unmarked_full_segment_lost_fails(self, tmp_path: Path) -> None:
        base = _manifest_src(_entry("synthetic_check_a", pre=False, full_segment="full_after_lint", pre_globs=None))
        head = _manifest_src(_entry("synthetic_check_a", pre=False, full_segment=None, pre_globs=None))
        assert _run(_repo(tmp_path, base, head)) != []

    def test_unmarked_pre_globs_narrowing_fails(self, tmp_path: Path) -> None:
        files = {"scripts/fake/only.py": "x = 1\n", "scripts/fake/other.py": "x = 1\n"}
        base = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=("scripts/fake/**",)))
        head = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=("scripts/fake/only.py",)))
        assert _run(_repo(tmp_path, base, head, extra_base=files, extra_head=files)) != []

    def test_unmarked_pre_globs_none_to_never_glob_fails(self, tmp_path: Path) -> None:
        base = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=None))
        head = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=("never/**",)))
        assert _run(_repo(tmp_path, base, head)) != []

    def test_still_sequenced_entry_removed_fails(self, tmp_path: Path) -> None:
        base = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=None))
        head = _manifest_src()
        assert _run(_repo(tmp_path, base, head)) != []

    def test_whole_domain_manifest_deleted_with_sequenced_entries_fails(self, tmp_path: Path) -> None:
        base = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=None))
        assert _run(_repo(tmp_path, base, None)) != []

    def test_marker_citing_nonexistent_decision_fails(self, tmp_path: Path) -> None:
        base = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=None))
        head = _manifest_src(
            _entry(
                "synthetic_check_a",
                pre=False,
                full_segment=None,
                pre_globs=None,
                marker="tier-demotion-approved: dec-999999 nonexistent decision",
            )
        )
        assert _run(_repo(tmp_path, base, head)) != []

    def test_marker_citing_skeleton_key_decision_fails(self, tmp_path: Path) -> None:
        """dec-500 mentions `scripts/checks` generically, never this check's own name -- the
        skeleton-key refusal at check-NAME-level authorization."""
        base = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=None))
        head = _manifest_src(
            _entry(
                "synthetic_check_a",
                pre=False,
                full_segment=None,
                pre_globs=None,
                marker="tier-demotion-approved: dec-500 generic mention only",
            )
        )
        assert _run(_repo(tmp_path, base, head)) != []

    def test_marker_with_empty_reason_fails(self, tmp_path: Path) -> None:
        base = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=None))
        head = _manifest_src(
            _entry("synthetic_check_a", pre=False, full_segment=None, pre_globs=None, marker="tier-demotion-approved: dec-501")
        )
        assert _run(_repo(tmp_path, base, head)) != []

    def test_stale_marker_identical_to_base_fails(self, tmp_path: Path) -> None:
        marker = "tier-demotion-approved: dec-501 already used once"
        base = _manifest_src(
            _entry("synthetic_check_a", pre=True, full_segment="full_after_lint", pre_globs=None, marker=marker)
        )
        head = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=None, marker=marker))
        assert _run(_repo(tmp_path, base, head)) != []

    def test_stale_marker_reworded_but_citing_the_same_decision_fails(self, tmp_path: Path) -> None:
        """DEC-ID-LEVEL, not byte-level: rewording a spent marker's reason never makes it fresh."""
        spent = "tier-demotion-approved: dec-501 already used once"
        reworded = "tier-demotion-approved: dec-501 a completely different reason, same decision"
        base = _manifest_src(
            _entry("synthetic_check_a", pre=True, full_segment="full_after_lint", pre_globs=None, marker=spent)
        )
        head = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=None, marker=reworded))
        assert _run(_repo(tmp_path, base, head)) != []

    def test_attribute_form_entry_demoted_unmarked_fails(self, tmp_path: Path) -> None:
        """Bare-`Entry`-Name-only detection leaves these invisible at BOTH base and head."""
        call = '    _schema.Entry(name="synthetic_check_a", module="m", attr="a", pre={0}),'
        repo = _repo(tmp_path, _alt_form_manifest_src(call.format(True)), _alt_form_manifest_src(call.format(False)))
        assert _run(repo) != []

    def test_positional_name_entry_demoted_unmarked_fails(self, tmp_path: Path) -> None:
        """`name` is Entry's FIRST field: a positional call is as grammar-legal as the keyword one."""
        call = '    Entry("synthetic_check_a", "m", "a", pre={0}),'
        repo = _repo(tmp_path, _alt_form_manifest_src(call.format(True)), _alt_form_manifest_src(call.format(False)))
        assert _run(repo) != []

    def test_deletion_with_marker_in_header_and_vacated_span_still_fails(self, tmp_path: Path) -> None:
        """The eleventh fixture: a valid, authorized, reason-bearing marker placed as plausibly
        as the grammar allows -- the module header AND the vacated line span -- and it STILL
        fails, because a removed Entry has no head line to carry one; check_state_diff's
        deletion branch never consults marker text at all."""
        base = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=None))
        head = (
            "from scripts.checks._schema import Entry\n\n"
            "# tier-demotion-approved: dec-501 synthetic_check_a retired, see module header\n"
            "ENTRIES = (\n"
            "    # tier-demotion-approved: dec-501 synthetic_check_a retired, vacated line span\n"
            ")\n"
        )
        assert _run(_repo(tmp_path, base, head)) != []


class TestPositiveControl:
    """The ONE positive control: a correctly marked, correctly authorized weakening passes clean."""

    def test_marked_and_authorized_demotion_passes(self, tmp_path: Path) -> None:
        base = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=None))
        head = _manifest_src(
            _entry(
                "synthetic_check_a",
                pre=False,
                full_segment=None,
                pre_globs=None,
                marker="tier-demotion-approved: dec-501 synthetic_check_a demoted per Decision 501",
            )
        )
        assert _run(_repo(tmp_path, base, head)) == []


class TestTighteningIsFree:
    """VP step 2: seven tightening moves, each UNMARKED, each must pass clean. If any needs a
    marker the mechanism is dead -- this is a first-class acceptance criterion."""

    def test_promotion_is_free(self, tmp_path: Path) -> None:
        base = _manifest_src(_entry("synthetic_check_a", pre=False, full_segment=None, pre_globs=None))
        head = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=None))
        assert _run(_repo(tmp_path, base, head)) == []

    def test_full_segment_added_is_free(self, tmp_path: Path) -> None:
        base = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=None))
        head = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment="full_after_lint", pre_globs=None))
        assert _run(_repo(tmp_path, base, head)) == []

    def test_glob_widening_is_free(self, tmp_path: Path) -> None:
        files = {"scripts/fake/a.py": "x = 1\n", "scripts/fake/b.py": "x = 1\n"}
        base = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=("scripts/fake/a.py",)))
        head = _manifest_src(
            _entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=("scripts/fake/a.py", "scripts/fake/b.py"))
        )
        assert _run(_repo(tmp_path, base, head, extra_base=files, extra_head=files)) == []

    def test_new_entry_is_free(self, tmp_path: Path) -> None:
        head = _manifest_src(_entry("synthetic_check_new", pre=True, full_segment=None, pre_globs=None))
        assert _run(_repo(tmp_path, None, head)) == []

    def test_marker_removed_with_no_state_change_is_free(self, tmp_path: Path) -> None:
        base = _manifest_src(
            _entry(
                "synthetic_check_a",
                pre=True,
                full_segment=None,
                pre_globs=None,
                marker="tier-demotion-approved: dec-501 stale leftover",
            )
        )
        head = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=None))
        assert _run(_repo(tmp_path, base, head)) == []

    def test_unsequenced_entry_deleted_is_free(self, tmp_path: Path) -> None:
        base = _manifest_src(_entry("synthetic_check_a", pre=False, full_segment=None, pre_globs=None))
        head = _manifest_src()
        assert _run(_repo(tmp_path, base, head)) == []

    def test_glob_repointed_across_same_pr_rename_is_free(self, tmp_path: Path) -> None:
        """Pins the HEAD-file-list reading of the coverage-superset rule: under a BASE-list
        reading this is the one case that inverts and demands a marker on a pure rename."""
        base = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=("scripts/foo/**",)))
        head = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=("scripts/bar/**",)))
        repo = _repo(
            tmp_path,
            base,
            head,
            extra_base={"scripts/foo/thing.py": "x = 1\n"},
            extra_head={"scripts/bar/thing.py": "x = 1\n"},
        )
        assert _run(repo) == []


class TestCleanOnLiveFleet:
    """VP step 4: clean on day one, no grandfather hook."""

    def test_zero_violations_against_the_real_tree_and_base_ref(self) -> None:
        failed: list[str] = []
        gate.validate_tier_demotion_markers(failed)
        assert failed == []

    def test_examined_count_covers_every_live_manifest_entry(self) -> None:
        """`examined` counts BASE-UNION-HEAD keys, so it is `>=` the live (head-only) count, never
        `==`: mark-then-drop retirement deletes a base key with no head counterpart, so `==` reds
        on the second PR of the workflow this gate prescribes. Head parity is pinned below."""
        failed: list[str] = []
        with registry.outcome_scope("validate_tier_demotion_markers"):
            gate.validate_tier_demotion_markers(failed)
            declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"

        head_keys: set[str] = set()
        for manifest in sorted((_common.ROOT / "scripts" / "checks").glob("*/_manifest.py")):
            head_keys |= set(gate.extract_tier_states(manifest.read_text(encoding="utf-8", errors="replace")))
        assert head_keys == set(registry._ALL_ENTRIES)
        assert declaration.count is not None and declaration.count >= len(head_keys)

    def test_no_grandfather_shaped_constant_in_the_guard_module(self) -> None:
        """AST scan, module-level only: no frozenset/set/tuple/list/dict constant of check
        names (any grandfather shape) -- bare literal OR wrapped in a builtin collection call."""
        tree = ast.parse(Path(inspect.getfile(gate)).read_text(encoding="utf-8"))
        literal_types = (ast.Set, ast.SetComp, ast.List, ast.ListComp, ast.Tuple, ast.Dict, ast.DictComp)
        ctor_names = {"frozenset", "set", "tuple", "list", "dict"}

        def _is_collection_shaped(value: ast.expr) -> bool:
            if isinstance(value, literal_types):
                return True
            return isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in ctor_names

        hits = [
            ast.dump(node)[:120]
            for node in tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None and _is_collection_shaped(node.value)
        ]
        assert not hits, f"module-level collection-shaped constant(s) found (grandfather-hook shape): {hits}"


def _repo_with_n_domains(tmp_path: Path, n: int) -> Path:
    """n domains, each holding one clean, unmarked, untouched Entry (base == head) -- for the
    subprocess-fan-out pin only; no state transition matters here."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, ["init", "-q"])
    _git(repo, ["config", "user.email", "test@example.com"])
    _git(repo, ["config", "user.name", "Test"])
    files = {"docs/DECISIONS.md": _FAKE_DECISIONS_MD}
    for i in range(n):
        files[f"scripts/checks/domain{i}/_manifest.py"] = _manifest_src(
            _entry(f"synthetic_check_{i}", pre=True, full_segment=None, pre_globs=None)
        )
    _write_files(repo, files)
    _git(repo, ["add", "-A"])
    _git(repo, ["commit", "-q", "-m", "base"])
    base_sha = _git(repo, ["rev-parse", "HEAD"]).stdout.strip()
    _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
    _git(repo, ["commit", "-q", "-m", "head", "--allow-empty"])
    return repo


def _count_common_run_calls(repo: Path) -> int:
    calls = 0
    original_run = _common.run

    def _spy(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original_run(*args, **kwargs)  # type: ignore[arg-type]

    failed: list[str] = []
    with patch.object(_common, "ROOT", repo), patch.object(_common, "run", _spy):
        gate.validate_tier_demotion_markers(failed, root=repo)
    return calls


def _code_string_and_name_literals(tree: ast.Module) -> set[str]:
    """Every string-constant value and every bare identifier appearing in `tree`'s ACTUAL CODE,
    excluding docstring positions (the first statement of a module/class/function body, when it
    is a bare string-literal Expr) -- a docstring citing a sibling check's name for precedent is
    prose, not a roster; a string used as data or a name used as an identifier is."""
    docstring_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstring_ids.add(id(first.value))

    literals: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstring_ids:
            literals.add(node.value)
        elif isinstance(node, ast.Name):
            literals.add(node.id)
    return literals


class TestAntiRitualPins:
    """VP step 6: no live check name other than the gate's own is a literal here or in the
    guard; the base is read via git with no committed snapshot fallback; the subprocess count is
    independent of domain count."""

    def test_no_foreign_live_check_name_literal_in_guard_or_mirror(self) -> None:
        """The gate's own name is DERIVED (fn.__name__), never spelled as a literal. The
        whole-fleet "no name at all" form is provably unsatisfiable -- every registered check
        necessarily names itself in its own @registry.register decoration, and this mirror
        necessarily imports it by name -- so this asserts the weaker, satisfiable property: no
        OTHER live check name appears, as a STRING or IDENTIFIER LITERAL (ast.Constant(str) /
        ast.Name) in either file's actual code. Prose CITING a sibling check's name for
        precedent (a docstring or comment -- comments are invisible to ast, docstrings are
        excluded below) is not a roster and is deliberately not scanned: this pin is about
        executable code, never about explanatory text."""
        own_name = gate.validate_tier_demotion_markers.__name__
        guard_tree = ast.parse(Path(inspect.getfile(gate)).read_text(encoding="utf-8"))
        mirror_tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        literals = _code_string_and_name_literals(guard_tree) | _code_string_and_name_literals(mirror_tree)
        foreign_hits = sorted((set(registry._ALL_ENTRIES) - {own_name}) & literals)
        assert not foreign_hits, f"foreign live check name(s) found as a literal: {foreign_hits}"

    def test_no_committed_snapshot_fallback_when_base_unreachable(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """If a committed snapshot existed, an unreachable base ref could silently fall back to
        it and still catch the demotion below -- proving there is none: with no origin/main ref
        at all, the same demotion that TestKnownBadFixtures catches instead SKIPs loudly."""
        base = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=None))
        head = _manifest_src(_entry("synthetic_check_a", pre=False, full_segment=None, pre_globs=None))
        repo = _repo(tmp_path, base, head)
        _git(repo, ["update-ref", "-d", "refs/remotes/origin/main"])
        assert _run(repo) == []
        assert "SKIP" in capsys.readouterr().out

    def test_common_run_call_count_is_independent_of_domain_count(self, tmp_path_factory: pytest.TempPathFactory) -> None:
        repo_2 = _repo_with_n_domains(tmp_path_factory.mktemp("two_domains"), 2)
        repo_17 = _repo_with_n_domains(tmp_path_factory.mktemp("seventeen_domains"), 17)
        assert _count_common_run_calls(repo_2) == _count_common_run_calls(repo_17)


class TestInternalHelperEdgeCases:
    """100%-coverage closure on defensive branches none of the git-repo fixtures above reach:
    non-literal AST values, malformed manifest syntax, an out-of-range marker span, the empty-
    input short circuits, and the internal type-safety asserts weakened()/gates_deletion() carry
    (never triggerable through check_state_diff itself, since spec.state_extractor always
    returns TierState -- these are direct unit tests of the two hooks' own defensive contract)."""

    def test_str_tuple_or_none_literal_non_literal_value_returns_none(self) -> None:
        call_node = ast.parse("f()", mode="eval").body
        assert gate._str_tuple_or_none_literal(call_node) is None

    def test_marker_on_span_out_of_range_lineno_is_skipped(self) -> None:
        assert gate._marker_on_span(["a", "b"], 5, 7) == (None, None)

    def test_extract_tier_states_malformed_syntax_returns_empty(self) -> None:
        assert gate.extract_tier_states("def broken(:\n") == {}

    def test_extract_tier_states_null_byte_source_returns_empty(self) -> None:
        """ast.parse raises ValueError, not SyntaxError, on embedded null bytes."""
        assert gate.extract_tier_states("ENTRIES = ()\x00\n") == {}

    def test_extract_tier_states_ignores_calls_that_are_not_entry(self) -> None:
        assert gate.extract_tier_states("import os\n\nf = os.getcwd()\ng = len([])\n") == {}

    def test_extract_tier_states_non_literal_name_is_skipped(self) -> None:
        text = "from scripts.checks._schema import Entry\nNAME = 'x'\nENTRIES = (\n    Entry(name=NAME, pre=True),\n)\n"
        assert gate.extract_tier_states(text) == {}

    def test_weakened_rejects_non_tierstate_input(self) -> None:
        weakened = gate._make_weakened([])
        with pytest.raises(TypeError):
            weakened(1, 2)

    def test_gates_deletion_rejects_non_tierstate_input(self) -> None:
        with pytest.raises(TypeError):
            gate.gates_deletion("not a tierstate")

    def test_head_manifest_paths_missing_checks_dir_returns_empty(self, tmp_path: Path) -> None:
        assert gate._head_manifest_paths(tmp_path) == []

    def test_base_manifest_paths_non_git_directory_returns_empty(self, tmp_path: Path) -> None:
        assert gate._base_manifest_paths(tmp_path) == []

    def test_batched_base_reader_empty_paths_returns_blank_reader(self) -> None:
        reader = gate._batched_base_reader(Path("."), [])
        assert reader is not None
        assert reader("anything") == ""

    def test_batched_base_reader_failed_subprocess_returns_no_reader(self) -> None:
        """A failed `git cat-file --batch` must yield NO reader: a blank-string one is a fail-open
        (check_state_diff reads "" as "reachable base, no entries"). Stdout here is WELL-FORMED."""
        fake_result = subprocess.CompletedProcess(["git", "cat-file", "--batch"], 128, b"a blob 2\nx\n", b"fatal")
        with patch.object(_common, "run", return_value=fake_result):
            assert gate._batched_base_reader(Path("."), ["a"]) is None

    def test_batched_base_reader_truncated_output_on_a_successful_call_reads_blank(self) -> None:
        """Record robustness, NOT a fail-open: rc is zero, so a newline-less record is an empty blob."""
        with patch.object(_common, "run", return_value=subprocess.CompletedProcess(["git"], 0, b"no newline here", b"")):
            reader = gate._batched_base_reader(Path("."), ["a"])
        assert reader is not None
        assert reader("a") == ""


class TestGitProbesFailLoudNeverOpen:
    """Decision 55 on this gate's own oracles: a probe that cannot run must never degrade into one
    that runs and finds nothing. Both legs printed an affirmative PASS before this class existed."""

    def test_cat_file_failure_skips_instead_of_reading_an_empty_base(self, tmp_path: Path) -> None:
        base = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=None))
        head = _manifest_src(_entry("synthetic_check_a", pre=False, full_segment=None, pre_globs=None))
        failed, declaration = _run_with_failing_git(_repo(tmp_path, base, head), ("cat-file", "--batch"))
        assert failed == []
        assert declaration is not None and declaration.kind == "skipped"

    def test_ls_files_failure_skips_instead_of_disabling_the_coverage_leg(self, tmp_path: Path) -> None:
        """Caught by TestKnownBadFixtures with a working probe; without one, unmeasurable."""
        files = {"scripts/fake/only.py": "x = 1\n", "scripts/fake/other.py": "x = 1\n"}
        base = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=("scripts/fake/**",)))
        head = _manifest_src(_entry("synthetic_check_a", pre=True, full_segment=None, pre_globs=("scripts/fake/only.py",)))
        repo = _repo(tmp_path, base, head, extra_base=files, extra_head=files)
        failed, declaration = _run_with_failing_git(repo, ("ls-files",))
        assert failed == []
        assert declaration is not None and declaration.kind == "skipped"

    def test_an_empty_head_file_list_cannot_see_a_narrowing(self) -> None:
        """Why that SKIP is mandatory: with no head file list the measured superset degenerates to
        `set() <= set()`, so EVERY narrowing (Decision 187 point 3's bypass included) reads free."""
        assert gate._globs_narrowed(("scripts/fake/**",), ("scripts/fake/only.py",), []) is False
        assert gate._globs_narrowed(("scripts/fake/a.py",), ("never/**",), []) is False
        assert gate._globs_narrowed(("scripts/fake/a.py",), ("never/**",), ["scripts/fake/a.py"]) is True
        assert gate._globs_narrowed(("scripts/fake/a.py",), None, []) is False  # gaining ungated is a tightening


class TestCommonPathCost:
    """Decision 187 reversal c4 ("common-path cost exceeds 1s"): UNGATED in --pre, so every
    unchanged entry's cost is paid on every diff. Measured 0.884s -> 0.091s on the live tree."""

    def test_identical_globs_short_circuit_before_any_fnmatch_scan(self) -> None:
        base_globs = ("scripts/checks/**", "tests/checks/**")
        head_globs = base_globs[:1] + base_globs[1:]
        assert head_globs is not base_globs, "the short circuit must key on equality, not identity"
        with patch.object(gate, "fnmatch") as fake_fnmatch:
            assert gate._globs_narrowed(base_globs, head_globs, [f"scripts/pkg/f{i}.py" for i in range(400)]) is False
        assert fake_fnmatch.call_count == 0

    def test_differing_globs_still_measure_coverage_by_fnmatch(self) -> None:
        """Teeth: the short circuit is keyed on glob EQUALITY, not on a disabled measured leg."""
        with patch.object(gate, "fnmatch", return_value=False) as fake_fnmatch:
            gate._globs_narrowed(("scripts/checks/**",), ("scripts/checks/deps/**",), ["scripts/checks/a.py"])
        assert fake_fnmatch.call_count > 0
