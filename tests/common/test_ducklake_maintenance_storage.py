"""New home for the relocated S3-listing helpers (_parse_s3_uri / _default_list_storage), now in
src/common/ducklake_maintenance.py so the smoke Lambda's run_gc cadence can build a storage-derived
G4 size source without importing the production verb module (ducklake_gc_ops).

A separate file rather than appending to test_ducklake_maintenance_ops.py, which is at 330 of 500
SLOC and gaining three new classes of its own (Decision 128 decompose-by-default).

TestG4RealPathShapeAnchor is the real-engine anchor (network-gated integration test): the `path`
column the dry-run ORPHAN table function returns must be byte-identical to _default_list_storage's
s3://bucket/key keys, against a real s3:// DATA_PATH -- this is the path-shape evidence licensing
strict-by-default sizing (a shape mismatch would make strict sizing raise in production).
"""

from __future__ import annotations

import functools
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from src.common import ducklake_maintenance as maint

pytestmark = pytest.mark.unit


class FakePaginator:
    def __init__(self, pages: list[dict[str, Any]]):
        self._pages = pages

    def paginate(self, **_kwargs: Any) -> Any:
        return iter(self._pages)


class FakeS3Client:
    def __init__(self, pages: list[dict[str, Any]]):
        self._pages = pages

    def get_paginator(self, name: str) -> FakePaginator:
        assert name == "list_objects_v2"
        return FakePaginator(self._pages)


class TestRelocatedStorageHelpers:
    def test_parse_s3_uri_splits_bucket_and_prefix(self) -> None:
        assert maint._parse_s3_uri("s3://my-bucket/some/prefix/") == ("my-bucket", "some/prefix/")

    def test_parse_s3_uri_rejects_non_s3_scheme(self) -> None:
        with pytest.raises(maint.DuckLakeMaintenanceError, match="must be an s3:// URI"):
            maint._parse_s3_uri("http://example.com/x")

    def test_parse_s3_uri_rejects_missing_bucket(self) -> None:
        with pytest.raises(maint.DuckLakeMaintenanceError, match="carries no bucket"):
            maint._parse_s3_uri("s3://")

    def test_default_list_storage_walks_paginated_pages(self) -> None:
        pages = [
            {"Contents": [{"Key": "prefix/a.parquet", "Size": 10}, {"Key": "prefix/b.parquet", "Size": 20}]},
            {"Contents": [{"Key": "prefix/c.parquet", "Size": 30}]},
        ]
        result = maint._default_list_storage("s3://my-bucket/prefix/", client=FakeS3Client(pages))
        assert result == {
            "s3://my-bucket/prefix/a.parquet": 10,
            "s3://my-bucket/prefix/b.parquet": 20,
            "s3://my-bucket/prefix/c.parquet": 30,
        }

    def test_default_list_storage_handles_a_page_with_no_contents(self) -> None:
        assert maint._default_list_storage("s3://my-bucket/prefix/", client=FakeS3Client([{}])) == {}


@functools.lru_cache(maxsize=1)
def _has_ducklake_extension() -> bool:
    try:
        import duckdb

        con = duckdb.connect()
        con.execute("INSTALL ducklake; LOAD ducklake")
        con.close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.integration
@pytest.mark.aws
class TestG4RealPathShapeAnchor:
    """Real-engine path-shape anchor licensing strict-by-default sizing: the dry-run ORPHAN table
    function's `path` column must be byte-identical to _default_list_storage's s3://bucket/key
    keys, against a real s3:// DATA_PATH on the pinned engine."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_ducklake_extension(self, _allow_network_for_integration: None) -> None:
        if not _has_ducklake_extension():
            pytest.skip("ducklake extension not available over the network")

    def test_orphan_path_column_matches_default_list_storage_keys(self, tmp_path: Any) -> None:
        import os

        import boto3
        import duckdb

        from scripts.aws_profile import resolve_aws_profile

        data_path = os.environ.get("DUCKLAKE_SMOKE_DATA_PATH", "s3://agent-platform-data-lake/ducklake-neon-smoke/")
        catalog_path = tmp_path / "catalog.ducklake"

        # DuckDB S3 credentials via CREATE SECRET -- the legacy SET s3_access_key_id form 403s
        # inside ducklake's own listing path even when a direct glob with the same credentials
        # succeeds (measured this session). A fresh LOCAL catalog file attached at the REAL
        # data_path tracks nothing, so every real S3 object under the prefix is an orphan --
        # exactly the storage key set, with no write of any kind (dry_run=True never deletes).
        session = boto3.Session(profile_name=resolve_aws_profile("agent_platform"))
        creds = session.get_credentials().get_frozen_credentials()
        region = session.region_name or "eu-west-2"

        con = duckdb.connect(":memory:")
        try:
            con.execute("INSTALL ducklake")
            con.execute("LOAD ducklake")
            con.execute(
                f"CREATE SECRET (TYPE s3, KEY_ID '{creds.access_key}', SECRET '{creds.secret_key}', "
                f"SESSION_TOKEN '{creds.token}', REGION '{region}')"
            )
            con.execute(f"ATTACH 'ducklake:{catalog_path}' AS lk (DATA_PATH '{data_path}', DATA_INLINING_ROW_LIMIT 0)")
            con.execute("USE lk")

            now = datetime.now(timezone.utc) + timedelta(days=3650)  # everything qualifies as orphan candidates
            ts = now.isoformat()
            orphan_rows = con.execute(
                f"SELECT path FROM ducklake_delete_orphaned_files('lk', dry_run=True, older_than=TIMESTAMPTZ '{ts}')"
            ).fetchall()
            orphan_paths = {r[0] for r in orphan_rows}

            storage_paths = set(maint._default_list_storage(data_path))

            assert orphan_paths ^ storage_paths == set(), (
                f"path shape mismatch: orphan-only={orphan_paths - storage_paths}, storage-only={storage_paths - orphan_paths}"
            )
        finally:
            con.close()
