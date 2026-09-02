"""Test doubles for scripts/ops/drain_glue_orphan (the package).

Lives in tests/fixtures/ (an importable package whose names never start with `test_`, so it is
exempt from the cross-test-import guard by construction) because tests/ops/test_drain_glue_orphan.py
would otherwise carry these fakes plus its own cases past the 500-SLOC cap. No network, no
warehouse write -- every double is a pure in-memory stand-in for an injected seam.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from scripts.ci import reconcile_target
from scripts.ops.drain_glue_orphan import _TFSTATE_BUCKET, _TFSTATE_KEY

RED_RECORD = {"status": "red", "commit_sha": "fake-red-commit-sha"}

_PAYLOADS_DIR = Path(__file__).resolve().parent / "drain_glue_orphan_payloads"


def load_payload(name: str) -> Any:
    """Load a committed real mcp__github__ payload fixture by filename (e.g.
    'reconcile_runs.json') from tests/fixtures/drain_glue_orphan_payloads/."""
    return json.loads((_PAYLOADS_DIR / name).read_text(encoding="utf-8"))


def unreachable_file_rec(fields: dict[str, Any], profile: str | None = None) -> str:
    raise AssertionError("file_rec must not be called")


class FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class MultiKeyS3Client:
    """Dispatches get_object by (Bucket, Key) -- the convergence record and the tfstate object
    live at different keys. Used as BOTH profile_s3_client and state_s3_client wherever a test
    does not care about the per-leg identity split itself (that split is TestProfileLegs' own
    concern, exercised via recording_boto3 below)."""

    def __init__(self, objects: dict[tuple[str, str], Any]) -> None:
        self._objects = objects

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        obj = self._objects.get((Bucket, Key))
        if obj is None:
            raise RuntimeError(f"NoSuchKey: {Bucket}/{Key}")
        return {"Body": FakeBody(json.dumps(obj).encode("utf-8"))}


def make_s3(record: dict[str, Any] | None, orphan_present: bool) -> MultiKeyS3Client:
    resources = [{"type": "aws_glue_catalog_database", "name": "ops"}] if orphan_present else []
    objects: dict[tuple[str, str], Any] = {(_TFSTATE_BUCKET, _TFSTATE_KEY): {"resources": resources}}
    if record is not None:
        objects[(reconcile_target.CONVERGENCE_BUCKET, reconcile_target.CONVERGENCE_KEY)] = record
    return MultiKeyS3Client(objects)


def reader_returning(status: str | None) -> Callable[[str], list[dict[str, Any]]]:
    def _r(rec_id: str) -> list[dict[str, Any]]:
        return [] if status is None else [{"status": status}]

    return _r


class ProgressiveS3Client:
    """converge_verify reads the convergence record a second time, AFTER the run lands (the
    post-apply fact). `dispatched` is the SAME list the test's fake dispatch tracker appends to,
    so the second read only turns green once a dispatch actually fired -- mirrors a live apply
    landing between the gate read and the verify read."""

    def __init__(self, tfstate_orphan_present: bool, dispatched: list[str]) -> None:
        self._tfstate_orphan_present = tfstate_orphan_present
        self._dispatched = dispatched

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        body: dict[str, Any]
        if (Bucket, Key) == (_TFSTATE_BUCKET, _TFSTATE_KEY):
            resources = [{"type": "aws_glue_catalog_database", "name": "ops"}] if self._tfstate_orphan_present else []
            body = {"resources": resources}
        elif (Bucket, Key) == (reconcile_target.CONVERGENCE_BUCKET, reconcile_target.CONVERGENCE_KEY):
            body = {"status": "green"} if self._dispatched else RED_RECORD
        else:
            raise RuntimeError(f"NoSuchKey: {Bucket}/{Key}")
        return {"Body": FakeBody(json.dumps(body).encode("utf-8"))}


class FakeCompletedProcess:
    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode


class RecordingS3Client:
    """get_object dispatch identical to MultiKeyS3Client, plus a shared `calls` log of
    (profile_name, Bucket, Key) for every call -- lets TestProfileLegs assert structurally which
    profile's client reached the tfstate key and which reached the convergence-record key."""

    def __init__(
        self, profile_name: str | None, objects: dict[tuple[str, str], Any], calls: list[tuple[str | None, str, str]]
    ) -> None:
        self._profile_name = profile_name
        self._objects = objects
        self._calls = calls

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        self._calls.append((self._profile_name, Bucket, Key))
        obj = self._objects.get((Bucket, Key))
        if obj is None:
            raise RuntimeError(f"NoSuchKey: {Bucket}/{Key}")
        return {"Body": FakeBody(json.dumps(obj).encode("utf-8"))}


def recording_boto3(objects: dict[tuple[str, str], Any]) -> tuple[Any, list[tuple[str | None, str, str]]]:
    """A fake boto3 module whose Session(profile_name=...).client("s3") returns a
    RecordingS3Client stamped with that profile name. `calls` accumulates every get_object call
    across every client this fake module creates, in order -- the structural proof VP5 requires:
    the tfstate key is reached ONLY by the client built from --state-profile."""
    calls: list[tuple[str | None, str, str]] = []

    class _RecordingSession:
        def __init__(self, profile_name: str | None = None) -> None:
            self.profile_name = profile_name

        def client(self, name: str) -> RecordingS3Client:
            return RecordingS3Client(self.profile_name, objects, calls)

    class _FakeBoto3Module:
        Session = _RecordingSession

    return _FakeBoto3Module(), calls
