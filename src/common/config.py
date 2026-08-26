"""Configuration management for the platform.

Credential Resolution:
    AWS credentials are resolved automatically in the following order:
    1. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
    2. AWS_PROFILE environment variable
    3. Cached credentials in ~/.aws/credentials
    4. IAM instance role (if running on AWS compute)
"""

import logging
import os
from typing import Any, Dict

import yaml

logger = logging.getLogger(__name__)


class Config:
    """Central configuration manager.

    Loads configuration from YAML file with environment variable overrides.
    """

    def __init__(self, config_path: str | None = None, validate: bool = False) -> None:
        """Initialize configuration.

        Args:
            config_path: Path to config.yaml. If None, uses THESEUS_CONFIG env var
                        or default path relative to project root.
            validate: If True, call validate() after loading config.
        """
        if config_path is None:
            # Resolve config path using the following priority:
            # 1. THESEUS_CONFIG env var (explicit override)
            # 2. ENVIRONMENT env var: 'personal' -> config.personal.yaml
            # 3. Fall back to config.yaml (base / Lambda defaults)
            explicit = os.environ.get("THESEUS_CONFIG")
            if explicit:
                config_path = explicit
            else:
                env = os.environ.get("ENVIRONMENT", "")
                base_dir = os.path.join(os.path.dirname(__file__), "..", "..")
                env_map = {"personal": "config.personal.yaml"}
                filename = env_map.get(env, "config.yaml")
                config_path = os.path.join(base_dir, "config", filename)

        self.config_path = config_path
        self._config: Dict[str, Any] = {}
        self._aws_profile = os.environ.get("AWS_PROFILE")
        self._load_config()
        if validate:
            self.validate()

    def _load_config(self) -> None:
        """Load configuration from YAML file.

        If config file doesn't exist, logs a warning and uses an empty dict.
        This allows tests and CI environments to proceed without a config file.
        Explicit validation errors (via validate()) will catch missing config.
        """
        if not os.path.exists(self.config_path):
            logger.warning(f"Config file not found: {self.config_path} - using empty config")
            self._config = {}
            return

        with open(self.config_path, "r") as f:
            self._config = yaml.safe_load(f) or {}

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by dot-separated key.

        Args:
            key: Dot-separated key (e.g., 'aws.region')
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        keys = key.split(".")
        value = self._config

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default

            if value is None:
                return default

        return value

    @property
    def aws_profile(self) -> str | None:
        """Get AWS profile name.

        Used for boto3 credential resolution. Set via AWS_PROFILE env var.
        """
        return self._aws_profile

    @property
    def aws_region(self) -> str:
        """Get AWS region for API calls.

        Resolved from config.yaml or AWS_REGION environment variable.
        """
        return self.get("aws.region", os.environ.get("AWS_REGION", "eu-west-2"))

    @property
    def s3_bucket(self) -> str | None:
        """Get S3 data lake bucket name.

        Resolved from config.yaml or S3_BUCKET environment variable.
        """
        return self.get("aws.s3_bucket", os.environ.get("S3_BUCKET"))

    def validate(self) -> None:
        """Validate required configuration fields.

        Raises:
            ValueError: If required fields are missing or invalid.
        """
        required = ["aws.region"]

        missing = [key for key in required if not self.get(key)]

        if missing:
            raise ValueError(f"Missing required configuration fields: {', '.join(missing)}\nConfig file: {self.config_path}")


# Global configuration instance
config = Config()
