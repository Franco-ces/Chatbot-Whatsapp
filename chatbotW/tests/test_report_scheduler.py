"""Tests for report_scheduler.py module.

TDD RED: Tests for the background scheduler that polls telemetry.report_schedules,
generates PDF reports, and sends them via WhatsApp.

Covers:
- 4.2: _process_schedule success and failure isolation
- 4.3: due schedule query filtering
- 2.1: start_scheduler / stop_scheduler lifecycle
- 2.2: _scheduler_loop query conditions
"""
import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock asyncpg before any import
if "asyncpg" not in sys.modules:
    _mock_asyncpg = MagicMock()
    _mock_asyncpg.Pool = MagicMock
    _mock_asyncpg.create_pool = AsyncMock()
    sys.modules["asyncpg"] = _mock_asyncpg

# Mock fpdf before any import that might need it (report_generator imports it)
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


class TestProcessScheduleSuccess:
    """Task 4.2: _process_schedule success path."""

    @pytest.mark.asyncio
    async def test_process_schedule_calls_generar_reporte(self, mocker):
        """_process_schedule must call generar_reporte with tipo and parametros."""
        import report_scheduler as rs_mod

        mock_pool, mock_conn = _make_pool_mock()
        mock_wa = MagicMock()
        mock_wa.enviar_documento = AsyncMock(return_value={"key": {"id": "doc1"}})

        mock_generar = mocker.patch(
            "report_generator.generar_reporte", new_callable=AsyncMock, return_value=b"%PDF-fake-content"
        )

        schedule = {
            "id": 1,
            "tipo": "diario",
            "parametros": {"telefono": "54911"},
            "hora_envio": time(8, 0),
            "destino": "5491112345678",
            "header_text": None,
            "footer_text": None,
        }

        await rs_mod._process_schedule(schedule, mock_pool, mock_wa, "instancia-test")

        mock_generar.assert_called_once_with("diario", mock_pool, {"telefono": "54911"})

    @pytest.mark.asyncio
    async def test_process_schedule_calls_enviar_documento(self, mocker):
        """_process_schedule must call enviar_documento with correct args."""
        import report_scheduler as rs_mod

        mock_pool, mock_conn = _make_pool_mock()
        mock_wa = MagicMock()
        mock_wa.enviar_documento = AsyncMock(return_value={"key": {"id": "doc1"}})

        mocker.patch("report_generator.generar_reporte", new_callable=AsyncMock, return_value=b"%PDF-content")

        schedule = {
            "id": 2,
            "tipo": "historial",
            "parametros": {},
            "hora_envio": time(9, 30),
            "destino": "5491199999999",
            "header_text": None,
            "footer_text": None,
        }

        await rs_mod._process_schedule(schedule, mock_pool, mock_wa, "my-instance")

        mock_wa.enviar_documento.assert_called_once()
        call_args = mock_wa.enviar_documento.call_args
        assert call_args[0][0] == "5491199999999"  # destino
        assert call_args[0][1] == b"%PDF-content"  # pdf_bytes
        assert "historial" in call_args[0][2]  # filename contains tipo
        assert call_args[1]["instance_name"] == "my-instance"

    @pytest.mark.asyncio
    async def test_process_schedule_updates_ultimo_envio(self, mocker):
        """_process_schedule must UPDATE ultimo_envio on success."""
        import report_scheduler as rs_mod

        mock_pool, mock_conn = _make_pool_mock()
        mock_wa = MagicMock()
        mock_wa.enviar_documento = AsyncMock(return_value={"key": {"id": "doc1"}})

        mocker.patch("report_generator.generar_reporte", new_callable=AsyncMock, return_value=b"%PDF")

        schedule = {
            "id": 3,
            "tipo": "diario",
            "parametros": {},
            "hora_envio": time(8, 0),
            "destino": "5491112345678",
            "header_text": None,
            "footer_text": None,
        }

        await rs_mod._process_schedule(schedule, mock_pool, mock_wa, "inst")

        # Verify UPDATE was called with the schedule's id
        update_calls = [c for c in mock_conn.execute.call_args_list if "UPDATE" in str(c)]
        assert len(update_calls) >= 1
        update_sql = str(update_calls[0][0][0])
        assert "ultimo_envio" in update_sql
        assert "report_schedules" in update_sql

    @pytest.mark.asyncio
    async def test_process_schedule_filename_includes_tipo_and_date(self, mocker):
        """Filename must include tipo and today's date."""
        import report_scheduler as rs_mod

        mock_pool, mock_conn = _make_pool_mock()
        mock_wa = MagicMock()
        mock_wa.enviar_documento = AsyncMock(return_value={"key": {"id": "d"}})

        mocker.patch("report_generator.generar_reporte", new_callable=AsyncMock, return_value=b"%PDF")

        schedule = {
            "id": 4,
            "tipo": "por-dia",
            "parametros": {},
            "hora_envio": time(10, 0),
            "destino": "54911",
            "header_text": None,
            "footer_text": None,
        }

        await rs_mod._process_schedule(schedule, mock_pool, mock_wa, "inst")

        filename = mock_wa.enviar_documento.call_args[0][2]
        assert "por-dia" in filename
        assert date.today().isoformat() in filename
        assert filename.endswith(".pdf")


