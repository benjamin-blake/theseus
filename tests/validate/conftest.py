"""Package-scoped, non-autouse factory fixture for tests/validate/ (Decision 131 clause 3).

Thin wrapper over tests.fixtures.pre_sequence_stub.select_steps -- a pure function, so sharing
one instance for the whole package is safe. Non-autouse: nothing here fires unless a test
explicitly requests the ``pre_sequence_stub`` fixture, so editing it does not trip
affected_tests.py's full-suite forcing (that keys on the root conftest path alone).

The caller still does the patching itself, inside its own ``with (...)`` block alongside its
other patches -- e.g. ``patch("scripts.checks.registry.pre_sequence", return_value=steps)`` --
so the derived selection stays a factory callable inside the test body, not a class-level
fixture marker (a class-scoped patch could not exempt a single parametrized case). Selection
controls which checks scripts/validate.py's main() iterates; it does not by itself stop a
selected check's real body from running -- that still needs an explicit
``patch("validate.<name>")`` per Decision 131 clause 3's PR1/PR2 split.
"""

from __future__ import annotations

from collections.abc import Iterable
from unittest.mock import patch

import pytest

from tests.fixtures.pre_sequence_stub import select_steps


@pytest.fixture(autouse=True)
def primary_capture_stub(request):
    """Unit-level subprocess doubles in the pytest-diff tests do not execute the real plugin."""
    if request.module.__name__ not in {
        "tests.validate.test_pytest_diff",
        "tests.validate.test_pytest_diff_coverage",
        "tests.validate.test_pytest_diff_reactive",
    }:
        yield
        return
    from scripts.checks import _pytest_diff_primary  # noqa: PLC0415

    with patch.object(_pytest_diff_primary.PrimaryCapture, "read", return_value={}):
        yield


@pytest.fixture(scope="package")
def pre_sequence_stub():
    """Factory: ``pre_sequence_stub(checks=(...), scaffolds="all")`` returns the derived Step
    list for the --pre tier. Callers patch scripts.checks.registry.pre_sequence with the result
    themselves (see module docstring)."""

    def _factory(*, checks: Iterable[str] = (), scaffolds: str | tuple[str, ...] = "all"):
        return select_steps(checks=tuple(checks), scaffolds=scaffolds, sequence="pre")

    return _factory
