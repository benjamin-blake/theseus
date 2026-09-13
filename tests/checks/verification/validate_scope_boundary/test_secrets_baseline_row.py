"""TestSecretsBaselineRow (PLAN-secrets-baseline-sanction-row): the
secrets_baseline_regeneration sanction row's scope_file_in_secrets_baseline trigger kind.

Eight arms, one per branch -- neither validate_scope_boundary.py nor this module carries a
config/coverage_baseline.yaml entry, so validate_test_coverage holds both to the 100% per-file
floor. Fixture baselines carry EMPTY results values (e.g. {"results": {"scripts/x.py": []}}) so
no fixture literal can trip the real detect-secrets hook and make this module itself a baseline
key.
"""

from __future__ import annotations

from pathlib import Path

from .conftest import _commit_all, _git, _init_repo, _write_baseline, _write_contract, _write_plan, validate_scope_boundary

_SCOPE_FILE = "scripts/foo.py"
_SCOPE = [{"file": _SCOPE_FILE, "action": "Modify", "purpose": "x"}]


def _build(
    tmp_path: Path,
    slug: str,
    base_baseline: dict[str, list] | None,
    working_baseline: dict[str, list] | None,
    working_baseline_raw: str | None = None,
    base_baseline_raw: str | None = None,
) -> tuple[Path, str]:
    """Repo builder giving independent control over the base-ref and working-tree
    `.secrets.baseline` content -- `_ResolvedFixture` writes the same content at both commits, but
    these arms need the two halves to differ. `*_raw` overrides write literal (possibly
    unparseable) text instead of a JSON-encoded results map; only one of the dict/raw pair may be
    given per half."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_contract(repo)
    _write_plan(repo, slug, _SCOPE, declared=False)
    if base_baseline_raw is not None:
        (repo / ".secrets.baseline").write_text(base_baseline_raw, encoding="utf-8")
    elif base_baseline is not None:
        _write_baseline(repo, base_baseline)
    base_sha = _commit_all(repo, "base")
    _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

    rel = _write_plan(repo, slug, _SCOPE, declared=True)
    if working_baseline_raw is not None:
        (repo / ".secrets.baseline").write_text(working_baseline_raw, encoding="utf-8")
    elif working_baseline is not None:
        _write_baseline(repo, working_baseline)
    elif (repo / ".secrets.baseline").exists():
        (repo / ".secrets.baseline").unlink()
    _commit_all(repo, "declare implementation")
    return repo, rel


class TestSecretsBaselineRow:
    def test_scope_file_is_working_tree_baseline_key_sanctioned(self, tmp_path: Path) -> None:
        """Arm 1: the scope file is a baseline results key in both halves -- sanctioned."""
        repo, rel = _build(tmp_path, "sb-secrets-positive", {_SCOPE_FILE: []}, {_SCOPE_FILE: []})
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, _SCOPE_FILE, ".secrets.baseline"], root=repo)
        assert failed == []

    def test_no_scope_file_in_baseline_not_sanctioned(self, tmp_path: Path) -> None:
        """Arm 2: the baseline exists but carries no key matching the plan's declared scope --
        NOT sanctioned, so a diff touching .secrets.baseline still STOPs."""
        repo, rel = _build(tmp_path, "sb-secrets-negative", {"scripts/unrelated.py": []}, {"scripts/unrelated.py": []})
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, _SCOPE_FILE, ".secrets.baseline"], root=repo)
        assert any(".secrets.baseline" in f and "outside declared scope" in f for f in failed)

    def test_key_only_at_base_ref_entry_removal_sanctioned(self, tmp_path: Path) -> None:
        """Arm 3: the key is present at the base ref but was removed by the working-tree
        regeneration (an entry-removal diff) -- still sanctioned via the base-ref half of the
        union."""
        repo, rel = _build(tmp_path, "sb-secrets-base-only", {_SCOPE_FILE: []}, {"scripts/unrelated.py": []})
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, _SCOPE_FILE, ".secrets.baseline"], root=repo)
        assert failed == []

    def test_key_only_in_working_tree_additive_sanctioned(self, tmp_path: Path) -> None:
        """Arm 4: an existing baseline gains the key only in the working tree (additive
        re-baselining) -- still sanctioned via the working-tree half of the union."""
        repo, rel = _build(tmp_path, "sb-secrets-working-only", {"scripts/unrelated.py": []}, {_SCOPE_FILE: []})
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, _SCOPE_FILE, ".secrets.baseline"], root=repo)
        assert failed == []

    def test_baseline_absent_from_both_derives_nothing_no_finding(self, tmp_path: Path) -> None:
        """Arm 5: no baseline at either half -- derives nothing, and since the diff never touches
        .secrets.baseline either, the whole diff is fully declared."""
        repo, rel = _build(tmp_path, "sb-secrets-absent", None, None)
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, _SCOPE_FILE], root=repo)
        assert failed == []

    def test_baseline_unparseable_in_working_tree_appends_finding(self, tmp_path: Path) -> None:
        """Arm 6: invalid JSON in the working tree appends a finding rather than raising, and at
        most once per dispatch."""
        repo, rel = _build(
            tmp_path,
            "sb-secrets-bad-working",
            {_SCOPE_FILE: []},
            None,
            working_baseline_raw="not valid json {",
        )
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, _SCOPE_FILE, ".secrets.baseline"], root=repo)
        matches = [f for f in failed if "unparseable in the working tree" in f]
        assert len(matches) == 1, failed

    def test_baseline_unparseable_at_base_ref_appends_finding(self, tmp_path: Path) -> None:
        """Arm 7: invalid JSON at the base ref appends a finding rather than raising, and at most
        once per dispatch."""
        repo, rel = _build(
            tmp_path,
            "sb-secrets-bad-base",
            None,
            {_SCOPE_FILE: []},
            base_baseline_raw="not valid json {",
        )
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, _SCOPE_FILE, ".secrets.baseline"], root=repo)
        matches = [f for f in failed if "unparseable at base ref" in f]
        assert len(matches) == 1, failed

    def test_baseline_absent_at_base_present_in_working_tree_sanctioned(self, tmp_path: Path) -> None:
        """Arm 8: `git show <base>:.secrets.baseline` returns non-zero (the file was never
        committed at base, only added in the working-tree commit) -- the base half contributes
        nothing SILENTLY (no finding), and the working-tree half alone still sanctions."""
        repo, rel = _build(tmp_path, "sb-secrets-new-file", None, {_SCOPE_FILE: []})
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, _SCOPE_FILE, ".secrets.baseline"], root=repo)
        assert failed == []
        assert not any("unparseable" in f for f in failed)
