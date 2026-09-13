"""Legacy collect-only classifier and shared heavy-dependency helpers."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from scripts.checks import _common

_DIST_TO_IMPORT_ALIASES: dict[str, str] = {
    "scikit-learn": "sklearn",
    "psycopg2-binary": "psycopg2",
    "beautifulsoup4": "bs4",
    "python-ulid": "ulid",
}
_NO_MODULE_NAMED_RE = re.compile(r"No module named ['\"]([\w.]+)['\"]")
_ERROR_COLLECTING_RE = re.compile(r"ERROR collecting (\S+)")
_SKIPPED_LINE_RE = re.compile(r"^SKIPPED\s+\[\d+\]\s+(\S+):\d+:\s*(.+)$", re.MULTILINE)
_SECTION_SEPARATOR_RE = re.compile(r"^=+.+=+$", re.MULTILINE)


def _parse_requirement_dist_names(path: Path) -> set[str]:
    """Parse a requirements file into bare distribution names."""
    names: set[str] = set()
    if not path.exists():
        return names
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        line = re.sub(r"\[[^\]]*\]", "", line)
        line = line.split(";", 1)[0].strip()
        name = re.split(r"[<>=!~]", line, maxsplit=1)[0].strip()
        if name:
            names.add(name)
    return names


def _dist_to_import_name(dist_name: str) -> str:
    return _DIST_TO_IMPORT_ALIASES.get(dist_name, dist_name.lower().replace("-", "_"))


def _excluded_heavy_import_names() -> set[str]:
    """Derive imports deliberately excluded from the fast tier's requirement delta."""
    full = _parse_requirement_dist_names(_common.ROOT / "requirements.txt")
    fast = _parse_requirement_dist_names(_common.ROOT / "requirements-fast.txt")
    return {_dist_to_import_name(dist) for dist in full - fast}


def _excluded_and_absent(missing: str | None, excluded: set[str]) -> str | None:
    """Return a deliberately excluded and genuinely absent top-level import name."""
    if not missing:
        return None
    top_level = missing.split(".")[0]
    if top_level in excluded and importlib.util.find_spec(top_level) is None:
        return top_level
    return None


def _match_changed_test_path(file_token: str, changed_tests: list[str], *, repo_root: Path = _common.ROOT) -> str | None:
    """Resolve a pytest path token back to its changed-test entry."""
    normalized = file_token.replace("\\", "/")
    for test_file in changed_tests:
        if normalized == test_file or normalized.endswith("/" + test_file):
            return test_file
        target = repo_root / test_file
        if not target.is_dir():
            continue
        candidate = repo_root / normalized
        try:
            candidate.relative_to(target)
        except ValueError:
            continue
        if candidate.is_file() and candidate.name.startswith("test_") and candidate.suffix == ".py":
            return candidate.relative_to(repo_root).as_posix()
    return None


def _expand_directory_test_targets(targets: list[str]) -> list[str]:
    """Defensively normalize any legacy directory target to individual test modules."""
    expanded: list[str] = []
    for target in targets:
        path = _common.ROOT / target
        if not path.is_dir():
            expanded.append(target)
            continue
        expanded.extend(
            test_file.relative_to(_common.ROOT).as_posix()
            for test_file in sorted(path.rglob("test_*.py"))
            if "__pycache__" not in test_file.parts and test_file.is_file()
        )
    return list(dict.fromkeys(expanded))


def _attribute_batched_collect_errors(combined: str, changed_tests: list[str], excluded: set[str]) -> dict[str, str]:
    """Attribute each heavy-dependency collection error or skip to its own test file."""
    deferred: dict[str, str] = {}
    headers = list(_ERROR_COLLECTING_RE.finditer(combined))
    for index, header in enumerate(headers):
        file_token = header.group(1)
        next_start = headers[index + 1].start() if index + 1 < len(headers) else len(combined)
        separator = _SECTION_SEPARATOR_RE.search(combined, header.end(), next_start)
        block = combined[header.end() : separator.start() if separator else next_start]
        matches = _NO_MODULE_NAMED_RE.findall(block)
        missing = _excluded_and_absent(matches[-1], excluded) if matches else None
        matched_file = _match_changed_test_path(file_token, changed_tests)
        if matched_file and missing:
            deferred[matched_file] = missing
    for skip_match in _SKIPPED_LINE_RE.finditer(combined):
        file_token, reason = skip_match.group(1), skip_match.group(2)
        matches = _NO_MODULE_NAMED_RE.findall(reason)
        missing = _excluded_and_absent(matches[-1], excluded) if matches else None
        matched_file = _match_changed_test_path(file_token, changed_tests)
        if matched_file and missing and matched_file not in deferred:
            deferred[matched_file] = missing
    return deferred


def partition_changed_tests_by_collectability(changed_tests: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """Retain the frozen batched collect-only classifier surface for compatibility."""
    if not changed_tests:
        return [], []
    excluded = _excluded_heavy_import_names()
    result = _common.run(
        [_common.PYTHON, "-m", "pytest", "--collect-only", "-q", "-rs", *changed_tests, "-m", "not integration"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_common.ROOT,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    deferred_map = _attribute_batched_collect_errors(combined, changed_tests, excluded)
    runnable = [test_file for test_file in changed_tests if test_file not in deferred_map]
    deferred = [(test_file, deferred_map[test_file]) for test_file in changed_tests if test_file in deferred_map]
    return runnable, deferred
