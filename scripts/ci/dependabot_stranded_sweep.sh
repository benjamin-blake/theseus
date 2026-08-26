#!/usr/bin/env bash
# Body of dependabot-stranded.yml's sweep step, extracted per Decision 162 R1/R3 so the sweep logic
# is directly testable (tests/test_dependabot_stranded_wiring.py) and the workflow step stays a
# one-line delegate registered as a 1-line body in config/composite_action_body_baseline.yaml.
#
# ERREXIT: the workflow step declares no `shell:` key, so GitHub runs the step body as
# "bash --noprofile --norc -e -o pipefail {0}" -- but that body spawns a CHILD bash to run this
# file, and a child bash does not inherit its parent's shell options (SHELLOPTS is unexported).
# This script therefore runs WITHOUT inherited errexit, so every gh call site checks its own exit
# status below. `set +e` is retained as defence-in-depth against a future re-inlining of this body
# back into the workflow step (where -e WOULD apply); it is not the load-bearing mechanism. Same
# derivation as scripts/ci/pr_conflict_signal.sh's header.
#
# WHAT IT DOES, AND DELIBERATELY DOES NOT DO:
#   - BEHIND: the PR's base moved on without it. Its required checks were computed against a stale
#     base and will never re-run on their own, because nothing pushes to the branch and so no
#     `synchronize` event fires. `gh pr update-branch` merges the current base in, which fires that
#     event and re-runs CI -- and re-triggers dependabot-auto-merge, which re-applies the single
#     copy of the minor/patch policy. This script carries NO merge policy of its own.
#   - DIRTY: the branch genuinely conflicts with the base, so update-branch cannot resolve it. The
#     fallback is a `@dependabot rebase` comment, which asks dependabot to RECREATE the branch from
#     the current base -- the only actor that can rewrite a dependabot branch cleanly. The same
#     fallback also covers a BEHIND PR whose update-branch call simply failed (permissions, a race
#     with a concurrent push), so a single failure mode never strands a PR for another week.
#   - Anything else (CLEAN, BLOCKED, UNSTABLE, UNKNOWN): reported in the summary table, untouched.
#     BLOCKED is usually a CODEOWNERS-protected path awaiting a human code-owner approval that no
#     bot can supply, and updating the branch would not change that.
#
# NO CLAUDE ATTRIBUTION FOOTER on the `@dependabot rebase` comment: comments posted from a workflow
# are authored by the github-actions bot, not by Claude, and the body is a bot COMMAND that
# dependabot parses -- extra trailer lines are noise on both counts.
#
# EXIT CODE: non-zero only on a TOTAL failure -- i.e. `gh pr list` could not enumerate the backlog
# at all, so the sweep did not run this week and nobody would otherwise notice. A per-PR failure is
# recorded in the summary table and emitted as a greppable marker, but does not red the run: the
# next scheduled sweep retries it, and this workflow is registered `ci_rca: excluded` precisely
# because a single unswept PR is not an RCA-worthy regression.
#
# Contract with dependabot-stranded.yml: cwd is the repo root (actions/checkout precedes this
# step); GH_TOKEN / GH_REPO are set in the step's env: block for the gh CLI to read.

set -uo pipefail
set +e

_GH_RETRY_ATTEMPTS=3
_GH_RETRY_SLEEP="${DEPENDABOT_STRANDED_RETRY_SLEEP:-5}"

_DEPENDABOT_AUTHOR="app/dependabot"
_REBASE_COMMAND="@dependabot rebase"

_TOTAL_FAILURE=0
_TABLE_ROWS=""

_signal_failure() {
  local msg="[DEPENDABOT-STRANDED] FAILURE: $1"
  echo "$msg" >&2
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '\n## dependabot-stranded FAILURE\n\n%s\n' "$msg" >> "$GITHUB_STEP_SUMMARY"
  fi
}

# Bounded retry shared by every retried gh call site, so retry policy and exit-status handling live
# in exactly one place (the rec-2735 defect class). Prints the last observed stdout and returns the
# last attempt's status. `gh pr update-branch` deliberately does NOT go through this: it has an
# explicit fallback, and retrying first would only delay reaching it.
_gh_bounded_retry() {
  local max_attempts="$1" sleep_secs="$2"
  shift 2
  local attempt out rc
  for ((attempt = 1; attempt <= max_attempts; attempt++)); do
    out=$("$@")
    rc=$?
    if [ "$rc" -eq 0 ]; then
      printf '%s' "$out"
      return 0
    fi
    if [ "$attempt" -lt "$max_attempts" ]; then
      sleep "$sleep_secs"
    fi
  done
  printf '%s' "$out"
  return 1
}

