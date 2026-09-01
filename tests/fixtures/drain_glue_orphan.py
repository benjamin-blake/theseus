"""Test doubles for scripts/ops/drain_glue_orphan.py.

Lives in tests/fixtures/ (an importable package whose names never start with `test_`, so it is
exempt from the cross-test-import guard by construction) because tests/ops/test_drain_glue_orphan.py
would otherwise carry these fakes plus its own cases past the 500-SLOC cap. No network, no
warehouse write -- every double is a pure in-memory stand-in for an injected seam.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from scripts.ci import reconcile_target
from scripts.ops.drain_glue_orphan import _TFSTATE_BUCKET, _TFSTATE_KEY

RED_RECORD = {"status": "red", "commit_sha": "fake-red-commit-sha"}


def unreachable_file_rec(fields: dict[str, Any], profile: str | None = None) -> str:
    raise AssertionError("file_rec must not be called")


class FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class MultiKeyS3Client:
    """Dispatches get_object by (Bucket, Key) -- the convergence record and the tfstate object
    live at different keys but share the ONE injected client, mirroring the live wiring."""

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
    """phase_converge reads the convergence record TWICE: red before dispatch (precondition), then
    again after the run lands (the post-apply fact). `dispatched` is the SAME list the test's fake
    dispatcher appends to, so the second read only turns green once a dispatch actually fired --
    mirrors a live apply landing between the two reads."""

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
