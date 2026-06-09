"""Tests for report_generator module and report API endpoints.

Covers:
- Registry: 4 subclasses auto-registered with correct IDs (4.2)
- Param definitions: required/optional match spec per report type (4.3)
- SQL strings: expected columns present (4.4)
- FPDF output: generar() returns %PDF-starting bytes (4.5)
- Row cap: mock 5001 rows → PDF includes cap notice (4.6)
- Validation: missing param, invalid date, desde > hasta, unknown tipo (4.7)
- API: list tipos, generate valid, generate invalid (4.8)
"""
import sys
from contextlib import asynccontextmanager
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Mock asyncpg before any import that touches it
if "asyncpg" not in sys.modules:
    _mock_asyncpg = MagicMock()
    _mock_asyncpg.Pool = MagicMock
    _mock_asyncpg.create_pool = AsyncMock()
    sys.modules["asyncpg"] = _mock_asyncpg


# ─── Helpers ───────────────────────────────────────────────────────────

def make_mock_pool(fetch_result=None, fetchrow_result=None):
    """Create a mock asyncpg pool with async context manager support.

    Usage in async tests:
        mock_pool, mock_conn = make_mock_pool(fetch_result=[...])
        result = await some_report.generar(mock_pool, params)
    """
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=fetch_result or [])
    mock_conn.fetchrow = AsyncMock(return_value=fetchrow_result)

    @asynccontextmanager
    async def mock_acquire(*args, **kwargs):
        yield mock_conn

    mock_pool = MagicMock()
    # pool.acquire() returns an async context manager
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


# ─── Registry Tests (4.2) ───────────────────────────────────────────────

class TestRegistry:
    """Task 4.2: Verify 4 report types are auto-registered with correct IDs."""

    def test_four_report_types_registered(self):
        """When module loads, 4 report types exist in _report_types."""
        from report_generator import _report_types

        assert set(_report_types.keys()) == {"diario", "historial", "por-dia", "completo"}

    def test_diario_class_is_registered(self):
        from report_generator import _report_types, ReporteDiario
        assert _report_types["diario"] is ReporteDiario

    def test_historial_class_is_registered(self):
        from report_generator import _report_types, ReporteHistorialPorNumero
        assert _report_types["historial"] is ReporteHistorialPorNumero

    def test_por_dia_class_is_registered(self):
        from report_generator import _report_types, ReporteMensajesPorDia
        assert _report_types["por-dia"] is ReporteMensajesPorDia

    def test_completo_class_is_registered(self):
        from report_generator import _report_types, ReporteHistorialCompleto
        assert _report_types["completo"] is ReporteHistorialCompleto


# ─── Param Definition Tests (4.3) ───────────────────────────────────────

class TestParamDefinitions:
    """Task 4.3: Required/optional params match spec per report type."""

    def test_diario_has_no_params(self):
        from report_generator import _report_types
        cls = _report_types["diario"]
        assert cls.parametros == []

    def test_historial_has_telefono_desde_hasta(self):
        from report_generator import _report_types
        cls = _report_types["historial"]
        keys = [p.key for p in cls.parametros]
        assert "telefono" in keys
        assert "desde" in keys
        assert "hasta" in keys

    def test_historial_telefono_is_required(self):
        from report_generator import _report_types
        cls = _report_types["historial"]
        tel = next(p for p in cls.parametros if p.key == "telefono")
        assert tel.requerido is True

    def test_historial_desde_is_optional(self):
        from report_generator import _report_types
        cls = _report_types["historial"]
        desde = next(p for p in cls.parametros if p.key == "desde")
        assert desde.requerido is False

    def test_historial_hasta_is_optional(self):
        from report_generator import _report_types
        cls = _report_types["historial"]
        hasta = next(p for p in cls.parametros if p.key == "hasta")
        assert hasta.requerido is False

    def test_por_dia_has_desde_hasta_both_required(self):
        from report_generator import _report_types
        cls = _report_types["por-dia"]
        keys = [p.key for p in cls.parametros]
        assert "desde" in keys
        assert "hasta" in keys
        desde = next(p for p in cls.parametros if p.key == "desde")
        hasta = next(p for p in cls.parametros if p.key == "hasta")
        assert desde.requerido is True
        assert hasta.requerido is True

    def test_completo_has_telefono_required(self):
        from report_generator import _report_types
        cls = _report_types["completo"]
        keys = [p.key for p in cls.parametros]
        assert "telefono" in keys
        tel = next(p for p in cls.parametros if p.key == "telefono")
        assert tel.requerido is True

    def test_completo_has_desde_hasta_optional(self):
        from report_generator import _report_types
        cls = _report_types["completo"]
        keys = [p.key for p in cls.parametros]
        assert "desde" in keys
        assert "hasta" in keys
        desde = next(p for p in cls.parametros if p.key == "desde")
        hasta = next(p for p in cls.parametros if p.key == "hasta")
        assert desde.requerido is False
        assert hasta.requerido is False


