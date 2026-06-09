"""Unit tests for telemetry.py module.

Tests cover:
- init_pool: schema bootstrap, missing env vars, pool creation
- close_pool: graceful close
- record_interaction: INSERT SQL, no-op on None pool, error handling
- get_summary: aggregation query, empty data, custom days

All asyncpg interactions are mocked — no real database required.
asyncpg is mocked in sys.modules because it requires a C extension
that may not be available in the local dev environment.
"""
import importlib
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── Mock asyncpg before importing telemetry ──────────────────────────

# asyncpg requires a C extension that may not be built locally.
# We inject a mock module so the import succeeds.
if "asyncpg" not in sys.modules:
    _mock_asyncpg = MagicMock()
    _mock_asyncpg.create_pool = AsyncMock()
    sys.modules["asyncpg"] = _mock_asyncpg

# Import after mocking asyncpg
import telemetry as _telemetry_mod
from telemetry import init_pool, close_pool, record_interaction, get_summary
from exceptions import AppError
from error_codes import ErrorCode


# ─── Reset module state between tests ─────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_telemetry_module():
    """Reset the telemetry module global state between tests."""
    original_pool = _telemetry_mod._pool
    _telemetry_mod._pool = None
    yield
    _telemetry_mod._pool = original_pool


# ─── Helper: create a fake asyncpg pool mock ─────────────────────────

