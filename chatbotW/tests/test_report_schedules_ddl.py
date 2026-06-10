"""Tests for the report_schedules DDL addition in telemetry.py.

TDD RED: These tests verify that init_pool bootstraps the
report_schedules table alongside bot_messages.
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock asyncpg before importing telemetry
if "asyncpg" not in sys.modules:
    _mock_asyncpg = MagicMock()
    _mock_asyncpg.create_pool = AsyncMock()
    sys.modules["asyncpg"] = _mock_asyncpg

import telemetry as _telemetry_mod
from telemetry import init_pool, close_pool


@pytest.fixture(autouse=True)
def _reset_telemetry_module():
    """Reset the telemetry module global state between tests."""
    original_pool = _telemetry_mod._pool
    _telemetry_mod._pool = None
    yield
    _telemetry_mod._pool = original_pool


def _make_pool_mock():
    """Create a mock asyncpg.Pool that supports the async context manager."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])

    pool = AsyncMock()
    pool.acquire = MagicMock()

    class _AcquireContext:
        async def __aenter__(self_inner):
            return conn
        async def __aexit__(self_inner, *args):
            pass

    pool.acquire.return_value = _AcquireContext()
    pool.close = AsyncMock()
    return pool, conn


class TestReportSchedulesDDL:
    """Task 1.2: init_pool must bootstrap report_schedules table."""

    @pytest.mark.asyncio
    async def test_init_pool_executes_report_schedules_ddl(self):
        """After init_pool, the report_schedules DDL must have been executed."""
        pool, conn = _make_pool_mock()

        with patch.dict(os.environ, {
            "POSTGRES_USER": "testuser",
            "POSTGRES_PASSWORD": "testpass",
            "POSTGRES_DB": "testdb",
            "POSTGRES_HOST": "testhost",
        }), patch.object(_telemetry_mod, "asyncpg", MagicMock(
            create_pool=AsyncMock(return_value=pool)
        )):
            await init_pool()

            # Collect all SQL that was executed
            sqls = [str(call[0][0]) for call in conn.execute.call_args_list]
            # Must include report_schedules table creation
            ddl_found = any("report_schedules" in s for s in sqls)
            assert ddl_found, f"report_schedules DDL not found in executed SQLs: {sqls}"

            await close_pool()

    @pytest.mark.asyncio
    async def test_init_pool_creates_index_on_activo(self):
        """After init_pool, an index on activo must have been created."""
        pool, conn = _make_pool_mock()

        with patch.dict(os.environ, {
            "POSTGRES_USER": "testuser",
            "POSTGRES_PASSWORD": "testpass",
            "POSTGRES_DB": "testdb",
            "POSTGRES_HOST": "testhost",
        }), patch.object(_telemetry_mod, "asyncpg", MagicMock(
            create_pool=AsyncMock(return_value=pool)
        )):
            await init_pool()

            sqls = [str(call[0][0]) for call in conn.execute.call_args_list]
            idx_found = any("idx_report_schedules" in s for s in sqls)
            assert idx_found, f"report_schedules index not found in executed SQLs: {sqls}"

            await close_pool()

    @pytest.mark.asyncio
    async def test_schedules_ddl_contains_all_required_columns(self):
        """The DDL must include: id, tipo, parametros, hora_envio, destino, activo, ultimo_envio."""
        # Read the DDL string from the module - this is a pure code inspection test
        from telemetry import _SCHEDULES_DDL
        ddl = _SCHEDULES_DDL
        assert "id" in ddl
        assert "tipo" in ddl
        assert "parametros" in ddl
        assert "hora_envio" in ddl
        assert "destino" in ddl
        assert "activo" in ddl
        assert "ultimo_envio" in ddl
        assert "created_at" in ddl
        assert "updated_at" in ddl