"""Mirror test for src/common/ducklake_telemetry_blobstore.py (the content_blobs s3 adapter) and the T2.36 c4 guard.

Fast-tier nodes use a hand fake client (no botocore). Two nodes take botocore through a function-scope importorskip: an
offline presign with fake credentials and a Stubber HEAD. Credential-shaped values are built at runtime."""

from __future__ import annotations

import ast
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

from src.common import ducklake_telemetry_blobstore as store_mod
from src.common.ducklake_scd2_schema import DuckLakeRuntimeError
from src.common.ducklake_telemetry_blobstore import (
    BLOB_COMMIT_MAX_AGE_DAYS,
    BlobGrantSelfCheckError,
    BlobRoot,
    BlobStoreAccessError,
    BlobStoreUnavailableError,
    S3BlobStore,
)
from src.telemetry.blobs import sha256_hex_to_b64
from tests.fixtures.telemetry_blob_fakes import SIGNED, ClientErrorLike, FakeS3Client, presigned_url

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 1, 10, tzinfo=timezone.utc)
SHA = "ab" * 32
URI = "tenant/project/session/" + SHA
BLOB_ROOT = BlobRoot("bucket", "telemetry-blobs/ducklake_smoke/")
HEAD_OK = {"ContentLength": 70000, "ChecksumSHA256": sha256_hex_to_b64(SHA), "LastModified": NOW - timedelta(days=1)}


def store(client: Any) -> S3BlobStore:
    return S3BlobStore(client, BLOB_ROOT, clock=lambda: NOW)


def test_verify_states_from_head() -> None:
    assert store(FakeS3Client(HEAD_OK)).verify(URI, SHA, 70000) == "verified"
    assert store(FakeS3Client({**HEAD_OK, "ContentLength": 69999})).verify(URI, SHA, 70000) == "mismatch"
    assert (
        store(FakeS3Client({**HEAD_OK, "ChecksumSHA256": sha256_hex_to_b64("cd" * 32)})).verify(URI, SHA, 70000) == "mismatch"
    )
    assert (
        store(FakeS3Client({k: v for k, v in HEAD_OK.items() if k != "ChecksumSHA256"})).verify(URI, SHA, 70000) == "mismatch"
    )
    old = {**HEAD_OK, "LastModified": NOW - timedelta(days=BLOB_COMMIT_MAX_AGE_DAYS, seconds=1)}
    assert store(FakeS3Client(old)).verify(URI, SHA, 70000) == "stale"
    edge = {**HEAD_OK, "LastModified": NOW - timedelta(days=BLOB_COMMIT_MAX_AGE_DAYS)}
    assert store(FakeS3Client(edge)).verify(URI, SHA, 70000) == "verified"
    for code in ("404", "NoSuchKey", "NotFound"):
        assert store(FakeS3Client(ClientErrorLike(code, 404))).verify(URI, SHA, 70000) == "missing"
    key = BLOB_ROOT.prefix + URI
    assert store(FakeS3Client(HEAD_OK)).verify(URI, SHA, 70000, now=NOW + timedelta(days=30)) == "stale"
    assert FakeS3Client(HEAD_OK).calls == [] and key.startswith("telemetry-blobs/ducklake_smoke/")


def test_head_403_is_missing_only_when_the_list_finds_nothing() -> None:
    absent = FakeS3Client(ClientErrorLike("403", 403), {"Contents": []})
    assert store(absent).verify(URI, SHA, 70000) == "missing"
    assert [c for c, _ in absent.calls] == ["head_object", "list_objects_v2"]
    assert absent.calls[1][1] == {"Bucket": "bucket", "Prefix": BLOB_ROOT.prefix + URI, "MaxKeys": 1}
    present = FakeS3Client(ClientErrorLike("AccessDenied", 403), {"Contents": [{"Key": BLOB_ROOT.prefix + URI}]})
    with pytest.raises(BlobStoreAccessError):
        store(present).verify(URI, SHA, 70000)
    other = FakeS3Client(ClientErrorLike("403", 403), {"Contents": [{"Key": BLOB_ROOT.prefix + URI + "x"}]})
    assert store(other).verify(URI, SHA, 70000) == "missing"
    denied_list = FakeS3Client(ClientErrorLike("403", 403), ClientErrorLike("AccessDenied", 403))
    with pytest.raises(BlobStoreAccessError):
        store(denied_list).verify(URI, SHA, 70000)