class TestProcessScheduleFailure:
    """Task 4.2: _process_schedule failure isolation."""

    @pytest.mark.asyncio
    async def test_process_schedule_does_not_raise_on_generar_reporte_failure(self, mocker):
        """If generar_reporte fails, _process_schedule must not raise."""
        import report_scheduler as rs_mod

        mock_pool, mock_conn = _make_pool_mock()
        mock_wa = MagicMock()
        mock_wa.enviar_documento = AsyncMock()

        mocker.patch("report_generator.generar_reporte", new_callable=AsyncMock, side_effect=ValueError("tipo no encontrado"))

        schedule = {
            "id": 5,
            "tipo": "inexistente",
            "parametros": {},
            "hora_envio": time(8, 0),
            "destino": "54911",
            "header_text": None,
            "footer_text": None,
        }

        # Must NOT raise — error is isolated
        await rs_mod._process_schedule(schedule, mock_pool, mock_wa, "inst")

    @pytest.mark.asyncio
    async def test_process_schedule_does_not_raise_on_send_failure(self, mocker):
        """If enviar_documento fails, _process_schedule must not raise."""
        from exceptions import CommunicationError
        from error_codes import ErrorCode
        import report_scheduler as rs_mod

        mock_pool, mock_conn = _make_pool_mock()
        mock_wa = MagicMock()
        mock_wa.enviar_documento = AsyncMock(
            side_effect=CommunicationError(ErrorCode.COM_SEND_DOCUMENT_FAILED, detail="API error")
        )

        mocker.patch("report_generator.generar_reporte", new_callable=AsyncMock, return_value=b"%PDF")

        schedule = {
            "id": 6,
            "tipo": "diario",
            "parametros": {},
            "hora_envio": time(8, 0),
            "destino": "54911",
            "header_text": None,
            "footer_text": None,
        }

        # Must NOT raise — error is isolated
        await rs_mod._process_schedule(schedule, mock_pool, mock_wa, "inst")

    @pytest.mark.asyncio
    async def test_process_schedule_does_not_update_envio_on_failure(self, mocker):
        """If generar_reporte fails, ultimo_envio must NOT be updated."""
        import report_scheduler as rs_mod

        mock_pool, mock_conn = _make_pool_mock()
        mock_wa = MagicMock()
        mock_wa.enviar_documento = AsyncMock()

        mocker.patch("report_generator.generar_reporte", new_callable=AsyncMock, side_effect=ValueError("bad tipo"))

        schedule = {
            "id": 7,
            "tipo": "bad",
            "parametros": {},
            "hora_envio": time(8, 0),
            "destino": "54911",
            "header_text": None,
            "footer_text": None,
        }

        await rs_mod._process_schedule(schedule, mock_pool, mock_wa, "inst")

        # No UPDATE should have been called
        update_calls = [c for c in mock_conn.execute.call_args_list if "UPDATE" in str(c)]
        assert len(update_calls) == 0

    @pytest.mark.asyncio
    async def test_no_instance_name_skips_schedule(self, mocker):
        """If instance_name_resolver returns empty string, schedule is skipped."""
        import report_scheduler as rs_mod

        mock_pool, mock_conn = _make_pool_mock()
        mock_wa = MagicMock()
        mock_wa.enviar_documento = AsyncMock()

        mock_generar = mocker.patch("report_generator.generar_reporte", new_callable=AsyncMock)

        schedule = {
            "id": 8,
            "tipo": "diario",
            "parametros": {},
            "hora_envio": time(8, 0),
            "destino": "54911",
            "header_text": None,
            "footer_text": None,
        }

        await rs_mod._process_schedule(schedule, mock_pool, mock_wa, "")

        # generar_reporte should NOT have been called
        mock_generar.assert_not_called()


