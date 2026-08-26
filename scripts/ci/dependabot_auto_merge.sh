#!/usr/bin/env bash
# Policy engine for .github/workflows/dependabot-auto-merge.yml (WS2). This script -- not the
# workflow -- is the single source of the auto-merge policy, so the policy is directly testable
# (tests/test_dependabot_auto_merge_wiring.py) and the workflow step stays a one-line delegate
# (Decision 162 R1/R3, config/composite_action_body_baseline.yaml r3_workflows).
#
# ERREXIT: the workflow step declares no `shell:` key, so GitHub runs the step body as
# "bash --noprofile --norc -e -o pipefail {0}" -- but that body spawns a CHILD bash to run this
# file, and a child bash does not inherit its parent's shell options (SHELLOPTS is unexported).
# This script therefore runs WITHOUT inherited errexit, so every gh call site checks its own exit
# status below. `set +e` is retained as defence-in-depth against a future re-inlining of this body
# back into the workflow step (where -e WOULD apply); it is not the load-bearing mechanism. Same
# derivation as scripts/ci/pr_conflict_signal.sh's header.
#
# WHY EACH GATE EXISTS:
#   1. Update type. Only patch and minor bumps are auto-merged. A major bump is a real
#      behaviour-change risk (an exact GitHub Actions major, or a pip floor crossing a breaking
#      release), and dependabot's minor-and-patch groups mean majors always arrive as their own
#      ungrouped PR -- they are left for human review and for the dependabot-stranded sweep to
#      surface. An empty update type means fetch-metadata could not classify the bump, which is
#      indistinguishable from "unknown risk" and is treated the same way.
#   2. Denylist. duckdb / DuckLake versions are under an SSOT lockstep regime (the client pin and
#      the catalog version must move together), so a bump of either is never a standalone
#      auto-merge candidate regardless of its semver class.
#   3. Arm auto-merge. `gh pr merge --auto --squash` only ARMS GitHub-native auto-merge; the
#      main-protection ruleset's required checks (pr-validate + terraform-validate) still gate the
#      merge itself, and a CODEOWNERS-protected path simply holds the armed PR until its code owner
#      approves. A terminal failure here (e.g. the repo-level "Allow auto-merge" toggle is off)
#      exits non-zero so it is visible in the Actions tab rather than silently doing nothing.
#
# Contract with dependabot-auto-merge.yml: cwd is the repo root; UPDATE_TYPE, DEPENDENCY_NAMES,
# PACKAGE_ECOSYSTEM, PR_URL, PR_NUMBER and GH_TOKEN are set in the step's env: block.

set -uo pipefail
set +e

_ALLOWED_PATCH_UPDATE="version-update:semver-patch"
_ALLOWED_MINOR_UPDATE="version-update:semver-minor"

# SSOT lockstep dependencies -- see gate 2 above.
_DENIED_DEPENDENCIES="duckdb ducklake"

_MERGE_ATTEMPTS=3
_MERGE_RETRY_SLEEP="${DEPENDABOT_AUTO_MERGE_RETRY_SLEEP:-2}"

UPDATE_TYPE="${UPDATE_TYPE:-}"
DEPENDENCY_NAMES="${DEPENDENCY_NAMES:-}"
PACKAGE_ECOSYSTEM="${PACKAGE_ECOSYSTEM:-}"
PR_URL="${PR_URL:-}"
PR_NUMBER="${PR_NUMBER:-}"

# Every gate decision is mirrored to $GITHUB_STEP_SUMMARY so the reason a PR was or was not armed
# is operator-observable from the run page, not buried in the step log (Decision 155 marker shape,
# mirroring scripts/ci/pr_conflict_signal.sh's _signal_failure).
_decision() {
  local msg="[DEPENDABOT-AUTO-MERGE] $1"
  echo "$msg"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '\n## dependabot-auto-merge\n\nPR #%s (%s): %s\n' "$PR_NUMBER" "$PACKAGE_ECOSYSTEM" "$1" >> "$GITHUB_STEP_SUMMARY"
  fi
}

_signal_failure() {
  local msg="[DEPENDABOT-AUTO-MERGE] FAILURE: $1"
  echo "$msg" >&2
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '\n## dependabot-auto-merge FAILURE\n\n%s\n' "$msg" >> "$GITHUB_STEP_SUMMARY"
  fi
}

# Comma-, newline- or whitespace-separated (grouped PRs carry several names). Matching is
# case-insensitive and per token; a token merely CONTAINING a denied name is denied too, because
# over-denying only costs a human review while under-denying breaks the lockstep invariant.
_denied_dependency() {
  local names token denied
  names=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr ',;\n\r\t' '     ')
  for token in $names; do
    for denied in $_DENIED_DEPENDENCIES; do
      case "$token" in
        *"$denied"*)
          printf '%s' "$token"
          return 0
          ;;
      esac
    done
  done
  return 1
}

if [ "$UPDATE_TYPE" != "$_ALLOWED_PATCH_UPDATE" ] && [ "$UPDATE_TYPE" != "$_ALLOWED_MINOR_UPDATE" ]; then
  _decision "update-type '${UPDATE_TYPE:-<empty>}' is not patch or minor -- left for human review / stranded-sweep."
  exit 0
fi

denied_token=$(_denied_dependency "$DEPENDENCY_NAMES")
denied_rc=$?

if [ "$denied_rc" -eq 0 ]; then
  _decision "dependency '${denied_token}' is an SSOT lockstep dependency, never auto-merged -- left for human review."
  exit 0
fi

if [ -z "$PR_URL" ]; then
  _signal_failure "PR_URL is empty; cannot arm auto-merge for PR #${PR_NUMBER:-<unknown>}."
  exit 1
fi

attempt=1
while [ "$attempt" -le "$_MERGE_ATTEMPTS" ]; do
  gh pr merge --auto --squash "$PR_URL"
  merge_rc=$?

  if [ "$merge_rc" -eq 0 ]; then
    _decision "armed GitHub-native auto-merge (squash) for a ${UPDATE_TYPE} bump of \
'${DEPENDENCY_NAMES}'; required checks still gate the merge."
    exit 0
  fi

  if [ "$attempt" -lt "$_MERGE_ATTEMPTS" ]; then
    sleep $((_MERGE_RETRY_SLEEP * attempt))
  fi
  attempt=$((attempt + 1))
done

_signal_failure "gh pr merge --auto --squash failed after ${_MERGE_ATTEMPTS} attempts for \
${PR_URL} (last exit ${merge_rc}); auto-merge NOT armed -- check the repository's Allow auto-merge setting."
exit 1