def test_throttle_and_5xx_are_unavailable() -> None:
    for code, status in (("SlowDown", 503), ("Throttling", 400), ("InternalError", 500), ("X", 502), ("Y", 429)):
        with pytest.raises(BlobStoreUnavailableError) as caught:
            store(FakeS3Client(ClientErrorLike(code, status))).verify(URI, SHA, 70000)
        assert "secret" not in str(caught.value) and caught.value.__cause__ is None
    for name in ("ReadTimeoutError", "ConnectTimeoutError", "EndpointConnectionError"):
        with pytest.raises(BlobStoreUnavailableError):
            store(FakeS3Client(type(name, (Exception,), {})("secret-key"))).verify(URI, SHA, 70000)
    with pytest.raises(BlobStoreAccessError) as caught:
        store(FakeS3Client(ClientErrorLike("InvalidObjectState", 400))).verify(URI, SHA, 70000)
    assert "secret" not in str(caught.value)
    with pytest.raises(BlobStoreUnavailableError):
        store(FakeS3Client(HEAD_OK, ClientErrorLike("SlowDown", 503))).count_objects("a/")


def test_head_asks_for_checksum_mode() -> None:
    client = FakeS3Client(HEAD_OK)
    store(client).verify(URI, SHA, 70000)
    assert client.calls == [
        ("head_object", {"Bucket": "bucket", "Key": BLOB_ROOT.prefix + URI, "ChecksumMode": "ENABLED"}),
    ]


def test_grant_self_check_refuses_an_unsigned_checksum() -> None:
    good = FakeS3Client(url=presigned_url("k"))
    grant = store(good).grant_put(URI, SHA, 70000)
    assert grant.headers == {"Content-Length": "70000", "x-amz-checksum-sha256": sha256_hex_to_b64(SHA)}
    assert grant.expires_at == "2026-01-10T00:15:00.000Z" and "https" not in repr(grant)
    name, kwargs = good.calls[0]
    assert name == "put_object" and kwargs["ExpiresIn"] == 900 and kwargs["HttpMethod"] == "PUT"
    assert kwargs["Params"] == {
        "Bucket": "bucket",
        "Key": BLOB_ROOT.prefix + URI,
        "ContentLength": 70000,
        "ChecksumSHA256": sha256_hex_to_b64(SHA),
    }
    for bad in (
        presigned_url(signed="content-length;host"),
        presigned_url(signed="host;x-amz-checksum-sha256"),
        presigned_url(signed=SIGNED + ";x-amz-meta-a"),
        presigned_url(extra="&x-amz-checksum-crc32=AAAAAA=="),
        presigned_url(extra="&X-Amz-Sdk-Checksum-Algorithm=CRC32"),
        presigned_url(token=False),
    ):
        with pytest.raises(BlobGrantSelfCheckError) as caught:
            store(FakeS3Client(url=bad)).grant_put(URI, SHA, 70000)
        assert "https" not in str(caught.value) and "X-Amz" not in str(caught.value)


def test_root_is_scoped_and_disjoint_from_the_data_path() -> None:
    ok = BlobRoot.from_env("s3://bucket/telemetry-blobs/ducklake_smoke/", "s3://bucket/ducklake_smoke/data/", "ducklake_smoke")
    assert (ok.bucket, ok.prefix, ok.key("a/b")) == (
        "bucket",
        "telemetry-blobs/ducklake_smoke/",
        "telemetry-blobs/ducklake_smoke/a/b",
    )
    for root, data in (
        ("s3://bucket/telemetry-blobs/other/", "s3://bucket/d/"),
        ("s3://bucket/telemetry-blobs/ducklake_smoke", "s3://bucket/d/"),
        ("s3://bucket/ducklake_smoke/", "s3://bucket/d/"),
        ("https://bucket/telemetry-blobs/ducklake_smoke/", "s3://bucket/d/"),
        ("s3:///telemetry-blobs/ducklake_smoke/", "s3://bucket/d/"),
        ("s3://bucket/telemetry-blobs/ducklake_smoke/", "s3://bucket/telemetry-blobs/"),
        ("s3://bucket/telemetry-blobs/ducklake_smoke/", "s3://bucket/telemetry-blobs/ducklake_smoke/sub/"),
        ("s3://bucket/telemetry-blobs/ducklake_smoke/", "s3://bucket/"),
    ):
        with pytest.raises(DuckLakeRuntimeError):
            BlobRoot.from_env(root, data, "ducklake_smoke")
    assert BlobRoot.from_env("s3://bucket/telemetry-blobs/ducklake_smoke/", "s3://other/telemetry-blobs/", "ducklake_smoke")


