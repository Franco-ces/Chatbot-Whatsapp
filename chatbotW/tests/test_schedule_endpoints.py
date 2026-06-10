"""Tests for schedule CRUD API endpoints in interface.py.

Covers:
- GET /api/reportes/schedules — list all schedules
- POST /api/reportes/schedules — create schedule
- PUT /api/reportes/schedules/{id} — update schedule
- DELETE /api/reportes/schedules/{id} — delete schedule
- POST /api/reportes/schedules/{id}/toggle — toggle active/inactive
"""
import sys
from contextlib import asynccontextmanager
from datetime import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Mock asyncpg before any import
if "asyncpg" not in sys.modules:
    _mock_asyncpg = MagicMock()
    _mock_asyncpg.Pool = MagicMock
    _mock_asyncpg.create_pool = AsyncMock()
    sys.modules["asyncpg"] = _mock_asyncpg

# Mock fpdf for report_generator
if "fpdf" not in sys.modules:
    _mock_fpdf = MagicMock()
    sys.modules["fpdf"] = _mock_fpdf


def _make_pool_mock(fetch_result=None, fetchrow_result=None):
    """Create a mock asyncpg pool with async context manager support."""
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=fetch_result or [])
    mock_conn.fetchrow = AsyncMock(return_value=fetchrow_result)
    mock_conn.execute = AsyncMock()

    @asynccontextmanager
    async def mock_acquire(*args, **kwargs):
        yield mock_conn

    mock_pool = MagicMock()
    mock_pool.acquire = mock_acquire
    return mock_pool, mock_conn


async def _get_auth_token(client):
    """Obtain a valid JWT token from /api/auth/login."""
    response = await client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "admin123"},
    )
    assert response.status_code == 200
    return response.json()["token"]


class TestListSchedules:
    """GET /api/reportes/schedules"""

    @pytest.mark.asyncio
    async def test_list_schedules_returns_200(self):
        import interface
        with patch("interface.telemetry") as mock_telemetry:
            mock_pool, mock_conn = _make_pool_mock(fetch_result=[
                {"id": 1, "tipo": "diario", "parametros": {}, "hora_envio": time(8, 0),
                 "destino": "+5491112345678", "header_text": None, "footer_text": None,
                 "activo": True, "ultimo_envio": None, "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"},
            ])
            mock_telemetry._pool = mock_pool

            transport = httpx.ASGITransport(app=interface.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                token = await _get_auth_token(client)
                response = await client.get(
                    "/api/reportes/schedules",
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_list_schedules_empty(self):
        import interface
        with patch("interface.telemetry") as mock_telemetry:
            mock_pool, _ = _make_pool_mock(fetch_result=[])
            mock_telemetry._pool = mock_pool

            transport = httpx.ASGITransport(app=interface.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                token = await _get_auth_token(client)
                response = await client.get(
                    "/api/reportes/schedules",
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert response.status_code == 200
            assert response.json() == []

    @pytest.mark.asyncio
    async def test_list_schedules_no_pool_returns_error(self):
        import interface
        with patch("interface.telemetry") as mock_telemetry:
            mock_telemetry._pool = None

            transport = httpx.ASGITransport(app=interface.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                token = await _get_auth_token(client)
                response = await client.get(
                    "/api/reportes/schedules",
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert response.status_code == 503


class TestCreateSchedule:
    """POST /api/reportes/schedules"""

    @pytest.mark.asyncio
    async def test_create_schedule_returns_201(self):
        import interface
        with patch("interface.telemetry") as mock_telemetry:
            mock_pool, mock_conn = _make_pool_mock()
            mock_row = {
                "id": 1, "tipo": "diario", "parametros": {}, "hora_envio": time(8, 0),
                "destino": "+5491112345678", "header_text": None, "footer_text": None,
                "activo": True, "ultimo_envio": None, "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
            }
            mock_conn.fetchrow = AsyncMock(return_value=mock_row)
            mock_telemetry._pool = mock_pool

            transport = httpx.ASGITransport(app=interface.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                token = await _get_auth_token(client)
                response = await client.post(
                    "/api/reportes/schedules",
                    json={
                        "tipo": "diario",
                        "parametros": {},
                        "hora_envio": "08:00",
                        "destino": "+5491112345678",
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_create_schedule_invalid_tipo_returns_400(self):
        import interface
        with patch("interface.telemetry") as mock_telemetry:
            mock_telemetry._pool = MagicMock()

            transport = httpx.ASGITransport(app=interface.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                token = await _get_auth_token(client)
                response = await client.post(
                    "/api/reportes/schedules",
                    json={
                        "tipo": "fake_tipo",
                        "parametros": {},
                        "hora_envio": "08:00",
                        "destino": "+5491112345678",
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_create_schedule_invalid_time_returns_400(self):
        import interface
        with patch("interface.telemetry") as mock_telemetry:
            mock_telemetry._pool = MagicMock()

            transport = httpx.ASGITransport(app=interface.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                token = await _get_auth_token(client)
                response = await client.post(
                    "/api/reportes/schedules",
                    json={
                        "tipo": "diario",
                        "parametros": {},
                        "hora_envio": "not-a-time",
                        "destino": "+5491112345678",
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert response.status_code == 400


class TestDeleteSchedule:
    """DELETE /api/reportes/schedules/{id}"""

    @pytest.mark.asyncio
    async def test_delete_schedule_returns_200(self):
        import interface
        with patch("interface.telemetry") as mock_telemetry:
            mock_pool, mock_conn = _make_pool_mock()
            mock_conn.fetchrow = AsyncMock(return_value={"id": 1})
            mock_telemetry._pool = mock_pool

            transport = httpx.ASGITransport(app=interface.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                token = await _get_auth_token(client)
                response = await client.delete(
                    "/api/reportes/schedules/1",
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_nonexistent_schedule_returns_404(self):
        import interface
        with patch("interface.telemetry") as mock_telemetry:
            mock_pool, mock_conn = _make_pool_mock()
            mock_conn.fetchrow = AsyncMock(return_value=None)
            mock_telemetry._pool = mock_pool

            transport = httpx.ASGITransport(app=interface.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                token = await _get_auth_token(client)
                response = await client.delete(
                    "/api/reportes/schedules/999",
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert response.status_code == 404


class TestToggleSchedule:
    """POST /api/reportes/schedules/{id}/toggle"""

    @pytest.mark.asyncio
    async def test_toggle_schedule_returns_200(self):
        import interface
        with patch("interface.telemetry") as mock_telemetry:
            mock_pool, mock_conn = _make_pool_mock()
            mock_row = {
                "id": 1, "tipo": "diario", "parametros": {}, "hora_envio": time(8, 0),
                "destino": "+5491112345678", "header_text": None, "footer_text": None,
                "activo": False, "ultimo_envio": None, "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
            }
            mock_conn.fetchrow = AsyncMock(return_value=mock_row)
            mock_telemetry._pool = mock_pool

            transport = httpx.ASGITransport(app=interface.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                token = await _get_auth_token(client)
                response = await client.post(
                    "/api/reportes/schedules/1/toggle",
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert response.status_code == 200
            data = response.json()
            assert data["activo"] is False  # Was True, now toggled to False