# ─── SQL String Tests (4.4) ──────────────────────────────────────────────

class TestSQLStrings:
    """Task 4.4: Verify expected columns/table in SQL per report (no DB)."""

    def test_diario_sql_reads_from_telemetry_bot_messages(self):
        from report_generator import ReporteDiario
        assert "telemetry.bot_messages" in ReporteDiario._sql

    def test_diario_sql_selects_remitente(self):
        from report_generator import ReporteDiario
        assert "remitente" in ReporteDiario._sql

    def test_diario_sql_filters_yesterday(self):
        from report_generator import ReporteDiario
        assert "CURRENT_DATE - 1" in ReporteDiario._sql

    def test_historial_sql_filters_by_phone(self):
        from report_generator import ReporteHistorialPorNumero
        assert "remitente" in ReporteHistorialPorNumero._sql
        assert "$1" in ReporteHistorialPorNumero._sql

    def test_por_dia_sql_groups_by_date(self):
        from report_generator import ReporteMensajesPorDia
        assert "GROUP BY" in ReporteMensajesPorDia._sql.upper()
        assert "created_at" in ReporteMensajesPorDia._sql

    def test_completo_sql_has_row_limit(self):
        from report_generator import ReporteHistorialCompleto
        assert "LIMIT" in ReporteHistorialCompleto._sql.upper()


# ─── FPDF Output Tests (4.5) ────────────────────────────────────────────

class TestBuildPDF:
    """Task 4.5: generar() returns %PDF-starting bytes."""

    def test_pdf_starts_with_pdf_header(self):
        from report_generator import _build_pdf
        result = _build_pdf("Test Report", ["Col1", "Col2"], [["A", "B"]])
        assert result.startswith(b"%PDF")

    def test_pdf_with_empty_rows(self):
        from report_generator import _build_pdf
        result = _build_pdf("Empty Report", ["Col1"], [])
        assert result.startswith(b"%PDF")

    def test_pdf_contains_title(self):
        from report_generator import _build_pdf
        result = _build_pdf("My Specific Title", ["Col1"], [["A"]])
        # FPDF2 embeds text that can be found as bytes in the PDF
        assert b"My Specific Title" in result

    def test_pdf_contains_column_headers(self):
        from report_generator import _build_pdf
        result = _build_pdf("Report", ["Hora", "Estado"], [["10:30", "OK"]])
        assert b"Hora" in result

    def test_pdf_with_header_text(self):
        from report_generator import _build_pdf
        result = _build_pdf("Report", ["C1"], [["A"]], header_text="Desde: 2026-01-01")
        assert b"Desde: 2026-01-01" in result

    def test_pdf_with_footer_text(self):
        from report_generator import _build_pdf
        result = _build_pdf("Report", ["C1"], [["A"]], footer_text="Total: 5")
        # footer_text appears in the rendered PDF content
        assert b"Total: 5" in result


# ─── Report Generation Tests (4.5 continued) ─────────────────────────────