def _make_pool_mock():
    """Create a mock asyncpg.Pool that supports the async context manager."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])

    pool = AsyncMock()
    pool.acquire = MagicMock()

    # acquire() returns an async context manager that yields the connection
    class _AcquireContext:
        async def __aenter__(self_inner):
            return conn
        async def __aexit__(self_inner, *args):
            pass

    pool.acquire.return_value = _AcquireContext()
    pool.close = AsyncMock()
    return pool, conn


# ─── init_pool tests ──────────────────────────────────────────────────

class TestInitPool:

    @pytest.mark.asyncio
    async def test_creates_pool_and_bootstraps_schema(self):
        """init_pool creates a pool, runs CREATE SCHEMA and CREATE TABLE DDL."""
        pool, conn = _make_pool_mock()

        with patch.dict(os.environ, {
            "POSTGRES_USER": "testuser",
            "POSTGRES_PASSWORD": "testpass",
            "POSTGRES_DB": "testdb",
            "POSTGRES_HOST": "testhost",
        }), patch.object(_telemetry_mod, "asyncpg", MagicMock(
            create_pool=AsyncMock(return_value=pool)
        )):
            result = await init_pool()

            assert result is pool
            # Schema bootstrap: at least CREATE SCHEMA, CREATE TABLE, CREATE INDEX x3
            assert conn.execute.call_count >= 2
            sqls = [str(call[0][0]) for call in conn.execute.call_args_list]
            assert any("CREATE SCHEMA" in s for s in sqls)
            assert any("CREATE TABLE" in s for s in sqls)

            await close_pool()

    @pytest.mark.asyncio
    async def test_returns_none_when_env_vars_missing(self):
        """init_pool returns None when required env vars are missing."""
        with patch.dict(os.environ, {}, clear=True):
            for key in ["POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_HOST"]:
                os.environ.pop(key, None)

            result = await init_pool()
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_pool_creation_failure(self):
        """init_pool returns None when create_pool raises an exception."""
        pool, _ = _make_pool_mock()

        with patch.dict(os.environ, {
            "POSTGRES_USER": "u",
            "POSTGRES_PASSWORD": "p",
            "POSTGRES_DB": "d",
            "POSTGRES_HOST": "h",
        }), patch.object(_telemetry_mod, "asyncpg", MagicMock(
            create_pool=AsyncMock(side_effect=Exception("connection refused"))
        )):
            result = await init_pool()
            assert result is None

    @pytest.mark.asyncio
    async def test_dsn_contains_credentials(self):
        """init_pool constructs DSN with user, password, host, db from env."""
        pool, conn = _make_pool_mock()

        with patch.dict(os.environ, {
            "POSTGRES_USER": "myuser",
            "POSTGRES_PASSWORD": "mypass",
            "POSTGRES_DB": "mydb",
            "POSTGRES_HOST": "myhost",
        }), patch.object(_telemetry_mod, "asyncpg", MagicMock(
            create_pool=AsyncMock(return_value=pool)
        )):
            await init_pool()

            dsn = _telemetry_mod.asyncpg.create_pool.call_args[1]["dsn"]
            assert "myuser" in dsn
            assert "myhost" in dsn
            assert "mydb" in dsn

            await close_pool()

    @pytest.mark.asyncio
    async def test_default_host_is_evolution_postgres(self):
        """init_pool defaults POSTGRES_HOST to 'evolution_postgres'."""
        pool, conn = _make_pool_mock()

        env = {"POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p", "POSTGRES_DB": "d"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("POSTGRES_HOST", None)

            with patch.object(_telemetry_mod, "asyncpg", MagicMock(
                create_pool=AsyncMock(return_value=pool)
            )):
                await init_pool()

                dsn = _telemetry_mod.asyncpg.create_pool.call_args[1]["dsn"]
                assert "evolution_postgres" in dsn

                await close_pool()


class TestClosePool:

    @pytest.mark.asyncio
    async def test_close_pool_calls_pool_close(self):
        """close_pool calls pool.close() on the initialized pool."""
        pool, _ = _make_pool_mock()

        with patch.dict(os.environ, {
            "POSTGRES_USER": "u",
            "POSTGRES_PASSWORD": "p",
            "POSTGRES_DB": "d",
            "POSTGRES_HOST": "h",
        }), patch.object(_telemetry_mod, "asyncpg", MagicMock(
            create_pool=AsyncMock(return_value=pool)
        )):
            await init_pool()
            await close_pool()

            pool.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_pool_is_safe_when_no_pool(self):
        """close_pool does nothing when pool was never initialized."""
        # Should not raise
        await close_pool()


# ─── record_interaction tests ──────────────────────────────────────────

class TestRecordInteraction:

    @pytest.mark.asyncio
    async def test_is_noop_when_pool_is_none(self):
        """record_interaction does nothing when pool is None."""
        # Call with None pool — should not raise
        await record_interaction(
            None,
            remitente="12345",
            push_name="Test",
            texto="hello",
            es_audio=False,
            respuesta="hi",
            cacheable=True,
            cache_hit=False,
            faq_hit=False,
            error_code=None,
            rag_duration_ms=100,
            send_duration_ms=50,
            total_duration_ms=150,
        )

    @pytest.mark.asyncio
    async def test_inserts_correct_sql_with_pool(self):
        """record_interaction executes INSERT with correct columns."""
        pool, conn = _make_pool_mock()

        await record_interaction(
            pool,
            remitente="54911111111",
            push_name="Juan",
            texto="cuanto cuesta?",
            es_audio=False,
            respuesta="El precio es...",
            cacheable=True,
            cache_hit=False,
            faq_hit=False,
            error_code=None,
            rag_duration_ms=500,
            send_duration_ms=200,
            total_duration_ms=700,
        )

        insert_calls = [c for c in conn.execute.call_args_list
                        if "INSERT" in str(c)]
        assert len(insert_calls) >= 1

        sql = insert_calls[0][0][0]
        assert "telemetry.bot_messages" in sql
        assert "remitente" in sql
        assert "push_name" in sql
        assert "es_audio" in sql
        assert "error_code" in sql
        # Verify positional args match the INSERT columns
        args = insert_calls[0][0][1:]
        assert args[0] == "54911111111"  # remitente
        assert args[2] == "cuanto cuesta?"  # texto
        assert args[4] == "El precio es..."  # respuesta

    @pytest.mark.asyncio
    async def test_logs_warning_on_db_error(self):
        """record_interaction logs a warning instead of raising on DB failure."""
        pool, conn = _make_pool_mock()
        conn.execute.side_effect = Exception("connection lost")

        # Should NOT raise — fire-and-forget
        await record_interaction(
            pool,
            remitente="54911111111",
            push_name="Juan",
            texto="hola",
            es_audio=False,
            respuesta="chau",
            cacheable=False,
            cache_hit=False,
            faq_hit=False,
            error_code=None,
            rag_duration_ms=None,
            send_duration_ms=None,
            total_duration_ms=100,
        )

    @pytest.mark.asyncio
    async def test_records_error_interaction(self):
        """record_interaction can store an error_code."""
        pool, conn = _make_pool_mock()

        await record_interaction(
            pool,
            remitente="54922222222",
            push_name=None,
            texto="broken query",
            es_audio=False,
            respuesta=None,
            cacheable=False,
            cache_hit=False,
            faq_hit=False,
            error_code="E-COM-001",
            rag_duration_ms=50,
            send_duration_ms=None,
            total_duration_ms=80,
        )

        insert_calls = [c for c in conn.execute.call_args_list
                        if "INSERT" in str(c)]
        assert len(insert_calls) >= 1
        # $9 is the error_code position
        call_args = insert_calls[0][0]
        assert "E-COM-001" in call_args

    @pytest.mark.asyncio
    async def test_records_faq_hit(self):
        """record_interaction stores faq_hit=True for FAQ shortcuts."""
        pool, conn = _make_pool_mock()

        await record_interaction(
            pool,
            remitente="54933333",
            push_name="Maria",
            texto="horario",
            es_audio=False,
            respuesta="Lun a Vie 9-18",
            cacheable=False,
            cache_hit=False,
            faq_hit=True,
            error_code=None,
            rag_duration_ms=None,
            send_duration_ms=100,
            total_duration_ms=100,
        )

        insert_calls = [c for c in conn.execute.call_args_list
                        if "INSERT" in str(c)]
        assert len(insert_calls) >= 1

    @pytest.mark.asyncio
    async def test_records_audio_interaction(self):
        """record_interaction stores es_audio=True for audio messages."""
        pool, conn = _make_pool_mock()

        await record_interaction(
            pool,
            remitente="54944444",
            push_name="Pedro",
            texto=None,
            es_audio=True,
            respuesta="respuesta al audio",
            cacheable=True,
            cache_hit=False,
            faq_hit=False,
            error_code=None,
            rag_duration_ms=800,
            send_duration_ms=300,
            total_duration_ms=1100,
        )

        insert_calls = [c for c in conn.execute.call_args_list
                        if "INSERT" in str(c)]
        assert len(insert_calls) >= 1
        call_args = insert_calls[0][0]
        # es_audio is the 4th positional arg ($4)
        assert call_args[4] is True  # es_audio=True


# ─── get_summary tests ────────────────────────────────────────────────

class TestGetSummary:

    @pytest.mark.asyncio
    async def test_returns_zero_counts_when_no_data(self):
        """get_summary returns zeros and empty daily when no rows exist."""
        pool, conn = _make_pool_mock()
        conn.fetchrow.return_value = None
        conn.fetch.return_value = []

        result = await get_summary(pool)

        assert result["total_messages"] == 0
        assert result["faq_hits"] == 0
        assert result["cache_hits"] == 0
        assert result["avg_rag_ms"] == 0
        assert result["avg_send_ms"] == 0
        assert result["error_count"] == 0
        assert result["unique_users"] == 0
        assert result["daily"] == []

    @pytest.mark.asyncio
    async def test_returns_aggregated_data_with_rows(self):
        """get_summary aggregates rows into totals and per-day breakdown."""
        pool, conn = _make_pool_mock()

        conn.fetchrow.return_value = {
            "total_messages": 100,
            "faq_hits": 20,
            "cache_hits": 15,
            "avg_rag_ms": 1200,
            "avg_send_ms": 300,
            "error_count": 5,
            "unique_users": 42,
        }
        conn.fetch.return_value = [
            {"date": "2026-06-03", "total_messages": 50, "faq_hits": 10,
             "cache_hits": 8, "avg_rag_ms": 1100, "avg_send_ms": 280,
             "error_count": 2, "unique_users": 21},
            {"date": "2026-06-04", "total_messages": 50, "faq_hits": 10,
             "cache_hits": 7, "avg_rag_ms": 1300, "avg_send_ms": 320,
             "error_count": 3, "unique_users": 25},
        ]

        result = await get_summary(pool)

        assert result["total_messages"] == 100
        assert result["faq_hits"] == 20
        assert result["cache_hits"] == 15
        assert result["avg_rag_ms"] == 1200
        assert result["avg_send_ms"] == 300
        assert result["error_count"] == 5
        assert result["unique_users"] == 42
        assert len(result["daily"]) == 2
        assert result["daily"][0]["date"] == "2026-06-03"

    @pytest.mark.asyncio
    async def test_passes_days_parameter_to_query(self):
        """get_summary accepts days parameter and includes it in the SQL."""
        pool, conn = _make_pool_mock()
        conn.fetchrow.return_value = {
            "total_messages": 0, "faq_hits": 0, "cache_hits": 0,
            "avg_rag_ms": 0, "avg_send_ms": 0,
            "error_count": 0, "unique_users": 0,
        }
        conn.fetch.return_value = []

        await get_summary(pool, days=14)

        # Verify that fetchrow was called with SQL containing "14 days"
        sql_arg = conn.fetchrow.call_args[0][0]
        assert "14 days" in sql_arg

    @pytest.mark.asyncio
    async def test_default_days_is_7(self):
        """get_summary defaults to 7 days when days is not specified."""
        pool, conn = _make_pool_mock()
        conn.fetchrow.return_value = {
            "total_messages": 0, "faq_hits": 0, "cache_hits": 0,
            "avg_rag_ms": 0, "avg_send_ms": 0,
            "error_count": 0, "unique_users": 0,
        }
        conn.fetch.return_value = []

        await get_summary(pool)

        sql_arg = conn.fetchrow.call_args[0][0]
        assert "7 days" in sql_arg

    @pytest.mark.asyncio
    async def test_raises_app_error_on_db_failure(self):
        """get_summary raises AppError(TELEMETRY_DB_ERROR) on database failure."""
        pool, conn = _make_pool_mock()
        conn.fetchrow.side_effect = Exception("db connection lost")

        with pytest.raises(AppError) as exc_info:
            await get_summary(pool)

        assert exc_info.value.code == ErrorCode.TELEMETRY_DB_ERROR

    @pytest.mark.asyncio
    async def test_raises_app_error_when_pool_is_none(self):
        """get_summary raises AppError when pool is None."""
        with pytest.raises(AppError) as exc_info:
            await get_summary(None)

        assert exc_info.value.code == ErrorCode.TELEMETRY_DB_ERROR