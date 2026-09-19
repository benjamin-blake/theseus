"""Sole home for VP-command shape analysis (docs/contracts/vp-red-before.yaml's carrier_rule,
self_satisfying_lint, and unsat_guard sections -- this module holds no second copy of that prose).

Holds three things that used to live in two different modules, plus one new hard-failing guard:

- The backtick-literal extractor relocated verbatim from
  scripts.checks.verification.validate_vp_replay._extract_literals.
- The general shell-command tokenizer relocated verbatim from
  scripts.roadmap.plan_document._partition_command (Decision 104 sole-home: a second
  shlex-based tokenizer inside this package would be the violation this relocation exists to
  avoid). Both plan_document and this module's own guard use ONE tokenizer.
- The ADVISORY self-satisfying lint: a literal that appears verbatim in its OWN command's text is
  redundant with that command's exit-0 (the command already names the token as one of its own
  arguments) -- reported, never rejected, so the repo's marker idiom (``echo MARKER``,
  ``grep -o -m1 TOKEN FILE``) stays authorable. Named ``self_satisfying``, deliberately never
  ``tautological`` -- that word is reserved by docs/contracts/vp-red-before.yaml#outcome_classes
  for the DYNAMIC replay outcome vocabulary; reusing it here for an unrelated STATIC property
  would be drift in the same contract file.
- The hard-failing unsatisfiable-command guard: a NARROW regression guard for one historical
  shape (PLAN-g4-byte-source-and-post-expiry-bound's original VP1, PR #1202) -- a chain of
  grep/rg invocations joined by shell control operators where EVERY invocation is confidently
  silenced (``-q``/``-c``/``-l``/``-L`` without an overriding ``-o``, or output redirected to
  ``/dev/null``) can never print a matched literal to stdout+stderr no matter how correct the
  implementation is. It fails OPEN on anything it cannot confidently classify (an unparseable
  segment, a non-grep/rg program) -- this guard does not attempt to reason about arbitrary output
  producers like ``python -c`` or module invocations; see the carrying plan's own measurement
  (86% of the enforced population resists a closed command vocabulary) for why that is a
  deliberate scope limit, not an oversight.
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path

import yaml

_BACKTICK_LITERAL_RE = re.compile(r"`([^`]+)`")

# pytest arguments whose VALUE names something the run will NOT execute (relocated verbatim
# alongside _partition_command -- plan_document._validate_test_obligation_links is the sole
# caller of this exclusion-flag vocabulary).
_EXCLUSION_FLAGS: frozenset[str] = frozenset({"--ignore", "--ignore-glob", "--deselect"})

_SHELL_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;|]")
_GREP_RG_BASENAMES = frozenset({"grep", "rg"})
_SILENCING_FLAGS = frozenset({"-q", "--quiet", "-c", "--count", "-l", "--files-with-matches", "-L", "--files-without-match"})
_UNSILENCING_FLAGS = frozenset({"-o", "--only-matching"})
_DEV_NULL_REDIRECT_RE = re.compile(r"[>&]\s*/dev/null")

# The suppressor set this guard treats as confidently silencing a grep/rg invocation -- declared
# here as the code's own tuple and asserted equal to docs/contracts/vp-red-before.yaml's copy
# (TestContractSuppressorParity), so the contract cannot drift from the code.
SUPPRESSOR_FLAGS: tuple[str, ...] = tuple(sorted(_SILENCING_FLAGS))


def _partition_command(command: str) -> tuple[list[str], list[str]]:
    """Split a shell command into (selectable arguments, explicitly excluded values).

    Relocated verbatim from scripts.roadmap.plan_document (Decision 104 sole-home) -- plan_document
    imports this back rather than keeping its own copy.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    selectable: list[str] = []
    excluded: list[str] = []
    pending_exclusion = False
    for token in tokens:
        if pending_exclusion:
            excluded.append(token)
            pending_exclusion = False
            continue
        flag, separator, value = token.partition("=")
        if flag in _EXCLUSION_FLAGS:
            if separator:
                excluded.append(value)
            else:
                pending_exclusion = True
            continue
        selectable.append(token)
    return selectable, excluded


def _extract_literals(expected: str) -> list[str]:
    """Every backtick-delimited literal in a VP step's `expected` field -- relocated verbatim
    from validate_vp_replay._extract_literals, the schema_version-4-and-below carrier."""
    return _BACKTICK_LITERAL_RE.findall(expected)


# The static verdict name a self-satisfying finding carries -- deliberately NEVER "tautological",
# which docs/contracts/vp-red-before.yaml#outcome_classes reserves for the four DYNAMIC replay
# outcome classes (a fifth, unrelated STATIC property reusing that word would be drift in the
# same contract file).
SELF_SATISFYING_VERDICT = "self_satisfying"


def find_self_satisfying_literals(command: str, literals: list[str]) -> list[str]:
    """The subset of `literals` that appear verbatim in `command`'s own text -- redundant with
    that command's exit-0, since the command already names the token as one of its own
    arguments. ADVISORY: the caller reports these, never rejects them."""
    return [literal for literal in literals if literal and literal in command]