class TestReporteDiarioGeneration:
    """Task 4.5: Each report type returns PDF bytes from generar()."""

    @pytest.mark.asyncio
    async def test_diario_returns_pdf_bytes_with_data(self):
        from report_generator import _report_types
        cls = _report_types["diario"]
        report = cls()

        mock_rows = [
            {
                "hora": "10:30",
                "usuario": "+549111234567",
                "estado": "exito",
                "latencia_ms": 234,
                "mensaje_preview": "Hola",
            }
        ]
        mock_pool, _ = make_mock_pool(fetch_result=mock_rows)
        result = await report.generar(mock_pool, {})
        assert result.startswith(b"%PDF")

    @pytest.mark.asyncio
    async def test_diario_returns_pdf_bytes_empty(self):
        """Triangulation: empty result set still produces valid PDF."""
        from report_generator import _report_types
        cls = _report_types["diario"]
        report = cls()

        mock_pool, _ = make_mock_pool(fetch_result=[])
        result = await report.generar(mock_pool, {})
        assert result.startswith(b"%PDF")


class TestReporteHistorialGeneration:
    @pytest.mark.asyncio
    async def test_historial_returns_pdf_bytes(self):
        from report_generator import _report_types
        cls = _report_types["historial"]
        report = cls()

        mock_rows = [
            {
                "fecha_hora": "01/06/2026 10:30",
                "direccion": "inbound",
                "estado": "exito",
                "contenido_preview": "Hola",
                "latencia_ms": 120,
            }
        ]
        mock_pool, _ = make_mock_pool(fetch_result=mock_rows)
        result = await report.generar(mock_pool, {"telefono": "5491112345678", "desde": "2026-01-01", "hasta": "2026-01-31"})
        assert result.startswith(b"%PDF")


class TestReporteMensajesPorDiaGeneration:
    @pytest.mark.asyncio
    async def test_por_dia_returns_pdf_bytes(self):
        from report_generator import _report_types
        cls = _report_types["por-dia"]
        report = cls()

        mock_rows = [
            {
                "fecha": date(2026, 6, 1),
                "total_mensajes": 50,
                "exitos": 45,
                "errores": 2,
                "cache_hits": 3,
                "faq_hits": 0,
                "latencia_promedio_ms": 120,
            }
        ]
        mock_pool, _ = make_mock_pool(fetch_result=mock_rows)
        result = await report.generar(mock_pool, {"desde": "2026-06-01", "hasta": "2026-06-30"})
        assert result.startswith(b"%PDF")


class TestReporteCompletoGeneration:
    @pytest.mark.asyncio
    async def test_completo_returns_pdf_bytes(self):
        from report_generator import _report_types
        cls = _report_types["completo"]
        report = cls()

        mock_rows = [
            {
                "fecha_hora": "01/06/2026 10:30",
                "direccion": "inbound",
                "estado": "OK",
                "contenido": "Mensaje de prueba",
                "latencia_ms": 100,
                "push_name": "Juan",
                "error_code": None,
            }
        ]
        mock_pool, _ = make_mock_pool(fetch_result=mock_rows)
        result = await report.generar(mock_pool, {"telefono": "5491112345678"})
        assert result.startswith(b"%PDF")


# ─── Row Cap Tests (4.6) ─────────────────────────────────────────────────

class TestRowCap:
    """Task 4.6: Mock 5001 rows → verify PDF includes cap notice."""

    @pytest.mark.asyncio
    async def test_completo_caps_at_5000_rows(self):
        """ReporteHistorialCompleto must show 'Mostrando primeros 5000' when exceeding cap."""
        from report_generator import _report_types
        cls = _report_types["completo"]
        report = cls()

        # 5001 rows to trigger cap (query returns 5001 to signal overflow)
        mock_rows = [
            {"fecha_hora": "01/06/2026 10:30", "direccion": "inbound",
             "estado": "OK", "contenido": f"Msg {i}", "latencia_ms": 100,
             "push_name": None, "error_code": None}
            for i in range(5001)
        ]
        mock_pool, _ = make_mock_pool(fetch_result=mock_rows)
        result = await report.generar(mock_pool, {"telefono": "5491112345678"})
        assert result.startswith(b"%PDF")
        # The PDF must contain the cap notice text
        assert b"Mostrando primeros 5000" in result

    @pytest.mark.asyncio
    async def test_completo_no_cap_notice_under_5000(self):
        """Triangulation: under-5000 rows must NOT show cap notice."""
        from report_generator import _report_types
        cls = _report_types["completo"]
        report = cls()

        mock_rows = [
            {"fecha_hora": "01/06/2026 10:30", "direccion": "inbound",
             "estado": "OK", "contenido": "Msg", "latencia_ms": 100,
             "push_name": None, "error_code": None}
            for i in range(10)
        ]
        mock_pool, _ = make_mock_pool(fetch_result=mock_rows)
        result = await report.generar(mock_pool, {"telefono": "5491112345678"})
        assert b"Mostrando primeros 5000" not in result