def test_count_objects_pages_through_the_prefix() -> None:
    pages = iter(
        [
            {"Contents": [{"Size": 5}], "IsTruncated": True, "NextContinuationToken": "t1"},
            {"Contents": [{"Size": 7}, {"Size": 1}], "IsTruncated": False},
        ]
    )

    class Paged(FakeS3Client):
        def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("list_objects_v2", kwargs))
            return next(pages)

    client = Paged()
    assert store(client).count_objects("t/p/s/") == {"count": 3, "bytes": 13}
    assert client.calls[0][1]["Prefix"] == BLOB_ROOT.prefix + "t/p/s/" and client.calls[1][1]["ContinuationToken"] == "t1"
    assert store(FakeS3Client()).count_objects("t/p/s/") == {"count": 0, "bytes": 0}


_OBJECT_READS = frozenset({"get_object", "download_file", "download_fileobj", "select_object_content", "copy_object"})
_S3_OPERATIONS = _OBJECT_READS | {
    "put_object", "delete_object", "delete_objects", "head_object", "list_objects", "list_objects_v2", "list_object_versions",
    "upload_file", "upload_fileobj", "copy", "create_multipart_upload", "upload_part", "complete_multipart_upload",
    "abort_multipart_upload", "generate_presigned_url", "generate_presigned_post", "put_object_acl", "restore_object",
}  # fmt: skip
_SQL_READ = re.compile(r"(read_parquet|read_json|read_csv|read_blob|read_text)", re.IGNORECASE)
_SQL_COPY = re.compile(r"\bCOPY\b[^;]*?\bFROM\b", re.DOTALL)
_SEAM = ("src/common/ducklake_telemetry_blobstore.py", "get_blob")


def _bundled(function: str | None = None) -> list[str]:
    """The .py files named by the DuckLake manifests (every ducklake_* function, or just one)."""
    found: set[str] = set()
    pattern = f"ducklake_{function}" if function else "ducklake_*"
    for manifest in sorted((ROOT / "src" / "lambdas").glob(f"{pattern}/manifest.yaml")):
        for include in yaml.safe_load(manifest.read_text(encoding="utf-8"))["includes"]:
            path = ROOT / include
            found.update(p.relative_to(ROOT).as_posix() for p in ([path] if path.suffix == ".py" else path.rglob("*.py")))
    return sorted(found)


def _scan(rel: str) -> tuple[list[tuple[str, int]], list[tuple[str, int]], list[str]]:
    """(S3 operation calls, SQL object-storage reads, names of get_blob definitions) outside docstrings."""
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    seam_lines: set[int] = set()
    if rel == _SEAM[0]:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == _SEAM[1]:
                seam_lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    calls, sql, seams = [], [], []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.FunctionDef) and node.name == _SEAM[1]:
            seams.append(node.name)
        if line in seam_lines:
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _S3_OPERATIONS:
            calls.append((node.func.attr, line))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            text = node.value
            if (_SQL_READ.search(text) and "s3://" in text) or _SQL_COPY.search(text) or "ducklake_add_data_files" in text:
                sql.append((text[:40], line))
    return calls, sql, seams


