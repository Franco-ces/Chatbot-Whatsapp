"""API tests for GET /api/telemetry/summary endpoint.

Tests cover:
- Unauthenticated request returns 401
- Authenticated request returns data
- Query parameter propagation
- DB failure returns 503 with TELEMETRY_DB_ERROR code

All asyncpg interactions are mocked — no real database required.
Uses httpx.AsyncClient (same pattern as test_faq_endpoints.py).
"""
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Mock asyncpg before importing interface (which imports telemetry)
if "asyncpg" not in sys.modules:
    _mock_asyncpg = MagicMock()
    _mock_asyncpg.create_pool = AsyncMock()
    sys.modules["asyncpg"] = _mock_asyncpg


# ─── Helper ──────────────────────────────────────────────────────────

async def _get_auth_token(client):
    """Obtain a valid JWT token from the /api/auth/login endpoint."""
    response = await client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "admin123"},
    )
    assert response.status_code == 200
    return response.json()["token"]


class TestTelemetrySummaryUnauthenticated:
    """TS-3: The endpoint is protected by AuthMiddleware."""

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self):
        """GET /api/telemetry/summary without auth returns 401."""
        import interface
        transport = httpx.ASGITransport(app=interface.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/telemetry/summary")

        assert response.status_code == 401


class TestTelemetrySummaryAuthenticated:
    """TS-1/TS-2: The endpoint returns aggregated data."""

    @pytest.mark.asyncio
    async def test_returns_success_with_data(self):
        """Authenticated request returns 200 with telemetry data."""
        import telemetry as _telemetry_mod
        import interface
        from error_codes import ErrorCode

        fake_data = {
            "total_messages": 100,
            "faq_hits": 20,
            "cache_hits": 15,
            "avg_rag_ms": 1200,
            "avg_send_ms": 300,
            "error_count": 5,
            "unique_users": 42,
            "daily": [
                {"date": "2026-06-03", "total_messages": 50, "faq_hits": 10,
                 "cache_hits": 8, "avg_rag_ms": 1100, "avg_send_ms": 280,
                 "error_count": 2, "unique_users": 21},
            ],
        }

        with patch.object(_telemetry_mod, "get_summary", new_callable=AsyncMock, return_value=fake_data):
            transport = httpx.ASGITransport(app=interface.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                token = await _get_auth_token(client)
                response = await client.get(
                    "/api/telemetry/summary",
                    headers={"Authorization": f"Bearer {token}"},
                )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["data"]["total_messages"] == 100
        assert body["data"]["faq_hits"] == 20
        assert len(body["data"]["daily"]) == 1

    @pytest.mark.asyncio
    async def test_days_parameter_propagated(self):
        """GET /api/telemetry/summary?days=14 passes days=14 to get_summary."""
        import telemetry as _telemetry_mod
        import interface

        fake_data = {
            "total_messages": 0, "faq_hits": 0, "cache_hits": 0,
            "avg_rag_ms": 0, "avg_send_ms": 0,
            "error_count": 0, "unique_users": 0, "daily": [],
        }
        mock_get = AsyncMock(return_value=fake_data)

        with patch.object(_telemetry_mod, "get_summary", mock_get):
            transport = httpx.ASGITransport(app=interface.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                token = await _get_auth_token(client)
                response = await client.get(
                    "/api/telemetry/summary?days=14",
                    headers={"Authorization": f"Bearer {token}"},
                )

        assert response.status_code == 200
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs.get("days") == 14

    @pytest.mark.asyncio
    async def test_db_failure_returns_503(self):
        """TS-4: DB failure returns 503 with TELEMETRY_DB_ERROR code."""
        import telemetry as _telemetry_mod
        import interface
        from exceptions import AppError
        from error_codes import ErrorCode

        with patch.object(_telemetry_mod, "get_summary", new_callable=AsyncMock,
                          side_effect=AppError(ErrorCode.TELEMETRY_DB_ERROR, detail="connection lost")):
            transport = httpx.ASGITransport(app=interface.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                token = await _get_auth_token(client)
                response = await client.get(
                    "/api/telemetry/summary",
                    headers={"Authorization": f"Bearer {token}"},
                )

        assert response.status_code == 503
        body = response.json()
        assert body["error"]["code"] == "E-TEL-001"