# ─── Validation Tests (4.7) ──────────────────────────────────────────────

class TestValidation:
    """Task 4.7: Missing param, invalid date, desde > hasta, unknown tipo."""

    def test_missing_required_param_raises_value_error(self):
        from report_generator import _validate_parametros, _report_types
        cls = _report_types["historial"]
        with pytest.raises(ValueError, match="Parámetro requerido: telefono"):
            _validate_parametros(cls, {})

    def test_missing_required_desde_for_por_dia(self):
        from report_generator import _validate_parametros, _report_types
        cls = _report_types["por-dia"]
        with pytest.raises(ValueError, match="Parámetro requerido: desde"):
            _validate_parametros(cls, {"hasta": "2026-01-31"})

    def test_invalid_date_format_raises_value_error(self):
        from report_generator import _validate_parametros, _report_types
        cls = _report_types["por-dia"]
        with pytest.raises(ValueError, match="Formato de fecha inválido"):
            _validate_parametros(cls, {"desde": "not-a-date", "hasta": "2026-01-31"})

    def test_desde_after_hasta_raises_value_error(self):
        from report_generator import _validate_parametros, _report_types
        cls = _report_types["por-dia"]
        with pytest.raises(ValueError, match="posterior"):
            _validate_parametros(cls, {"desde": "2026-02-01", "hasta": "2026-01-01"})

    def test_range_exceeds_90_days_por_dia(self):
        from report_generator import _validate_parametros, _report_types
        cls = _report_types["por-dia"]
        with pytest.raises(ValueError, match="90 días"):
            _validate_parametros(cls, {"desde": "2026-01-01", "hasta": "2026-04-02"})

    def test_valid_params_pass_validation(self):
        from report_generator import _validate_parametros, _report_types
        cls = _report_types["historial"]
        # Should not raise
        _validate_parametros(cls, {"telefono": "5491112345678", "desde": "2026-01-01", "hasta": "2026-01-31"})

    def test_invalid_phone_raises_value_error(self):
        from report_generator import _validate_parametros, _report_types
        cls = _report_types["historial"]
        with pytest.raises(ValueError, match="teléfono inválido"):
            _validate_parametros(cls, {"telefono": "abc"})

    def test_diario_no_required_params_passes(self):
        from report_generator import _validate_parametros, _report_types
        cls = _report_types["diario"]
        # No params needed for diario
        _validate_parametros(cls, {})


# ─── generar_reporte Function Tests ──────────────────────────────────────

class TestGenerarReporte:
    """Test the public generar_reporte function."""

    @pytest.mark.asyncio
    async def test_unknown_tipo_raises_value_error(self):
        from report_generator import generar_reporte
        mock_pool, _ = make_mock_pool()
        with pytest.raises(ValueError, match="no encontrado"):
            await generar_reporte("nonexistent", mock_pool, {})

    @pytest.mark.asyncio
    async def test_diario_returns_pdf(self):
        from report_generator import generar_reporte
        mock_rows = [
            {"hora": "10:30", "usuario": "+549111234567", "estado": "exito",
             "latencia_ms": 234, "mensaje_preview": "Hola"}
        ]
        mock_pool, _ = make_mock_pool(fetch_result=mock_rows)
        result = await generar_reporte("diario", mock_pool, {})
        assert result.startswith(b"%PDF")

    @pytest.mark.asyncio
    async def test_generar_validates_params_before_query(self):
        """Validation must happen before the DB query."""
        from report_generator import generar_reporte
        mock_pool, mock_conn = make_mock_pool()
        with pytest.raises(ValueError):
            await generar_reporte("historial", mock_pool, {})
        # DB query should never have been called
        mock_conn.fetch.assert_not_called()


