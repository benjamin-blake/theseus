"""rec-4077 acceptance module: python-ulid fast-tier floor parity, plus an executable guard on
requirements-fast.txt's declaration rule (Decision 163: prose parity rule -> enforced by code).

TestUlidInFastTier proves python-ulid is a declared requirements-fast.txt floor matching
requirements.in's specifier and is no longer in the excluded-heavy-import set (see
tests/validate/test_pytest_diff.py's TestExcludedHeavyDeps, inverted alongside this module).

TestFastTierDependencyParity is a module-private pure helper computing parity violations from
three requirements files (requirements.in, requirements-dev.in, requirements-fast.txt) and the
declared `# heavy-exclusion: <dist> -- <reason>` lines: the OMISSION set is derived via
scripts.checks._pytest_diff._parse_requirement_dist_names -- the same parser
_excluded_heavy_import_names() consumes, so this guard checks exactly the set the fast tier's
reactive heavy-dep path acts on -- and the SPECIFIERS are derived via
scripts.import_governance.parse_declared_requirements (skips requirements-dev.in's
`-c requirements.txt` option line correctly). Names are normalized identically on both sides via
packaging.utils.canonicalize_name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from scripts.checks._pytest_diff import _excluded_heavy_import_names, _parse_requirement_dist_names
from scripts.import_governance import parse_declared_requirements

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS_IN = ROOT / "requirements.in"
REQUIREMENTS_DEV_IN = ROOT / "requirements-dev.in"
REQUIREMENTS_FAST_TXT = ROOT / "requirements-fast.txt"
REQUIREMENTS_TXT = ROOT / "requirements.txt"

_HEAVY_EXCLUSION_RE = re.compile(r"^#\s*heavy-exclusion:\s*(\S+)\s+--\s+(.+)$")


def _by_canonical_name(declared: dict[str, Requirement]) -> dict[str, Requirement]:
    return {canonicalize_name(requirement.name): requirement for requirement in declared.values()}


class TestUlidInFastTier:
    def test_python_ulid_floor_declared(self) -> None:
        source_by_name = _by_canonical_name(parse_declared_requirements([REQUIREMENTS_IN])[0])
        fast_by_name = _by_canonical_name(parse_declared_requirements([REQUIREMENTS_FAST_TXT])[0])
        assert "python-ulid" in fast_by_name, "requirements-fast.txt must declare a python-ulid floor"
        assert str(fast_by_name["python-ulid"].specifier) == str(source_by_name["python-ulid"].specifier), (
            "requirements-fast.txt's python-ulid specifier must match requirements.in's"
        )

    def test_ulid_not_in_excluded_heavy_imports(self) -> None:
        assert "ulid" not in _excluded_heavy_import_names()

    def test_fast_floor_admits_the_compiled_pin(self) -> None:
        fast_by_name = _by_canonical_name(parse_declared_requirements([REQUIREMENTS_FAST_TXT])[0])
        compiled_by_name = _by_canonical_name(parse_declared_requirements([REQUIREMENTS_TXT])[0])
        fast_req = fast_by_name["python-ulid"]
        compiled_req = compiled_by_name["python-ulid"]
        pinned_version = next(iter(compiled_req.specifier)).version
        assert fast_req.specifier.contains(pinned_version), (
            f"requirements-fast.txt's python-ulid specifier {fast_req.specifier} does not admit "
            f"the compiled pin {pinned_version} in requirements.txt"
        )


def _heavy_exclusion_declarations(requirements_fast_path: Path) -> dict[str, str]:
    """Parse `# heavy-exclusion: <dist> -- <reason>` lines into {canonical dist name: reason}."""
    declarations: dict[str, str] = {}
    for raw_line in requirements_fast_path.read_text(encoding="utf-8").splitlines():
        match = _HEAVY_EXCLUSION_RE.match(raw_line.strip())
        if match:
            declarations[canonicalize_name(match.group(1))] = match.group(2).strip()
    return declarations


@dataclass(frozen=True)
class _ParityViolations:
    undeclared_omissions: tuple[str, ...]
    drifted_floors: tuple[tuple[str, str, str], ...]


def _compute_parity_violations(
    requirements_in_path: Path,
    requirements_dev_in_path: Path,
    requirements_fast_path: Path,
) -> _ParityViolations:
    """Pure computation of the two parity-violation shapes the guard reports: an OMITTED dist
    with no heavy-exclusion reason, and a shared floor whose specifier drifted from its source."""
    full_dists = _parse_requirement_dist_names(requirements_in_path)
    fast_dists = _parse_requirement_dist_names(requirements_fast_path)
    omitted = {canonicalize_name(dist) for dist in full_dists - fast_dists}
    declared = _heavy_exclusion_declarations(requirements_fast_path)
    undeclared = tuple(sorted(name for name in omitted if not declared.get(name)))

    source_by_name = _by_canonical_name(parse_declared_requirements([requirements_in_path, requirements_dev_in_path])[0])
    fast_by_name = _by_canonical_name(parse_declared_requirements([requirements_fast_path])[0])

    drifted: list[tuple[str, str, str]] = []
    for name, fast_req in fast_by_name.items():
        source_req = source_by_name.get(name)
        if source_req is not None and str(source_req.specifier) != str(fast_req.specifier):
            drifted.append((name, str(fast_req.specifier), str(source_req.specifier)))
    return _ParityViolations(undeclared_omissions=undeclared, drifted_floors=tuple(sorted(drifted)))


class TestFastTierDependencyParity:
    """Executable form of requirements-fast.txt's header declaration rule (Decision 163): every
    requirements.in omission is declared on a heavy-exclusion line with a non-empty reason, and
    every shared floor matches its requirements.in / requirements-dev.in source specifier
    exactly."""

    def test_every_omission_is_declared_with_a_reason(self) -> None:
        violations = _compute_parity_violations(REQUIREMENTS_IN, REQUIREMENTS_DEV_IN, REQUIREMENTS_FAST_TXT)
        assert violations.undeclared_omissions == (), (
            "requirements.in distribution(s) omitted from requirements-fast.txt with no "
            f"'# heavy-exclusion:' reason: {violations.undeclared_omissions}"
        )
        declared = _heavy_exclusion_declarations(REQUIREMENTS_FAST_TXT)
        fast_dists = {canonicalize_name(dist) for dist in _parse_requirement_dist_names(REQUIREMENTS_FAST_TXT)}
        overlapping = sorted(name for name in declared if name in fast_dists)
        assert not overlapping, f"declared heavy-exclusion(s) also present as a requirement line: {overlapping}"
        for name, reason in declared.items():
            assert reason, f"heavy-exclusion line for {name} has an empty reason"

    def test_shared_floors_match_their_source(self) -> None:
        violations = _compute_parity_violations(REQUIREMENTS_IN, REQUIREMENTS_DEV_IN, REQUIREMENTS_FAST_TXT)
        assert violations.drifted_floors == (), (
            f"requirements-fast.txt floor(s) whose specifier drifted from their source: {violations.drifted_floors}"
        )

    def test_undeclared_omission_is_reported_by_dist_name(self, tmp_path: Path) -> None:
        req_in = tmp_path / "requirements.in"
        req_in.write_text("widget>=1.0\n", encoding="utf-8")
        req_dev_in = tmp_path / "requirements-dev.in"
        req_dev_in.write_text("-c requirements.txt\n", encoding="utf-8")
        req_fast = tmp_path / "requirements-fast.txt"
        req_fast.write_text("# no widget floor, no heavy-exclusion line\n", encoding="utf-8")

        violations = _compute_parity_violations(req_in, req_dev_in, req_fast)
        assert violations.undeclared_omissions == ("widget",)
        assert violations.drifted_floors == ()

    def test_drifted_floor_is_reported_with_both_specifiers(self, tmp_path: Path) -> None:
        req_in = tmp_path / "requirements.in"
        req_in.write_text("widget>=1.0\n", encoding="utf-8")
        req_dev_in = tmp_path / "requirements-dev.in"
        req_dev_in.write_text("-c requirements.txt\n", encoding="utf-8")
        req_fast = tmp_path / "requirements-fast.txt"
        req_fast.write_text("# heavy-exclusion: unrelated -- not present here\nwidget>=2.0\n", encoding="utf-8")

        violations = _compute_parity_violations(req_in, req_dev_in, req_fast)
        assert violations.undeclared_omissions == ()
        assert violations.drifted_floors == (("widget", ">=2.0", ">=1.0"),)
