"""Tests for `evo_client._get_evo_api_key()`.

Covers env-var resolution: EVO_API_KEY takes priority, EVOLUTION_API_KEY
is the legacy fallback with deprecation warning, and empty string when
neither is set.
"""

from unittest.mock import patch

import pytest

from evo_client import _get_evo_api_key


class TestGetEvoApiKey:
    def test_evo_api_key_takes_priority(self, monkeypatch):
        """GIVEN EVO_API_KEY is set AND EVOLUTION_API_KEY is also set
        WHEN _get_evo_api_key is called
        THEN it MUST use EVO_API_KEY value."""
        monkeypatch.setenv("EVO_API_KEY", "new-key")
        monkeypatch.setenv("EVOLUTION_API_KEY", "old-key")
        assert _get_evo_api_key() == "new-key"

    def test_legacy_fallback_with_warning(self, monkeypatch, caplog):
        """GIVEN only EVOLUTION_API_KEY is set
        WHEN _get_evo_api_key is called
        THEN it MUST use EVOLUTION_API_KEY value
        AND emit a deprecation warning."""
        monkeypatch.delenv("EVO_API_KEY", raising=False)
        monkeypatch.setenv("EVOLUTION_API_KEY", "legacy-key")
        caplog.set_level("WARNING")
        result = _get_evo_api_key()
        assert result == "legacy-key"
        assert "[LEGACY]" in caplog.text
        assert "EVOLUTION_API_KEY" in caplog.text
        assert "EVO_API_KEY" in caplog.text

    def test_returns_empty_when_neither_set(self, monkeypatch):
        """GIVEN neither EVO_API_KEY nor EVOLUTION_API_KEY are set
        WHEN _get_evo_api_key is called
        THEN it MUST return empty string."""
        monkeypatch.delenv("EVO_API_KEY", raising=False)
        monkeypatch.delenv("EVOLUTION_API_KEY", raising=False)
        assert _get_evo_api_key() == ""