# ─── Listar Tipos Tests ──────────────────────────────────────────────────

class TestListarTipos:
    def test_returns_list_of_four_tipo_dicts(self):
        from report_generator import listar_tipos
        result = listar_tipos()
        assert isinstance(result, list)
        assert len(result) == 4

    def test_each_tipo_has_required_keys(self):
        from report_generator import listar_tipos
        result = listar_tipos()
        for item in result:
            assert "id" in item
            assert "nombre" in item
            assert "descripcion" in item
            assert "parametros" in item

    def test_parametros_have_correct_structure(self):
        from report_generator import listar_tipos
        result = listar_tipos()
        historial = next(r for r in result if r["id"] == "historial")
        assert len(historial["parametros"]) > 0
        param = historial["parametros"][0]
        assert "key" in param
        assert "label" in param
        assert "tipo" in param
        assert "requerido" in param

    def test_diario_tipo_has_empty_parametros(self):
        from report_generator import listar_tipos
        result = listar_tipos()
        diario = next(r for r in result if r["id"] == "diario")
        assert diario["parametros"] == []


# ─── API Endpoint Tests (4.8) ─────────────────────────────────────────────

class TestReportesAPI:
    """Task 4.8: API endpoint tests with httpx.AsyncClient."""

    @pytest.mark.asyncio
    async def test_list_tipos_returns_200(self):
        import interface
        transport = httpx.ASGITransport(app=interface.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Reportes endpoints are in EXCLUDED_PATHS (public)
            response = await client.get("/api/reportes/tipos")

        assert response.status_code == 200
        body = response.json()
        assert "tipos" in body
        assert len(body["tipos"]) == 4

    @pytest.mark.asyncio
    async def test_generate_diario_returns_pdf(self):
        """Authenticated request to generate diario returns PDF."""
        import interface
        import report_generator as rg_mod
        from report_generator import ReporteDiario

        mock_rows = [
            {"hora": "10:30", "usuario": "+549111234567", "estado": "exito",
             "latencia_ms": 234, "mensaje_preview": "Hola"}
        ]
        mock_pool, _ = make_mock_pool(fetch_result=mock_rows)

        with patch.object(rg_mod, "_report_types", {"diario": ReporteDiario}):
            with patch("interface.telemetry") as mock_telemetry:
                mock_telemetry._pool = mock_pool
                transport = httpx.ASGITransport(app=interface.app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/reportes/generar",
                        json={"tipo": "diario", "parametros": {}},
                    )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"

    @pytest.mark.asyncio
    async def test_generate_unknown_tipo_returns_error(self):
        """POST with unknown tipo returns error."""
        import interface

        with patch("interface.telemetry") as mock_telemetry:
            mock_telemetry._pool = MagicMock()
            transport = httpx.ASGITransport(app=interface.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/reportes/generar",
                    json={"tipo": "nonexistent", "parametros": {}},
                )

        # Should return 400 or 404 depending on error mapping
        assert response.status_code in (400, 404)
        body = response.json()
        assert "error" in body or "detail" in body

    @pytest.mark.asyncio
    async def test_generate_missing_required_param_returns_400(self):
        """POST without required telefono for historial returns 400."""
        import interface

        with patch("interface.telemetry") as mock_telemetry:
            mock_telemetry._pool = MagicMock()
            transport = httpx.ASGITransport(app=interface.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/reportes/generar",
                    json={"tipo": "historial", "parametros": {}},
                )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_generate_no_pool_returns_error(self):
        """POST when pool is None returns 503."""
        import interface

        with patch("interface.telemetry") as mock_telemetry:
            mock_telemetry._pool = None
            transport = httpx.ASGITransport(app=interface.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/reportes/generar",
                    json={"tipo": "diario", "parametros": {}},
                )

        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_tipos_endpoint_has_correct_ids(self):
        """Verify all 4 report type IDs are present in the API response."""
        import interface

        transport = httpx.ASGITransport(app=interface.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/reportes/tipos")

        assert response.status_code == 200
        ids = [t["id"] for t in response.json()["tipos"]]
        assert set(ids) == {"diario", "historial", "por-dia", "completo"}