# Age in whole days from an ISO-8601 createdAt. `date -d` is GNU-only, which the ubuntu-latest
# runner always is; an unparseable or absent timestamp yields "?" rather than aborting the sweep,
# because age is reporting-only and never gates an action.
_age_days() {
  local created="$1" created_epoch now_epoch
  [ -z "$created" ] && { printf '?'; return 0; }
  created_epoch=$(date -u -d "$created" +%s 2>/dev/null)
  if [ $? -ne 0 ] || [ -z "$created_epoch" ]; then
    printf '?'
    return 0
  fi
  now_epoch=$(date -u +%s)
  printf '%s' "$(((now_epoch - created_epoch) / 86400))"
}

_add_row() {
  local number="$1" title="$2" age="$3" merge_state="$4" auto_merge="$5" action="$6"
  # A pipe inside a title would break the markdown table's column count.
  title="${title//|/\\|}"
  _TABLE_ROWS="${_TABLE_ROWS}| #${number} | ${title} | ${age} | ${merge_state} | ${auto_merge} | ${action} |
"
}

_write_summary() {
  [ -z "${GITHUB_STEP_SUMMARY:-}" ] && return 0
  {
    printf '\n## dependabot-stranded sweep\n\n'
    if [ -z "$_TABLE_ROWS" ]; then
      printf 'No open dependabot PRs.\n'
    else
      printf '| PR | Title | Age (days) | Merge state | Auto-merge | Action |\n'
      printf '| --- | --- | --- | --- | --- | --- |\n'
      printf '%s' "$_TABLE_ROWS"
    fi
  } >> "$GITHUB_STEP_SUMMARY"
}

prs=$(_gh_bounded_retry "$_GH_RETRY_ATTEMPTS" "$_GH_RETRY_SLEEP" \
  gh pr list --author "$_DEPENDABOT_AUTHOR" --state open \
  --json number,title,headRefName,mergeStateStatus,createdAt,autoMergeRequest \
  --jq '.[] | [.number, .title, .mergeStateStatus, .createdAt, (if .autoMergeRequest == null then "no" else "yes" end)] | @tsv')
prs_rc=$?

if [ "$prs_rc" -ne 0 ]; then
  _signal_failure "gh pr list failed after $_GH_RETRY_ATTEMPTS attempts; cannot enumerate open dependabot PRs -- the sweep did not run."
  _TOTAL_FAILURE=1
elif [ -z "$prs" ]; then
  echo "No open dependabot PRs."
else
  while IFS=$'\t' read -r number title merge_state created_at auto_merge; do
    [ -z "$number" ] && continue
    age_days=$(_age_days "$created_at")

    if [ "$merge_state" != "BEHIND" ] && [ "$merge_state" != "DIRTY" ]; then
      echo "PR #$number: mergeStateStatus=$merge_state, no sweep action needed."
      _add_row "$number" "$title" "$age_days" "$merge_state" "$auto_merge" "none"
      continue
    fi

    echo "PR #$number: mergeStateStatus=$merge_state, updating branch onto the current base."
    gh pr update-branch "$number"
    update_rc=$?

    if [ "$update_rc" -eq 0 ]; then
      _add_row "$number" "$title" "$age_days" "$merge_state" "$auto_merge" "update-branch"
      continue
    fi

    echo "PR #$number: gh pr update-branch failed (exit $update_rc); asking dependabot to rebase."
    _gh_bounded_retry "$_GH_RETRY_ATTEMPTS" "$_GH_RETRY_SLEEP" \
      gh pr comment "$number" --body "$_REBASE_COMMAND" > /dev/null
    comment_rc=$?

    if [ "$comment_rc" -eq 0 ]; then
      _add_row "$number" "$title" "$age_days" "$merge_state" "$auto_merge" "rebase-comment"
      continue
    fi

    _signal_failure "PR #$number: gh pr update-branch failed (exit $update_rc) and the $_REBASE_COMMAND fallback comment also failed; PR left stranded for the next sweep."
    _add_row "$number" "$title" "$age_days" "$merge_state" "$auto_merge" "FAILED"
  done <<< "$prs"
fi

_write_summary

if [ "$_TOTAL_FAILURE" -ne 0 ]; then
  exit 1
fi
exit 0