def test_no_ducklake_bundle_ingests_from_object_storage() -> None:
    """T2.36 c4 guard. Staging is an S3 object read whose bytes become catalog rows. Leg (a): no module bundled by any DuckLake
    manifest (the only processes that write catalog rows, Decision 84 I-1) reads an object (get_object, download_file,
    download_fileobj, select_object_content, copy_object) or holds SQL that reads object storage into a table (read_* over
    s3://, COPY ... FROM, ducklake_add_data_files). Uploads and listings are not reads (catalog_dr's upload_file, the
    maintenance list paginator). One named seam is admitted: a function get_blob in the blob store adapter, the content_blobs
    port's read verb (rec-4291, slice 2b), which returns bytes to a caller and never feeds a table. Leg (b): the telemetry
    writer bundle's S3 client calls are exactly head_object, generate_presigned_url (put_object) and list_objects_v2."""
    every = _bundled()
    assert _SEAM[0] in every and "src/common/ducklake_runtime.py" in every
    for rel in every:
        calls, sql, _ = _scan(rel)
        assert not [c for c in calls if c[0] in _OBJECT_READS], (rel, calls)
        assert not sql, (rel, sql)
    writer = _bundled("telemetry_writer")
    used = {name for rel in writer for name, _ in _scan(rel)[0]}
    assert used == {"head_object", "generate_presigned_url", "list_objects_v2"}, used
    for rel in writer:
        text = (ROOT / rel).read_text(encoding="utf-8")
        if rel != _SEAM[0]:
            assert _SEAM[1] not in text, rel
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "generate_presigned_url":
                assert isinstance(node.args[0], ast.Constant) and node.args[0].value == "put_object", rel


def test_the_guard_flags_a_read_and_admits_only_the_named_seam(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        'def go(c, con):\n    c.get_object(Bucket="b")\n    con.execute("SELECT * FROM read_parquet(\'s3://b/x\')")\n'
        '    con.execute("COPY t FROM \'x\'")\n    c.upload_file("a", "b", "c")\n    c.list_objects_v2()\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(f"{__name__}.ROOT", tmp_path)
    calls, sql, _ = _scan("sample.py")
    assert [c[0] for c in calls] == ["get_object", "upload_file", "list_objects_v2"] and len(sql) == 2
    seam = tmp_path / _SEAM[0]
    seam.parent.mkdir(parents=True)
    seam.write_text(
        'def get_blob(c):\n    return c.get_object(Bucket="b")\n\ndef other(c):\n    c.get_object(Bucket="b")\n',
        encoding="utf-8",
    )
    calls, _, seams = _scan(_SEAM[0])
    assert seams == ["get_blob"] and [c[0] for c in calls] == ["get_object"] and calls[0][1] == 5


def _offline_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    pytest.importorskip("botocore")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA" + "0" * 16)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s" * 40)
    monkeypatch.setenv("AWS_SESSION_TOKEN", "tok" + "x" * 20)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    return store_mod.make_s3_client("eu-west-2")


@pytest.mark.aws
def test_real_presign_signs_length_host_and_checksum(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _offline_client(monkeypatch)
    grant = S3BlobStore(client, BLOB_ROOT, clock=lambda: NOW).grant_put(URI, SHA, 70000)
    parsed = urlparse(grant.url)
    query = {k.lower(): v[0] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
    assert parsed.hostname == "bucket.s3.eu-west-2.amazonaws.com" and parsed.path == "/" + BLOB_ROOT.prefix + URI
    assert query["x-amz-signedheaders"] == "content-length;host;x-amz-checksum-sha256" and query["x-amz-expires"] == "900"
    assert "x-amz-security-token" in query and not [
        k for k in query if k.startswith(("x-amz-checksum-", "x-amz-sdk-checksum"))
    ]


@pytest.mark.aws
def test_real_head_stub_carries_checksum_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from botocore.stub import Stubber

    client = _offline_client(monkeypatch)
    with Stubber(client) as stub:
        stub.add_response(
            "head_object",
            {**HEAD_OK, "LastModified": NOW - timedelta(days=1)},
            expected_params={"Bucket": "bucket", "Key": BLOB_ROOT.prefix + URI, "ChecksumMode": "ENABLED"},
        )
        assert S3BlobStore(client, BLOB_ROOT, clock=lambda: NOW).verify(URI, SHA, 70000) == "verified"
        stub.assert_no_pending_responses()