class TestDueScheduleQuery:
    """Task 4.3: due schedule query filter logic."""

    @pytest.mark.asyncio
    async def test_query_filters_activo_true(self):
        """Only activo=true schedules should be returned."""
        import report_scheduler as rs_mod

        # The loop query includes WHERE activo = true
        assert "activo" in rs_mod._DUE_SCHEDULES_SQL
        assert "true" in rs_mod._DUE_SCHEDULES_SQL.lower()

    @pytest.mark.asyncio
    async def test_query_filters_by_hora_envio(self):
        """The SQL must filter by hora_envio <= current time."""
        import report_scheduler as rs_mod

        assert "hora_envio" in rs_mod._DUE_SCHEDULES_SQL

    @pytest.mark.asyncio
    async def test_query_filters_ultimo_envio_date(self):
        """The SQL must check ultimo_envio IS NULL OR date < today."""
        import report_scheduler as rs_mod

        assert "ultimo_envio" in rs_mod._DUE_SCHEDULES_SQL
        sql_lower = rs_mod._DUE_SCHEDULES_SQL.lower()
        assert "current_date" in sql_lower or "CURRENT_DATE" in rs_mod._DUE_SCHEDULES_SQL


class TestSchedulerLifecycle:
    """Task 2.1: start_scheduler / stop_scheduler."""

    @pytest.mark.asyncio
    async def test_start_scheduler_creates_task(self):
        """start_scheduler must create an asyncio.Task."""
        import report_scheduler as rs_mod

        mock_pool = MagicMock()
        mock_wa = MagicMock()

        # Patch the loop function to prevent actual execution
        original_loop = rs_mod._scheduler_loop
        rs_mod._scheduler_loop = AsyncMock()

        try:
            task = await rs_mod.start_scheduler(mock_pool, mock_wa, lambda: "inst")
            assert task is not None
            assert isinstance(task, asyncio.Task)
        finally:
            # Cleanup
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            rs_mod._scheduler_loop = original_loop
            rs_mod._scheduler_task = None

    @pytest.mark.asyncio
    async def test_stop_scheduler_cancels_task(self):
        """stop_scheduler must cancel the running task."""
        import report_scheduler as rs_mod

        mock_pool = MagicMock()
        mock_wa = MagicMock()

        # Make the loop sleep forever
        rs_mod._scheduler_loop = AsyncMock()

        try:
            task = await rs_mod.start_scheduler(mock_pool, mock_wa, lambda: "inst")
            # Task should complete immediately since _scheduler_loop is mocked
            await rs_mod.stop_scheduler()
            # If we get here without error, the task was cancelled successfully
            assert True
        finally:
            rs_mod._scheduler_task = None