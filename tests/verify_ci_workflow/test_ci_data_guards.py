"""Tests for scripts/verify_ci_workflow.py -- the full-tier-runtime-lock, jobs-and-flags, and
fetch-depth guards sharing the _VALID_CI_DATA fixture (VERBATIM split from
tests/test_verify_ci_workflow.py, rec-2709 Wave 12; the non-fetch-depth guards further split to
tests/verify_ci_workflow/test_ci_topology_guards.py, PLAN ci-full-tier-history-parity, once this
file crossed the 500-SLOC budget -- Decision 128).
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import patch

import pytest

from scripts.verify_ci_workflow import (
    _check_fetch_depth,
    _check_full_tier_runtime_lock,
    _check_jobs_and_flags,
)

# ---------------------------------------------------------------------------
# Shared fixture data for the five guards below
# ---------------------------------------------------------------------------

_COMPILED_CACHE_KEY = (
    "pip-${{ hashFiles('requirements.in', 'requirements-dev.in', 'requirements.txt', 'requirements-dev.txt') }}"
)

_VALID_CI_DATA: dict[str, Any] = {
    "jobs": {
        "pr-validate": {
            "if": "github.event_name == 'pull_request'",
            "runs-on": "ubuntu-latest",
            "concurrency": {"group": "pr-validate-${{ github.ref }}", "cancel-in-progress": True},
            "steps": [
                {"uses": "actions/checkout@v4", "with": {"fetch-depth": 0}},
                {"run": "bin/venv-python -m scripts.validate --pre"},
            ],
        },
        "main-validate": {
            "if": "github.event_name == 'push'",
            "runs-on": "ubuntu-latest",
            "steps": [
                {"uses": "actions/checkout@v4", "with": {"fetch-depth": 0}},
                {
                    "uses": "actions/cache@v6",
                    "with": {"key": _COMPILED_CACHE_KEY},
                },
                {"run": "pip install -r requirements.txt\npip install -r requirements-dev.txt"},
                {"run": "bin/venv-python -m scripts.validate"},
            ],
        },
        "terraform-validate": {
            "runs-on": "ubuntu-latest",
            "steps": [{"run": "terraform validate"}],
        },
    }
}

_VALID_CANARY_COMPILED_DATA = {
    "jobs": {
        "canary": {
            "steps": [
                {"uses": "actions/checkout@v4", "with": {"fetch-depth": 0}},
                {
                    "uses": "actions/cache@v6",
                    "with": {"key": _COMPILED_CACHE_KEY},
                },
                {"run": "pip install -r requirements.txt\npip install -r requirements-dev.txt"},
                {"run": "bin/venv-python -m scripts.validate"},
            ]
        }
    }
}


class TestFullTierRuntimeLock:
    def test_accepts_compiled_output_jobs(self) -> None:
        with patch("scripts.verify_ci_workflow._ci_yaml._load") as mock_load:
            mock_load.side_effect = [_VALID_CI_DATA, _VALID_CANARY_COMPILED_DATA]
            _check_full_tier_runtime_lock()

    @pytest.mark.parametrize(
        ("missing", "expected"),
        [("install", "does not install compiled requirements-dev.txt"), ("cache", "cache key omits requirements.txt")],
    )
    def test_rejects_missing_main_validate_compiled_contract(self, missing: str, expected: str) -> None:
        import copy

        ci_data = copy.deepcopy(_VALID_CI_DATA)
        steps = ci_data["jobs"]["main-validate"]["steps"]
        if missing == "install":
            steps[2]["run"] = "pip install -r requirements.txt"
        else:
            steps[1]["with"]["key"] = "pip-runtime"
        with patch("scripts.verify_ci_workflow._ci_yaml._load") as mock_load:
            mock_load.side_effect = [ci_data, _VALID_CANARY_COMPILED_DATA]
            with pytest.raises(AssertionError, match=re.escape(expected)):
                _check_full_tier_runtime_lock()


# ---------------------------------------------------------------------------
# _check_jobs_and_flags
# ---------------------------------------------------------------------------


class TestCheckJobsAndFlagsPassPath:
    def test_passes_with_valid_ci_data(self) -> None:
        with patch("scripts.verify_ci_workflow._ci_yaml._load") as mock_load:
            mock_load.return_value = _VALID_CI_DATA
            _check_jobs_and_flags()


class TestCheckJobsAndFlagsFailPath:
    def test_fails_when_pr_validate_missing(self) -> None:
        data = {
            "jobs": {
                "main-validate": _VALID_CI_DATA["jobs"]["main-validate"],
            }
        }
        with patch("scripts.verify_ci_workflow._ci_yaml._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="pr-validate job missing"):
                _check_jobs_and_flags()

    def test_fails_when_pr_validate_missing_pre_flag(self) -> None:
        data = {
            "jobs": {
                "pr-validate": {
                    "if": "github.event_name == 'pull_request'",
                    "runs-on": "ubuntu-latest",
                    "steps": [
                        {"uses": "actions/checkout@v4", "with": {"fetch-depth": 0}},
                        {"run": "bin/venv-python -m scripts.validate"},
                    ],
                },
                "main-validate": _VALID_CI_DATA["jobs"]["main-validate"],
            }
        }
        with patch("scripts.verify_ci_workflow._ci_yaml._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="--pre"):
                _check_jobs_and_flags()

    def test_fails_when_main_validate_compiled_install_is_missing(self) -> None:
        import copy

        data = copy.deepcopy(_VALID_CI_DATA)
        data["jobs"]["main-validate"]["steps"][2]["run"] = "pip install -r requirements.txt"
        with patch("scripts.verify_ci_workflow._ci_yaml._load", return_value=data):
            with pytest.raises(AssertionError, match="requirements-dev.txt"):
                _check_jobs_and_flags()


# ---------------------------------------------------------------------------
# _check_fetch_depth
# ---------------------------------------------------------------------------


class TestCheckFetchDepthPassPath:
    def test_passes_with_valid_ci_data(self) -> None:
        with patch("scripts.verify_ci_workflow._ci_yaml._load") as mock_load:
            mock_load.side_effect = [_VALID_CI_DATA, _VALID_CANARY_COMPILED_DATA]
            _check_fetch_depth()


class TestCheckFetchDepthFailPath:
    def test_fails_when_pr_validate_missing_fetch_depth(self) -> None:
        data = {
            "jobs": {
                "pr-validate": {
                    "if": "github.event_name == 'pull_request'",
                    "runs-on": "ubuntu-latest",
                    "steps": [
                        {"uses": "actions/checkout@v4"},
                        {"run": "bin/venv-python -m scripts.validate --pre"},
                    ],
                },
                "main-validate": _VALID_CI_DATA["jobs"]["main-validate"],
            }
        }
        with patch("scripts.verify_ci_workflow._ci_yaml._load") as mock_load:
            mock_load.side_effect = [data, _VALID_CANARY_COMPILED_DATA]
            with pytest.raises(AssertionError, match="fetch-depth"):
                _check_fetch_depth()

    def test_fails_when_main_validate_has_no_checkout_step(self) -> None:
        """rec-2040: a full-tier job with no checkout step at all must be rejected, not just
        one with a wrong or missing fetch-depth value."""
        data = {
            "jobs": {
                "pr-validate": _VALID_CI_DATA["jobs"]["pr-validate"],
                "main-validate": {
                    "if": "github.event_name == 'push'",
                    "runs-on": "ubuntu-latest",
                    "steps": [
                        {"run": "bin/venv-python -m scripts.validate"},
                    ],
                },
            }
        }
        with patch("scripts.verify_ci_workflow._ci_yaml._load") as mock_load:
            mock_load.side_effect = [data, _VALID_CANARY_COMPILED_DATA]
            with pytest.raises(AssertionError, match="no checkout step"):
                _check_fetch_depth()

    def test_fails_when_main_validate_missing_fetch_depth(self) -> None:
        """A checkout step with no `with` block at all is rejected the same as an explicit
        wrong value -- both resolve to fetch-depth None != 0."""
        data = {
            "jobs": {
                "pr-validate": _VALID_CI_DATA["jobs"]["pr-validate"],
                "main-validate": {
                    "if": "github.event_name == 'push'",
                    "runs-on": "ubuntu-latest",
                    "steps": [
                        {"uses": "actions/checkout@v4"},
                        {"run": "bin/venv-python -m scripts.validate"},
                    ],
                },
            }
        }
        with patch("scripts.verify_ci_workflow._ci_yaml._load") as mock_load:
            mock_load.side_effect = [data, _VALID_CANARY_COMPILED_DATA]
            with pytest.raises(AssertionError, match="expected 0"):
                _check_fetch_depth()

    def test_fails_when_main_validate_has_shallow_fetch_depth(self) -> None:
        """Polarity flip (Decision 168, amends Decision 159 clause 1): fetch-depth 2 was the
        accepted value under the retired rule -- it is now the rejected one, since every
        full-tier job must check out full history."""
        data = {
            "jobs": {
                "pr-validate": _VALID_CI_DATA["jobs"]["pr-validate"],
                "main-validate": {
                    "if": "github.event_name == 'push'",
                    "runs-on": "ubuntu-latest",
                    "steps": [
                        {"uses": "actions/checkout@v4", "with": {"fetch-depth": 2}},
                        {"run": "bin/venv-python -m scripts.validate"},
                    ],
                },
            }
        }
        with patch("scripts.verify_ci_workflow._ci_yaml._load") as mock_load:
            mock_load.side_effect = [data, _VALID_CANARY_COMPILED_DATA]
            with pytest.raises(AssertionError, match="expected 0"):
                _check_fetch_depth()


# ---------------------------------------------------------------------------
# TestCheckFullTierDepth -- canary coverage (Decision 168 extends the rule beyond ci.yml)
# ---------------------------------------------------------------------------


class TestCheckFullTierDepth:
    def test_shallow_canary_checkout_is_rejected(self) -> None:
        canary_data = {
            "jobs": {
                "canary": {
                    "steps": [
                        {"uses": "actions/checkout@v4", "with": {"fetch-depth": 2}},
                        {"run": "bin/venv-python -m scripts.validate"},
                    ]
                }
            }
        }
        with patch("scripts.verify_ci_workflow._ci_yaml._load") as mock_load:
            mock_load.side_effect = [_VALID_CI_DATA, canary_data]
            with pytest.raises(AssertionError, match=r"canary checkout fetch-depth.*expected 0"):
                _check_fetch_depth()
