"""Recall channels for the --pre affected-set derivation (Decision 135's strictly-additive union).

Sibling of affected_tests.py, which owns the derivation and the cap; this module owns the three
channels added to close the measured "no-edge" escape class -- 32 of 32 mechanically classified
post-merge escapes in the 60-day window were `no-edge` (the diff-aware selection had no edge to
follow at all) and 0 were `capped`, so the gap is in the channels, never the budget.

  * EXTRA-TREE .py CANDIDATES (is_extra_tree_py) -- a changed .py outside src/|scripts/|tests/
    (setup.py, .claude/hooks/*.py, .claude/statusline.py) is invisible to the import graph AND
    was skipped outright by the data-edge candidate filter, so it selected ZERO tests. Its
    mirror tests do quote its basename (tests/test_edit_scope_guard.py literally contains
    "edit_scope_guard.py"), so admitting it as a data-edge candidate is all that is needed.
  * PROSE-MENTION EDGES (mention_pattern) -- a word-boundary basename occurrence ANYWHERE in a
    test's text (docstring, comment, prose) counts, not only a whole quoted string. The
    quoted-string requirement is what made the rec-2548 cluster escape: the test that reads
    source_registry.yaml names it only in a docstring.
  * DIRECTORY-REFERENCE EDGES (new_file_reference_dirs / directory_reference_pattern) -- a file
    that did not exist before cannot be quoted anywhere, so every precise channel is empty BY
    CONSTRUCTION for an addition. The tests that will exercise it are the validators' mirror
    tests that glob-scan the containing directory, and those reference the DIRECTORY. DELETIONS
    ride the same channel for the same reason -- a retired file changes what a glob-scanning
    validator observes exactly as much as a new one does, and the precise channels reach only
    the tests that still name the departed path, never the ones that name its directory
    (measured: retiring one .github/workflows/*.yml selected 2 test modules where adding one
    selected 16). Its precision guarantees, in BOTH the plain-literal ("docs/contracts") and the
    pathlib segment-join ("docs" / "contracts") spellings: a reference to a SPECIFIC FILE inside
    the directory is not a reference to the directory, and neither is a nested sibling. A
    single-segment root (`config`) additionally demands an explicit path context, because the
    bare word is also an ordinary identifier -- see _SINGLE_SEGMENT_CONTEXT.

All three feed the protected (never-capped) set: Decision 135 permits capping only the
transitive import-closure residue, and none of these is transitive residue.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path, PurePosixPath

# Curated roots whose contents are GLOB-SCANNED by a validator, so that adding OR removing one
# file changes what an existing directory-counting test observes. Evidence (ci-failure recon,
# 60-day window): .github/workflows -- the test_real_workflows_dir cluster, 7 recs on one added
# workflow file; docs/contracts and config -- both measured at ZERO selected tests for a synthetic
# addition while carrying glob-scanning validators. `config` is the only SINGLE-SEGMENT entry and
# is kept on a re-measured, narrower basis: the structural size-governance class engine globs
# `config/*.yaml`, so a config/-root addition genuinely lands in its three test modules -- but
# only _SINGLE_SEGMENT_CONTEXT makes that signal separable from the 62 modules that merely use
# the WORD config. docs/plans is deliberately EXCLUDED: plan YAMLs are added on nearly every PR
# and validate_plan_documents is already pre_globs-gated on them, so the channel would cost ~15
# test modules per plan PR for no measured recall.
GLOB_SCANNED_DIRS: tuple[str, ...] = (".github/workflows", "docs/contracts", "config")

_FIRST_PARTY_TREES = ("src/", "scripts/", "tests/")

# Statuses that change a directory's MEMBERSHIP, which is what a glob-scanning validator counts:
# an addition (tracked or untracked) and a deletion. "M" is deliberately absent -- an in-place
# edit leaves membership untouched and is already carried by the precise path/basename channels.
_MEMBERSHIP_CHANGING = ("A", "??", "D")

# A path separator as written in Python source: either a literal "/" inside one string, or the
# pathlib segment-join idiom `"a" / "b"` -- the real escaping test writes ROOT / ".github" /
# "workflows", so a plain-literal scan misses exactly the case this channel exists for.
_PATH_SEP = r"(?:/|['\"]\s*/\s*['\"])"

# A directory reference ENDS where a file reference would continue. Both halves are LOOKAHEADS so
# they compose on the same position: the first accepts the delimiters a directory literal may end
# on (a quote, a closing bracket, whitespace, a `/*` glob, a trailing-slash `"config/"`), and the
# second rejects a segment-join CONTINUATION. Without that second half a closing quote terminates
# the match, so `"docs" / "contracts" / "check-manifest.yaml"` and `"docs/contracts" / "x.yaml"`
# -- both readers of ONE file -- would drag in the whole directory.
_DIR_TERMINATOR = r"(?=['\"\)\s,\]:]|/\*|/['\"]|$)(?!['\"]\s*/)"

# The mirror guard on the LEADING side: the match must be the FIRST segment of its path
# expression, so `ROOT / "x" / "docs" / "contracts"` is the nested sibling x/docs/contracts and
# `root / "docs" / "config"` is docs/config -- exactly what the plain-literal form's path-boundary
# lookbehind already rejects. Python's re admits no variable-width lookbehind, so _PATH_SEP's
# `['\"]\s*/\s*['\"]` is spelled out as the four fixed-width forms its `\s*` can produce under
# ruff format (zero or one space either side of the `/`).
_NOT_A_LATER_SEGMENT = r"(?<!['\"]/['\"])(?<!['\"]\s/['\"])(?<!['\"]/\s['\"])(?<!['\"]\s/\s['\"])"

# A SINGLE-SEGMENT root (`config`) collides with the ordinary identifier and the ordinary English
# word of the same name, so it demands an explicit path context: `config/` continuing into a glob
# or closing the literal. Measured, the bare form put 67 test modules -- `_git(["config", ...])`
# subcommand strings, `tmp_path / "config"` fixture trees, prose -- into the never-capped
# PROTECTED set for one added config/ file, against 5 with this context requirement. The pathlib
# spelling `X / "config"` is deliberately NOT accepted here: it is byte-identical to the
# `tmp_path / "config"` fixture idiom (16 of the 67), and every measured genuine scanner of the
# config/ root -- the structural size-governance class engine's three test modules -- spells it
# `config/*.yaml`. Multi-segment roots are unambiguous and keep the full _DIR_TERMINATOR grammar.
_SINGLE_SEGMENT_CONTEXT = r"(?=/(?:\*|['\"]))"


def is_extra_tree_py(path: str) -> bool:
    """A .py file outside src/|scripts/|tests/ -- no graph node, no mirror-map entry, no
    conftest channel; its only edge to a test is textual."""
    return path.endswith(".py") and not path.startswith(_FIRST_PARTY_TREES)


def mention_pattern(basename: str) -> re.Pattern[str]:
    """Word-boundary basename occurrence anywhere in a text.

    A path prefix is allowed to precede it (so a docstring naming the full relative path of a
    same-named file in another directory still matches), but a word character, '-' or '.' may
    not: 'registry.yaml' must not match inside 'source_registry.yaml'. A trailing '.' IS
    allowed, because prose ends sentences with one.
    """
    return re.compile(r"(?<![\w.\-])" + re.escape(basename) + r"(?![\w\-])")


def directory_reference_pattern(dir_path: str) -> re.Pattern[str]:
    """Match `dir_path` written as a DIRECTORY, in either the plain-literal ("docs/contracts") or
    the pathlib segment-join ("docs" / "contracts") form.

    Never matches a SPECIFIC FILE inside it ("docs/contracts/check-manifest.yaml", or its
    segment-join spelling), never a nested sibling ("config/agentic", `ROOT / "x" / "docs" /
    "contracts"`), and -- for a single-segment root -- never the ordinary identifier of the same
    name (`config = {}`, `_git(["config", "user.email"])`, prose).
    """
    segments = [re.escape(p) for p in dir_path.split("/")]
    if len(segments) == 1:
        return re.compile(_NOT_A_LATER_SEGMENT + r"(?<![\w./\-])" + segments[0] + _SINGLE_SEGMENT_CONTEXT)
    return re.compile(_NOT_A_LATER_SEGMENT + r"(?<![\w./\-])" + _PATH_SEP.join(segments) + _DIR_TERMINATOR)


def new_file_reference_dirs(entries: Iterable[tuple[str, str]]) -> list[str]:
    """Directories to scan for directory-reference edges: the parent of every non-.py file whose
    diff status CHANGES that directory's membership -- an addition (A/untracked) or a deletion
    (D) -- and that sits at or below a curated glob-scanned root. (The name is the channel's
    founding case; a retirement opens the identical edge, see the module docstring.)

    The parent, not the root, so `config/agent/data_quality/x.yaml` matches the tests that scan
    that leaf directory rather than every test that mentions `config`.
    """
    dirs: set[str] = set()
    for status, path in entries:
        if status not in _MEMBERSHIP_CHANGING or path.endswith(".py"):
            continue
        parent = PurePosixPath(path).parent.as_posix()
        if any(parent == root or parent.startswith(root + "/") for root in GLOB_SCANNED_DIRS):
            dirs.add(parent)
    return sorted(dirs)


def scan_test_texts(repo_root: Path) -> Iterator[tuple[str, str]]:
    """Yield (repo-relative posix path, text) for every readable tests/**/*.py, in sorted order.

    One shared read for every text channel -- reading the 653-file, 7 MB tests tree once costs
    ~0.15 s, and doing it per-channel would multiply that against the fast tier's budget.
    """
    tests_dir = repo_root / "tests"
    if not tests_dir.is_dir():
        return
    for path in sorted(tests_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        yield path.relative_to(repo_root).as_posix(), text


def scan_reference_channels(
    repo_root: Path,
    *,
    path_literals: Sequence[str],
    quoted_patterns: Sequence[re.Pattern[str]],
    mention_basenames: Sequence[str],
    directory_paths: Sequence[str],
) -> tuple[set[str], set[str], set[str]]:
    """One pass over tests/**/*.py: returns (precise, mention, directory_reference) hit sets.

    `precise` and `mention` are disjoint -- a file that matches precisely is attributed there and
    is not re-reported as a weaker mention hit. `directory_reference` is independent and may
    overlap either (the caller resolves provenance precedence).

    The substring pre-filter in front of each mention regex is load-bearing for the budget: `in`
    is a C-level scan, and it is negative for nearly every (candidate, test file) pair.
    """
    mention_patterns = {name: mention_pattern(name) for name in mention_basenames}
    # Every directory form the regex accepts still ends in the literal last path component, so
    # that component's presence is a necessary condition -- the same C-level pre-filter the
    # mention channel uses, applied to a pattern whose alternation makes it the costlier of the two.
    dir_patterns = [(d.rsplit("/", 1)[-1], directory_reference_pattern(d)) for d in directory_paths]
    precise: set[str] = set()
    mention: set[str] = set()
    directory: set[str] = set()
    for rel_test, text in scan_test_texts(repo_root):
        if any(literal in text for literal in path_literals) or any(p.search(text) for p in quoted_patterns):
            precise.add(rel_test)
        elif any(name in text and mention_patterns[name].search(text) for name in mention_basenames):
            mention.add(rel_test)
        if any(leaf in text and pattern.search(text) for leaf, pattern in dir_patterns):
            directory.add(rel_test)
    return precise, mention, directory
