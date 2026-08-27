"""Retired-provider concern of src/data/handlers/scheduled_agent_handler.py (rec-2709 Wave 11).

Covers TestRetiredProvider (Decision 116: copilot-sdk, gemini). Split from
tests/test_scheduled_agent_handler.py.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import src.data.handlers.scheduled_agent_handler as handler_mod
from src.data.handlers.scheduled_agent_handler import RetiredProviderError, handler


class TestRetiredProvider:
    """Tests for the Decision 116 retired-provider path (copilot-sdk, gemini).

    Decision 116 supersedes Decision 49: copilot-sdk and gemini are retired
    scheduled-agent providers. The handler raises RetiredProviderError
    (caught locally) instead of silently misrouting to github-models.
    """

    @pytest.fixture(autouse=True)
    def _enable_agents(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SCHEDULED_AGENTS_ENABLED", "true")

    def test_retired_provider_error_is_a_runtime_error(self) -> None:
        assert issubclass(RetiredProviderError, RuntimeError)

    @pytest.mark.parametrize("provider", ["copilot-sdk", "gemini"])
    def test_handler_raises_and_records_retired_provider_as_failure(self, provider: str) -> None:
        """Retired providers fail loudly (no silent misroute to github-models)."""
        agent = {
            "name": "doc-freshness",
            "cron": "0 6 * * 1",
            "model": "claude-haiku-4.5",
            "prompt_path": ".github/prompts/scheduled/doc-freshness.prompt.md",
            "provider": provider,
        }

        with (
            patch.object(handler_mod, "_get_github_pat", return_value="ghp_test") as mock_pat,
            patch.object(handler_mod, "_load_manifest", return_value=[agent]),
            patch.object(handler_mod, "_load_prompt", return_value="prompt"),
            patch("scripts.run_scheduled_agent.is_agent_due", return_value=True),
            patch("scripts.llm.github_models_client.chat_completion") as mock_gh,
        ):
            result = handler({}, None)

        mock_gh.assert_not_called()
        mock_pat.assert_not_called()
        assert result["agents_run"] == 0
        assert result["agents_failed"] == 1

    def test_retired_provider_failure_message_names_decision_116(self, caplog: pytest.LogCaptureFixture) -> None:
        agent = {
            "name": "rec-curator",
            "cron": "0 8 * * *",
            "model": "claude-sonnet-4.6",
            "prompt_path": ".github/prompts/scheduled/rec-curator.prompt.md",
            "provider": "copilot-sdk",
        }

        with (
            patch.object(handler_mod, "_load_manifest", return_value=[agent]),
            patch.object(handler_mod, "_load_prompt", return_value="prompt"),
            patch("scripts.run_scheduled_agent.is_agent_due", return_value=True),
            caplog.at_level("ERROR"),
        ):
            result = handler({}, None)

        assert result["agents_failed"] == 1
        assert "Decision 116" in caplog.text
        assert "retired" in caplog.text.lower()
