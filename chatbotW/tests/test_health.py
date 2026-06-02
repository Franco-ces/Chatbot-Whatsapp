"""Tests para health.py (PR 3 — bot decoupling).

3 tests, como pide el design:
1. instance_name se pasa explicito (no se lee de wa_client)
2. Agregacion de status (ok / degraded / unhealthy)
3. Branch con wa_client=None
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from health import run_health_probes


TEST_INSTANCE = "bot_health_test"


def _stub_wa_client():
    """Stub con api_url/api_key pero SIN instance_name (post-PR-3)."""
    class StubWaClient:
        api_url = "https://evolution.api"
        api_key = "test-key"
    return StubWaClient()


class TestExplicitInstanceName:
    """`run_health_probes(wa_client, rag, *, instance_name)` — kwarg keyword-only."""

    @pytest.mark.asyncio
    async def test_requiere_instance_name_kwarg(self):
        """Sin instance_name: TypeError explicito (keyword-only, sin default)."""
        with pytest.raises(TypeError) as exc_info:
            await run_health_probes(_stub_wa_client(), MagicMock())
        assert "instance_name" in str(exc_info.value)


class TestAggregation:
    """Logica de agregacion: all ok -> ok, all down -> unhealthy, mix -> degraded."""

    @pytest.mark.asyncio
    async def test_aggregation(self):
        """Cubre los 3 caminos en un test:
        - all ok -> overall 'ok'
        - mix (rag down o evo down) -> 'degraded'
        - all down -> 'unhealthy'
        """
        wa = _stub_wa_client()
        rag_ok = MagicMock()
        # all ok
        with patch("health.check_evolution_api", new=AsyncMock(return_value={"status": "ok", "duration_ms": 5})):
            r = await run_health_probes(wa, rag_ok, instance_name=TEST_INSTANCE)
        assert r["status"] == "ok"

        # degraded: RAG down
        with patch("health.check_evolution_api", new=AsyncMock(return_value={"status": "ok", "duration_ms": 5})):
            r = await run_health_probes(wa, None, instance_name=TEST_INSTANCE)
        assert r["status"] == "degraded"

        # degraded: Evolution down
        with patch(
            "health.check_evolution_api",
            new=AsyncMock(return_value={"status": "unhealthy", "duration_ms": 50, "detail": "timeout"}),
        ):
            r = await run_health_probes(wa, rag_ok, instance_name=TEST_INSTANCE)
        assert r["status"] == "degraded"
        assert r["components"]["evolution_api"]["detail"] == "timeout"

        # all down
        with patch(
            "health.check_evolution_api",
            new=AsyncMock(return_value={"status": "unhealthy", "duration_ms": 0, "detail": "n/a"}),
        ):
            r = await run_health_probes(None, None, instance_name=TEST_INSTANCE)
        assert r["status"] == "unhealthy"


class TestMissingWaClient:
    """wa_client=None: el component evolution_api es unhealthy con detalle."""

    @pytest.mark.asyncio
    async def test_wa_client_none_skips_evolution_check(self):
        """Sin wa_client, check_evolution_api NO se llama (no hay api_url)
        y el component es unhealthy con mensaje claro."""
        with patch("health.check_evolution_api", new=AsyncMock()) as mock_check:
            result = await run_health_probes(
                None, None, instance_name=TEST_INSTANCE,
            )
        mock_check.assert_not_called()
        assert result["components"]["evolution_api"]["status"] == "unhealthy"
        assert "WhatsApp client not initialized" in result["components"]["evolution_api"]["detail"]
