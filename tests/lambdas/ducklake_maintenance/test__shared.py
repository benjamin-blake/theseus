"""MIRROR for src/lambdas/ducklake_maintenance/_shared.py (Decision 204,
PLAN-ducklake-partition-layout-remediation).

Mirror test for _shared.py -- identifier and data_path guards, 100% line coverage.
"""

from __future__ import annotations

import pytest

from src.common.ducklake_runtime import DuckLakeRuntimeError
from src.lambdas.ducklake_maintenance import _shared

pytestmark = pytest.mark.unit


def test_extension_directory_is_a_string_constant():
    assert isinstance(_shared.EXTENSION_DIRECTORY, str)


def test_require_identifier_accepts_bare_identifier():
    assert _shared._require_identifier("ducklake_ops") == "ducklake_ops"
    assert _shared._require_identifier("_leading_underscore") == "_leading_underscore"


@pytest.mark.parametrize("bad", ["ducklake ops", "ducklake-ops", "1leading_digit", "", None, 42, "ducklake;drop table x"])
def test_require_identifier_rejects_non_identifier(bad):
    with pytest.raises(DuckLakeRuntimeError, match="invalid SQL identifier"):
        _shared._require_identifier(bad)


def test_require_data_path_accepts_s3_uri():
    assert _shared._require_data_path("s3://bucket/prefix/") == "s3://bucket/prefix/"


@pytest.mark.parametrize("bad", ["http://bucket/prefix/", "bucket/prefix/", "", None, 42])
def test_require_data_path_rejects_non_s3_uri(bad):
    with pytest.raises(DuckLakeRuntimeError, match="invalid data_path"):
        _shared._require_data_path(bad)
