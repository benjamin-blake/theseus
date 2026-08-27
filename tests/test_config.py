"""Tests for src/common/config.py -- the platform Config loader."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from src.common.config import Config

pytestmark = pytest.mark.unit


def _write_config(body: str) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as fh:
        fh.write(body)
        return fh.name


def test_config_initialization() -> None:
    config = Config()
    assert config is not None


def test_config_defaults() -> None:
    config = Config()

    assert config.get("nonexistent.key", "default") == "default"
    assert isinstance(config.aws_region, str)


def test_config_from_file() -> None:
    config_path = _write_config(
        """
        aws:
          region: eu-west-2
          s3_bucket: test-bucket
        """
    )
    try:
        config = Config(config_path=config_path)
        assert config.get("aws.region") == "eu-west-2"
        assert config.get("aws.s3_bucket") == "test-bucket"
        assert config.aws_region == "eu-west-2"
        assert config.s3_bucket == "test-bucket"
    finally:
        os.unlink(config_path)


def test_config_nested_access() -> None:
    config_path = _write_config(
        """
        level1:
          level2:
            level3: value
        """
    )
    try:
        config = Config(config_path=config_path)
        assert config.get("level1.level2.level3") == "value"
        assert config.get("level1.level2.nonexistent", "default") == "default"
        assert config.get("level1.level2.level3.deeper", "default") == "default"
    finally:
        os.unlink(config_path)


def test_missing_config_file_degrades_to_empty(tmp_path: Path) -> None:
    """A missing config file warns and yields an empty config rather than raising."""
    config = Config(config_path=str(tmp_path / "absent.yaml"))
    assert config.get("aws.region", "fallback") == "fallback"


def test_empty_yaml_file_yields_empty_config() -> None:
    config_path = _write_config("")
    try:
        config = Config(config_path=config_path)
        assert config.get("anything", "default") == "default"
    finally:
        os.unlink(config_path)


def test_aws_profile_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_PROFILE", "agent_platform")
    assert Config().aws_profile == "agent_platform"


def test_aws_profile_none_when_env_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    assert Config().aws_profile is None


def test_aws_region_falls_back_to_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    config = Config(config_path=str(tmp_path / "absent.yaml"))
    assert config.aws_region == "us-east-1"


def test_s3_bucket_falls_back_to_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("S3_BUCKET", "env-bucket")
    config = Config(config_path=str(tmp_path / "absent.yaml"))
    assert config.s3_bucket == "env-bucket"


def test_explicit_env_var_selects_config_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """THESEUS_CONFIG takes priority over the ENVIRONMENT-derived filename."""
    config_path = _write_config("aws:\n  region: eu-central-1\n")
    try:
        monkeypatch.setenv("THESEUS_CONFIG", config_path)
        monkeypatch.setenv("ENVIRONMENT", "personal")
        config = Config()
        assert config.config_path == config_path
        assert config.aws_region == "eu-central-1"
    finally:
        os.unlink(config_path)


def test_personal_environment_selects_personal_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THESEUS_CONFIG", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "personal")
    assert Config().config_path.endswith("config.personal.yaml")


def test_unknown_environment_falls_back_to_base_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THESEUS_CONFIG", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "unrecognised")
    assert Config().config_path.endswith("config.yaml")


def test_config_validate_rejects_empty_string() -> None:
    """validate() rejects both None and empty-string values for required fields."""
    config_path = _write_config('aws:\n  region: ""\n')
    try:
        config = Config(config_path=config_path, validate=False)
        with pytest.raises(ValueError, match="Missing required configuration fields"):
            config.validate()
    finally:
        os.unlink(config_path)


def test_config_validate_passes_when_region_present() -> None:
    config_path = _write_config("aws:\n  region: eu-west-2\n")
    try:
        Config(config_path=config_path, validate=True)
    finally:
        os.unlink(config_path)
