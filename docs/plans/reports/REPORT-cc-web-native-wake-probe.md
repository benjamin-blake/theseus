# REPORT: Does CC-web deliver a native wake on green check-suite rollup?

> Evidence-gathering probe against rec-3335. No plan artifact, no review gate -- this document
> is the disposable control surface for the live experiment, not a proposal. The finding itself
> is filed to the ops portal against rec-3335, per the Warehouse-as-source-of-truth invariant;
> this file exists only because the probe needs a real, mergeable-shaped diff to open a real PR
> and trigger real CI.

## 1. Question

`docs/contracts/git-ops.yaml:193-199` (`wake_signals.ci_green_comment`) asserts that
`subscribe_pr_activity` "delivers failure events but NOT a CI-success webhook", and that
`signal-green` (`ci.yml`) exists specifically to compensate for that gap by posting a "CI green"
PR comment on `claude/*` branches only.

The current `subscribe_pr_activity` tool contract available to this session instead states that
"comments, CI failures, and successful check-suite rollups will be delivered" -- i.e. that a
native wake on green now exists. One of the two is stale.

## 2. Control

`signal-green` (`ci.yml:315`, gate: `startsWith(github.head_ref, 'claude/')`) and
`pr-conflict-signal.yml` / `scripts/ci/pr_conflict_signal.sh` (enumerates only
`headRefName` starting with `claude/`) both scope their comment-based wake signals to
`claude/*` head branches. Running this probe from an `agent/*` head branch means neither
in-repo signal can fire, so any wake observed on a green check-suite rollup is necessarily
native harness delivery, not a repo-side comment.

## 3. Method

1. Open this PR from `agent/cc-web-native-wake-probe` (not the harness-assigned session
   branch) against `main`.
2. `subscribe_pr_activity`; confirm `signal-green` shows `skipped` in the check-run list.
3. Push a deliberate CI failure (positive control -- proves the subscription delivers at all).
4. Push the fix; observe whether a wake arrives on the subsequent green rollup, and if so its
   `<wake reason="external-event">` `kind` and latency from last check completion.
5. If no wake arrives within ~15 minutes, confirm independently via `pull_request_read`
   (`get_status` / `get_check_runs`) that CI actually went green, so "no wake" is not confused
   with "CI never finished".

## 4. Result

Pending -- filed to the ops portal against rec-3335 once steps 3-5 complete, not recorded here
(narrative summaries are query results, not stored artefacts, per `AGENTS.md`).

## 5. Interpretation

A positive result (wake observed) is conclusive: it demonstrates the capability exists.
A negative result is not conclusive on its own: rec-3335 already established that delivery on
a live subscription can fail intermittently, so a single negative does not license deleting
`signal-green`.

## 6. Disposition

This PR is not intended to merge. It is closed once the probe completes; the finding lives in
the ops portal, not in this file's history.
