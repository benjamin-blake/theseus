"""Artifact-level halves of scripts.convergence_health.budget_ingest: reading the `budget` block
out of one selection-manifest archive, and the authenticated zip fetcher that downloads it.

Split out of the retired single-file test_budget_ingest.py monolith (rec-3288 wave-4 fixups).
"""

from __future__ import annotations

import json
import urllib.request
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from scripts.convergence_health import budget_ingest as bi

from .conftest import _archive, _budget_block


class TestExtractBudgetBlock:
    def test_returns_budget_block_when_present(self) -> None:
        block = _budget_block()
        assert bi.extract_budget_block(_archive({"selected": [], "budget": block})) == block

    def test_returns_none_for_pre_968_manifest_without_budget_key(self) -> None:
        assert bi.extract_budget_block(_archive({"selected": [], "timings": {}})) is None

    def test_returns_none_when_manifest_member_absent_from_archive(self) -> None:
        assert bi.extract_budget_block(_archive({"budget": {}}, member="other.json")) is None

    def test_returns_none_when_manifest_is_not_a_mapping(self) -> None:
        assert bi.extract_budget_block(_archive(["not", "a", "mapping"])) is None

    def test_returns_none_when_budget_key_is_not_a_mapping(self) -> None:
        assert bi.extract_budget_block(_archive({"budget": "breach"})) is None

    def test_raises_on_malformed_json(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            bi.extract_budget_block(_archive("{not json"))

    def test_raises_on_non_zip_bytes(self) -> None:
        with pytest.raises(zipfile.BadZipFile):
            bi.extract_budget_block(b"definitely not a zip")


class TestArtifactFetcher:
    def test_no_token_fails_loudly_instead_of_returning_an_empty_archive(self) -> None:
        fetcher = bi._make_artifact_fetcher("")
        with pytest.raises(RuntimeError, match="no GH_TOKEN/GITHUB_TOKEN"):
            fetcher("https://api.github.com/repos/o/r/actions/artifacts/1/zip")

    def test_authenticated_fetch_returns_the_archive_bytes(self) -> None:
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b"PK-zip-bytes"
        with patch("urllib.request.build_opener", return_value=opener):
            fetcher = bi._make_artifact_fetcher("t0ken")
            assert fetcher("https://api.github.com/repos/o/r/actions/artifacts/1/zip") == b"PK-zip-bytes"
        request = opener.open.call_args.args[0]
        assert request.get_header("Authorization") == "Bearer t0ken"

    def test_redirect_to_blob_storage_strips_the_github_authorization_header(self) -> None:
        """GitHub 302s the artifact zip endpoint to blob storage; unlike curl, urllib forwards the
        Authorization header across hosts, which the storage backend rejects."""
        request = urllib.request.Request(
            "https://api.github.com/repos/o/r/actions/artifacts/1/zip",
            headers={"Authorization": "Bearer t0ken", "Accept": "application/vnd.github+json"},
        )
        redirected = bi._AuthStrippingRedirectHandler().redirect_request(
            request, None, 302, "Found", {}, "https://blob.example.invalid/artifact.zip"
        )
        assert redirected is not None
        assert redirected.get_header("Authorization") is None
        assert redirected.get_header("Accept") == "application/vnd.github+json"
