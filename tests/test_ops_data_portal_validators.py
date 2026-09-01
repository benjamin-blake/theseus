"""Unit tests for wave-2 write-time validators and compute_automatable in ops_data_portal."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
import yaml

from scripts.ops_data_portal import (
    _load_write_time_validators,
    _validate_context_length,
    _validate_file_path,
    _write_time_validators_cache,
    compute_automatable,
    file_rec,
)

# ---------------------------------------------------------------------------
# _validate_file_path
# ---------------------------------------------------------------------------


def test_file_path_rejects_absolute_unix():
    with pytest.raises(ValueError, match="absolute Unix"):
        _validate_file_path("/abs/path/file.py")


def test_file_path_rejects_absolute_windows():
    with pytest.raises(ValueError, match="absolute Windows"):
        _validate_file_path("C:\\path\\file.py")


def test_file_path_rejects_backslash_separator():
    with pytest.raises(ValueError, match="backslash"):
        _validate_file_path("scripts\\module.py")


def test_file_path_accepts_relative():
    _validate_file_path("scripts/module.py")  # must not raise


def test_file_path_accepts_nonexistent_relative():
    _validate_file_path("scripts/future_file.py")  # no existence check; must not raise


# ---------------------------------------------------------------------------
# _validate_context_length
# ---------------------------------------------------------------------------


def test_context_length_rejects_short():
    with pytest.raises(ValueError, match="80"):
        _validate_context_length("fix bug")


def test_context_length_accepts_80_chars():
    _validate_context_length("x" * 80)  # exactly 80 chars -- must not raise


# ---------------------------------------------------------------------------
# lint_acceptance_command wired into file_rec
# ---------------------------------------------------------------------------


def test_acceptance_lint_wired_into_file_rec():
    """file_rec raises ValueError when acceptance contains a banned python -c pattern."""
    long_context = "This recommendation exists because the system needs improvement to handle edge cases."
    fields = {
        "title": "Test recommendation title",
        "file": "scripts/some_module.py",
        "context": long_context,
        "acceptance": 'python -c "x=1"',
        "effort": "S",
        "priority": "Low",
        "source": "manual",
        "status": "open",
    }
    with patch("scripts.ops_data_portal.validate_source"):
        with pytest.raises(ValueError, match="python -c"):
            file_rec(fields)


# ---------------------------------------------------------------------------
# compute_automatable
# ---------------------------------------------------------------------------


def test_compute_automatable_boundary_file():
    """Files matching a boundary pattern return False regardless of risk score."""
    # "scripts/executor/" is in the boundary_patterns of config/agent/executor/capabilities.yaml
    result = compute_automatable("scripts/executor/some_tool.py", "S")
    assert result is False


def test_compute_automatable_high_risk_score():
    """R > maturity_ceiling returns False.

    compute_automatable moved to scripts/ops_portal/risk_scoring.py, which calls
    _compute_risk_score as its own module-local sibling -- the patch target is that
    module, not the facade re-export (Decision 124 namespace migration).
    """
    with patch("scripts.ops_portal.risk_scoring._compute_risk_score", return_value=999.0):
        result = compute_automatable("scripts/some_new_module.py", "M")
    assert result is False


def test_compute_automatable_valid():
    """Normal file with R <= maturity_ceiling returns True."""
    with patch("scripts.ops_portal.risk_scoring._compute_risk_score", return_value=0.5):
        result = compute_automatable("scripts/some_new_module.py", "XS")
    assert result is True


# ---------------------------------------------------------------------------
# automatable override warning in file_rec
# ---------------------------------------------------------------------------


def test_automatable_override_warning(caplog):
    """Caller-supplied automatable=True overridden to False by formula; WARNING emitted."""
    long_context = "This recommendation exists because the system needs improvement to handle edge cases."
    fields = {
        "title": "Test boundary recommendation",
        "file": "scripts/executor/some_tool.py",  # boundary file -> compute_automatable returns False
        "context": long_context,
        "acceptance": "grep -q 'pattern' scripts/executor/some_tool.py && grep -q 'other' scripts/executor/some_tool.py",
        "effort": "S",
        "priority": "Low",
        "source": "manual",
        "status": "open",
        "automatable": True,  # caller supplies True; formula will derive False (boundary file)
    }
    with (
        patch("scripts.ops_data_portal.validate_source"),
        patch("scripts.ops_data_portal.Recommendation.model_validate"),
        patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-999"}),
        patch("scripts.ops_data_portal._append_to_local_jsonl"),
        patch("scripts.ops_data_portal._sync_table"),
        caplog.at_level(logging.WARNING, logger="scripts.ops_data_portal"),
    ):
        file_rec(fields)

    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("automatable" in str(m) for m in warning_msgs), (
        f"Expected automatable override WARNING in logs; got: {warning_msgs}"
    )


# ---------------------------------------------------------------------------
# _load_write_time_validators: unrecognised names loud-fail (rec-3308 sibling gap)
# ---------------------------------------------------------------------------


def test_unknown_write_time_test_raises(tmp_path):
    """A write_time test name outside the recognised set raises, instead of the pre-fix elif
    chain falling through with no error and no log."""
    fixture_yaml = tmp_path / "ops.yaml"
    fixture_yaml.write_text(
        yaml.safe_dump(
            {
                "tables": {
                    "ops_recommendations": {
                        "columns": {
                            "mystery": {
                                "tests": [{"bogus_test": {"write_time": True, "enforced": True}}],
                            }
                        }
                    }
                }
            }
        )
    )
    with (
        patch("scripts.ops_portal.write_validators._OPS_YAML_PATH", fixture_yaml),
        patch("scripts.ops_portal.write_validators._write_time_validators_cache", {}),
    ):
        with pytest.raises(ValueError, match="bogus_test"):
            _load_write_time_validators("ops_recommendations")


# ---------------------------------------------------------------------------
# array_element_format (rec-3307 dependencies)
# ---------------------------------------------------------------------------


def test_array_element_format_rejects_malformed_element():
    """array_element_format rejects a malformed dependencies element and accepts a valid list and
    None -- via the bare validator against the real ops.yaml, and through file_rec's write-time
    gate too (acceptance criterion 4 claims both write paths; test_update_rec_content_validation.py
    covers the update_rec half)."""
    _write_time_validators_cache.clear()
    dep_validators = [fn for col, fn in _load_write_time_validators("ops_recommendations") if col == "dependencies"]
    assert dep_validators, "expected a write_time validator for the dependencies column"
    validate = dep_validators[0]

    with pytest.raises(ValueError, match="dependencies"):
        validate(["rec-1", "nonsense"], "dependencies")
    validate(["rec-1", "rec-2"], "dependencies")  # must not raise
    validate(None, "dependencies")  # must not raise

    long_context = "This recommendation exists because the system needs improvement to handle edge cases well."
    fields = {
        "title": "Test recommendation title for dependency format",
        "file": "scripts/some_module.py",
        "context": long_context,
        "acceptance": "grep -q ops_data_portal scripts/ops_data_portal.py && grep -q file_rec scripts/ops_data_portal.py",
        "effort": "S",
        "priority": "Low",
        "source": "manual",
        "status": "open",
        "dependencies": ["rec-1", "nonsense"],
    }
    with patch("scripts.ops_data_portal.validate_source"):
        with pytest.raises(ValueError, match="dependencies"):
            file_rec(fields)


# ---------------------------------------------------------------------------
# min_length (rec-3310 disarmed landmine)
# ---------------------------------------------------------------------------


def test_min_length_reports_its_own_column_and_bound():
    """min_length honours its declared parameter per column: a 9-char title is rejected naming
    title and the bound 10, and a 47-char title is accepted -- under the old hardcoded
    _validate_context_length branch a 47-char value would have been rejected for failing
    context's 80-char rule regardless of which column it was bound to."""
    _write_time_validators_cache.clear()
    title_validators = [fn for col, fn in _load_write_time_validators("ops_recommendations") if col == "title"]
    assert len(title_validators) >= 2, "expected both not_null and min_length write_time validators for title"

    short_title = "123456789"  # 9 stripped chars
    raised = []
    for fn in title_validators:
        try:
            fn(short_title, "title")
        except ValueError as exc:
            raised.append(str(exc))
    assert raised, "expected at least one title validator to reject a 9-char title"
    assert any("title" in msg and "10" in msg for msg in raised), raised
    assert not any("context" in msg for msg in raised), (
        f"min_length must name its own column (title), not the old hardcoded context rule: {raised}"
    )

    ok_title = "x" * 47  # under context's old hardcoded 80-char rule; title's bound is 10
    for fn in title_validators:
        fn(ok_title, "title")  # must not raise