def _segment_tokens(command: str) -> list[list[str]]:
    """Tokenize each shell-control-operator-delimited segment of `command`. An unparseable
    segment is dropped, never raised -- fails open, matching the sibling lints in
    docs/contracts/vp-red-before.yaml."""
    segments: list[list[str]] = []
    for raw in _SHELL_SEGMENT_SPLIT_RE.split(command or ""):
        raw = raw.strip()
        if not raw:
            continue
        try:
            segments.append(shlex.split(raw))
        except ValueError:
            continue
    return segments


def _segment_is_confidently_silent(tokens: list[str]) -> bool:
    """True iff this segment is a grep/rg invocation this guard can PROVE prints no matched text.
    False covers both "provably prints text" and "cannot tell" (fail open toward satisfiable)."""
    if not tokens:
        return False
    head = tokens[0].rsplit("/", 1)[-1]
    if head not in _GREP_RG_BASENAMES:
        return False
    flags = {tok for tok in tokens[1:] if tok.startswith("-")}
    if flags & _UNSILENCING_FLAGS:
        return False
    if flags & _SILENCING_FLAGS:
        return True
    if _DEV_NULL_REDIRECT_RE.search(" ".join(tokens)):
        return True
    return False


def command_is_output_suppressed(command: str) -> bool:
    """True iff EVERY segment of `command` is a confidently-silent grep/rg invocation -- the
    all-suppressed-chain shape this guard exists to catch (four ``grep -q`` calls chained with
    ``&&``, PLAN-g4-byte-source-and-post-expiry-bound's original VP1). Fails OPEN: a command with
    no segments, or with any segment this can't prove silent (a non-grep/rg program, an
    unparseable segment, or a grep/rg call carrying ``-o``), is treated as satisfiable."""
    segments = _segment_tokens(command)
    if not segments:
        return False
    return all(_segment_is_confidently_silent(tokens) for tokens in segments)


def find_unsatisfiable_literals(command: str, literals: list[str]) -> list[str]:
    """The subset of `literals` that cannot be satisfied because `command`'s entire chain is
    output-suppressed. Empty when `literals` is empty or the command can emit text."""
    if not literals or not command_is_output_suppressed(command):
        return []
    return list(literals)


def select_literals(step, schema_version: int) -> list[str]:
    """This step's assertion carrier, selected by the plan's schema_version (docs/contracts/
    vp-red-before.yaml#carrier_rule): schema_version 5 declares ``expected_literals`` directly;
    schema_version 4-and-below keeps the byte-identical backtick-in-``expected`` scan. The sole
    call site for both ``validate_vp_replay``'s green/red replay legs."""
    if schema_version >= 5:
        return list(step.expected_literals or [])
    return _extract_literals(step.expected)


def format_literal_print(plan_rel: str, step_number: int, literals: list[str], schema_version: int) -> str:
    """One printable line naming a graduate step's selected literal carrier -- the red-before
    leg's per-step audit print, sited after its eligibility filter (never at the unconditional
    DEFER line)."""
    return f"  LITERALS: {plan_rel}:{step_number} expected_literals={literals!r} (schema_version {schema_version})"


def _iter_hermetic_pre_deploy_steps_with_literals(plans_dir: Path):
    """Yield (plan_name, step_number, command, literals, graduation) for every pre-deploy,
    hermetic step across docs/plans/PLAN-*.yaml whose expected field carries >=1 backtick
    literal -- read as plain YAML (never through the strict PlanDocument loader), mirroring
    plan_obligations.py's read-only-plain-YAML posture so a malformed sibling plan never aborts
    the census."""
    for path in sorted(plans_dir.glob("PLAN-*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        for step in data.get("verification_plan") or []:
            if not isinstance(step, dict):
                continue
            if step.get("phase") != "pre-deploy" or not step.get("hermetic"):
                continue
            literals = _extract_literals(step.get("expected") or "")
            if not literals:
                continue
            yield path.name, step.get("step"), step.get("command") or "", literals, step.get("graduation")


def run_census(plans_dir: Path) -> None:
    """Print the live corpus split (self-satisfying / unsat-guard-flagged / residual) so the
    contract's declared unenforced-residual arm is grounded in a measured number, not an asserted
    one. A one-shot measurement tool -- VP step 6 (TestV4CorpusInvariance) is the standing
    invariance guarantee, this is only its quantification."""
    total_steps = 0
    total_literals = 0
    self_satisfying = 0
    unsat = 0
    residual = 0
    for _name, _step_no, command, literals, _graduation in _iter_hermetic_pre_deploy_steps_with_literals(plans_dir):
        total_steps += 1
        total_literals += len(literals)
        for literal in literals:
            if literal in command:
                self_satisfying += 1
            elif command_is_output_suppressed(command):
                unsat += 1
            else:
                residual += 1
    print(
        f"CENSUS steps={total_steps} literals={total_literals} self_satisfying={self_satisfying} "
        f"unsat={unsat} residual={residual}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VP-command shape analysis (vp_literals) CLI")
    parser.add_argument("--census", metavar="PLANS_DIR", help="Print the live corpus literal-class split for PLANS_DIR")
    args = parser.parse_args(argv)
    if args.census:
        run_census(Path(args.census))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
