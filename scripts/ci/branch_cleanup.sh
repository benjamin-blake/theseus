#!/usr/bin/env bash
# Body of branch-cleanup.yml's cleanup step, extracted per Decision 162 R1/R3 so the workflow step
# stays a one-line delegate registered as a 1-line body in
# config/composite_action_body_baseline.yaml.
#
# THIN BY DESIGN: every decision, every hard guard and every gh/git call lives in
# scripts/ci/branch_cleanup.py, so the delete/keep logic is unit-testable in-process
# (tests/test_branch_cleanup.py) instead of only through a shell harness. This file exists solely
# to bridge the workflow's `run:` body to that module, so it must stay free of policy.
#
# `python3` (not bin/venv-python): this runs on the GitHub runner, which has no repo venv, and the
# module is stdlib-only by construction for exactly that reason. Invoked by FILE PATH rather than
# `-m` because it imports nothing from the repo -- so unlike scripts/ci/reconcile_target.py it does
# not need the repo root on sys.path.
#
# `exec` replaces this shell with the interpreter, so the module's exit status IS this script's
# exit status with no intermediate handling to get wrong -- which is why there are no per-call-site
# status checks here the way scripts/ci/pr_conflict_signal.sh needs them.
#
# Contract with branch-cleanup.yml: cwd is the repo root (actions/checkout with fetch-depth: 0
# precedes this step); DRY_RUN, MIN_AGE_HOURS, EXTRA_BRANCHES, GH_TOKEN and GH_REPO are set in the
# step's env: block.

set -uo pipefail

exec python3 scripts/ci/branch_cleanup.py