def test_loader_yields_context_min_length_80():
    """Context enforcement is unchanged at 80 THROUGH THE YAML LOADER after migrating off the
    expression branch -- file_rec calls _validate_context_length directly regardless of the
    loader, so this must exercise _load_write_time_validators itself, not the direct function."""
    _write_time_validators_cache.clear()
    context_validators = [fn for col, fn in _load_write_time_validators("ops_recommendations") if col == "context"]
    assert context_validators, "expected at least one write_time validator for the context column"

    short = "x" * 79
    long_ = "x" * 80
    raised = []
    for fn in context_validators:
        try:
            fn(short, "context")
        except ValueError as exc:
            raised.append(str(exc))
    assert raised, "expected a context validator to reject 79 stripped chars"
    for fn in context_validators:
        fn(long_, "context")  # must not raise


def test_expression_write_time_yields_no_validator(tmp_path):
    """The retired hardcoded expression write-time branch is unreachable: a column whose only
    write_time test is an expression carrying a python: key yields no validator from
    _load_write_time_validators. The python: key is mandatory in the fixture -- the retired
    branch was gated on isinstance(params.get("python"), str), so an expression without it would
    yield nothing even if the branch had survived, making the test pass vacuously."""
    fixture_yaml = tmp_path / "ops.yaml"
    fixture_yaml.write_text(
        yaml.safe_dump(
            {
                "tables": {
                    "ops_recommendations": {
                        "columns": {
                            "some_expr_col": {
                                "tests": [
                                    {
                                        "expression": {
                                            "sql": "LENGTH(TRIM(some_expr_col)) >= 80",
                                            "write_time": True,
                                            "enforced": True,
                                            "python": "len(value.strip()) >= 80",
                                        }
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        )
    )
    with (
        patch("scripts.ops_portal.write_validators._OPS_YAML_PATH", fixture_yaml),
        patch("scripts.ops_portal.write_validators._write_time_validators_cache", {}),
    ):
        validators = _load_write_time_validators("ops_recommendations")
    assert validators == [], f"expected no validator for the retired expression write-time branch, got: {validators}"
