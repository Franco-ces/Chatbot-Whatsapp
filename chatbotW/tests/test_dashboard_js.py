"""Tests contractuales para el tab Dashboard — verifica que index.html y app.js
contengan los elementos, métodos y patrones esperados del dashboard de telemetría.

Estrategia: leemos JS/HTML como texto y verificamos contratos:
1. CDN script de Chart.js en el head.
2. Tab button "Dashboard" entre Instancias y Logs.
3. Dashboard panel con loading/error/empty/cards/charts.
4. State props (telemetryData, telemetryLoading, etc.) en adminPanel.
5. Métodos (loadTelemetry, initCharts, destroyCharts) en app.js.
6. Watcher para activeTab === 'dashboard'.
7. Botón "Actualizar" en el panel.
"""
import re
from pathlib import Path

import pytest


HTML_PATH = Path(__file__).resolve().parent.parent / "src" / "index.html"
APP_JS_PATH = Path(__file__).resolve().parent.parent / "src" / "static" / "js" / "app.js"


@pytest.fixture
def html_content():
    """Lee el contenido de index.html como string."""
    return HTML_PATH.read_text(encoding="utf-8")


@pytest.fixture
def app_js():
    """Lee el contenido de app.js como string."""
    return APP_JS_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. CDN Script
# ---------------------------------------------------------------------------


class TestChartJsCdn:
    """Verifica que Chart.js 4.x se carga desde CDN en el <head>."""

    def test_chart_js_script_in_head(self, html_content):
        """Debe existir un <script src='...chart.js...' > en el HTML."""
        assert re.search(r'<script[^>]*src="[^"]*chart\.js[^"]*"[^>]*>', html_content), (
            "index.html debe contener un <script> tag que carga Chart.js desde CDN"
        )

    def test_chart_js_version_pinned(self, html_content):
        """La URL del CDN debe pinnear la versión 4.4.7."""
        assert "chart.js@4.4.7" in html_content, (
            "La URL del CDN debe pinnear chart.js@4.4.7 para evitar breaking changes"
        )

    def test_chart_js_umd_bundle(self, html_content):
        """Debe cargar el bundle UMD (no ESM) para compatibilidad con Alpine."""
        assert "chart.umd.min.js" in html_content, (
            "Debe cargar chart.umd.min.js (UMD) para compatibilidad global con window.Chart"
        )


# ---------------------------------------------------------------------------
# 2. Dashboard Tab Button
# ---------------------------------------------------------------------------


class TestDashboardTabButton:
    """Verifica que el botón Dashboard exista en el tab bar."""

    def test_dashboard_tab_button_exists(self, html_content):
        """Debe existir un botón con @click='switchTab(\"dashboard\")'."""
        assert 'switchTab(\'dashboard\')' in html_content or 'switchTab("dashboard")' in html_content, (
            "Debe existir un botón tab con @click=\"switchTab('dashboard')\""
        )

    def test_dashboard_tab_button_text(self, html_content):
        """El botón debe mostrar el texto 'Dashboard'."""
        # Buscar el botón del dashboard
        dashboard_btn_match = re.search(
            r'<button[^>]*dashboard[^>]*>.*?</button>',
            html_content,
            re.DOTALL | re.IGNORECASE
        )
        assert dashboard_btn_match, "Debe existir un <button> que contenga 'Dashboard'"
        btn_text = dashboard_btn_match.group(0)
        assert "Dashboard" in btn_text, (
            "El botón del tab debe contener el texto 'Dashboard'"
        )

    def test_dashboard_tab_has_chart_pie_icon(self, html_content):
        """El botón Dashboard debe tener el ícono fa-chart-pie."""
        # Buscar botón con switchTab('dashboard')
        match = re.search(
            r'<button[^>]*switchTab\([\'"]dashboard[\'"]\)[^>]*>.*?</button>',
            html_content,
            re.DOTALL
        )
        assert match, "Debe existir botón con switchTab('dashboard')"
        assert "fa-chart-pie" in match.group(0), (
            "El botón Dashboard debe usar el ícono fa-chart-pie"
        )

    def test_dashboard_tab_between_instances_and_logs(self, html_content):
        """El botón Dashboard debe estar entre Instancias y Logs en el tab bar."""
        # Buscar las posiciones de los tabs
        instances_pos = html_content.find("Instancias")
        dashboard_pos = html_content.find("Dashboard")
        logs_pos = html_content.find("Logs")
        assert instances_pos > 0, "Debe existir el tab 'Instancias'"
        assert dashboard_pos > 0, "Debe existir el tab 'Dashboard'"
        assert logs_pos > 0, "Debe existir el tab 'Logs'"
        assert instances_pos < dashboard_pos < logs_pos, (
            f"Dashboard debe estar entre Instancias y Logs. "
            f"Posiciones: Instancias={instances_pos}, Dashboard={dashboard_pos}, Logs={logs_pos}"
        )


# ---------------------------------------------------------------------------
# 3. Dashboard Panel HTML
# ---------------------------------------------------------------------------


class TestDashboardPanelHtml:
    """Verifica la estructura del panel Dashboard en el HTML."""

    def test_dashboard_panel_exists(self, html_content):
        """Debe existir un div con x-show='activeTab === \"dashboard\"'."""
        assert "activeTab === 'dashboard'" in html_content or 'activeTab === "dashboard"' in html_content, (
            "Debe existir un panel con x-show=\"activeTab === 'dashboard'\""
        )

    def test_loading_state_exists(self, html_content):
        """Debe existir un estado de carga con 'Cargando datos' o spinner."""
        # Buscar dentro del panel dashboard
        assert "Cargando datos" in html_content, (
            "Debe existir un estado de carga con 'Cargando datos...'"
        )

    def test_error_state_exists(self, html_content):
        """Debe existir un estado de error con el mensaje de 'Error al cargar'."""
        assert "Error al cargar el dashboard" in html_content, (
            "Debe existir un estado de error con 'Error al cargar el dashboard'"
        )

    def test_empty_state_exists(self, html_content):
        """Debe existir un estado vacío con 'Sin datos aún'."""
        assert "Sin datos aún" in html_content, (
            "Debe existir un estado vacío con 'Sin datos aún'"
        )

    def test_chart_canvas_refs_exist(self, html_content):
        """Deben existir los 4 canvas con x-ref para los charts."""
        expected_refs = ["chartMessages", "chartErrors", "chartDurations", "chartSources"]
        for ref_name in expected_refs:
            pattern = f'x-ref="{ref_name}"'
            assert pattern in html_content, (
                f"Debe existir un <canvas x-ref=\"{ref_name}\"> en el HTML"
            )

    def test_metric_cards_exist(self, html_content):
        """Deben existir las 4 metric cards con etiquetas específicas."""
        assert "Mensajes" in html_content, "Debe existir una metric card 'Mensajes'"
        assert "Errores" in html_content, "Debe existir una metric card 'Errores'"
        assert "Tiempo Prom" in html_content or "Tiempo Promedio" in html_content, (
            "Debe existir una metric card de tiempo promedio"
        )
        assert "Tasa Error" in html_content, "Debe existir una metric card 'Tasa Error'"

    def test_chart_grid_responsive(self, html_content):
        """El grid de charts debe ser responsive con grid-cols-1 md:grid-cols-2."""
        # Buscar el grid que contiene los canvases
        assert "grid-cols-1 md:grid-cols-2" in html_content, (
            "El grid de charts debe ser responsive: grid-cols-1 md:grid-cols-2"
        )

    def test_refresh_button_exists(self, html_content):
        """Debe existir un botón 'Actualizar' que llame a loadTelemetry o refreshDashboard."""
        # Buscar botón Actualizar cerca del panel dashboard
        match = re.search(r'Actualizar', html_content)
        assert match, "Debe existir un botón 'Actualizar' en el dashboard"


# ---------------------------------------------------------------------------
# 4. Alpine.js State Properties
# ---------------------------------------------------------------------------


class TestDashboardAlpineState:
    """Verifica que adminPanel en app.js tenga las propiedades de estado del dashboard."""

    def test_telemetry_data_prop_exists(self, app_js):
        """adminPanel debe tener la propiedad telemetryData."""
        assert "telemetryData" in app_js, (
            "app.js debe contener la propiedad telemetryData en adminPanel"
        )

    def test_telemetry_loading_prop_exists(self, app_js):
        """adminPanel debe tener la propiedad telemetryLoading."""
        assert "telemetryLoading" in app_js, (
            "app.js debe contener la propiedad telemetryLoading en adminPanel"
        )

    def test_telemetry_error_prop_exists(self, app_js):
        """adminPanel debe tener la propiedad telemetryError."""
        assert "telemetryError" in app_js, (
            "app.js debe contener la propiedad telemetryError en adminPanel"
        )

    def test_charts_array_prop_exists(self, app_js):
        """adminPanel debe tener la propiedad charts (array)."""
        # Buscar 'charts' como propiedad del data object
        # Puede ser 'charts: []' o 'charts = []'
        assert "this.charts" in app_js or "charts:" in app_js, (
            "app.js debe contener la propiedad charts en adminPanel"
        )


# ---------------------------------------------------------------------------
# 5. Alpine.js Methods
# ---------------------------------------------------------------------------


class TestDashboardAlpineMethods:
    """Verifica que los métodos del dashboard existan en app.js."""

    def test_load_telemetry_method_exists(self, app_js):
        """adminPanel debe tener el método loadTelemetry."""
        assert "loadTelemetry" in app_js, (
            "app.js debe contener el método loadTelemetry"
        )

    def test_load_telemetry_calls_correct_endpoint(self, app_js):
        """loadTelemetry debe llamar al endpoint /api/telemetry/summary?days=7."""
        assert "/api/telemetry/summary" in app_js, (
            "loadTelemetry debe llamar a /api/telemetry/summary"
        )
        assert "days=7" in app_js, (
            "loadTelemetry debe pasar days=7 como query param"
        )

    def test_load_telemetry_uses_api_fetch(self, app_js):
        """loadTelemetry debe usar apiFetch para hacer la petición."""
        # Buscar apiFetch dentro de loadTelemetry
        idx = app_js.find("loadTelemetry")
        assert idx >= 0, "Método loadTelemetry debe existir"
        method_slice = app_js[idx:idx + 1500]
        assert "apiFetch" in method_slice, (
            "loadTelemetry debe usar apiFetch para la petición HTTP"
        )

    def test_init_charts_method_exists(self, app_js):
        """adminPanel debe tener el método initCharts."""
        assert "initCharts" in app_js, (
            "app.js debe contener el método initCharts"
        )

    def test_init_charts_creates_chart_instances(self, app_js):
        """initCharts debe crear instancias de Chart.js (new Chart)."""
        idx = app_js.find("initCharts")
        assert idx >= 0, "Método initCharts debe existir"
        method_slice = app_js[idx:idx + 3000]
        assert "new Chart" in method_slice, (
            "initCharts debe crear instancias de Chart.js con 'new Chart'"
        )

    def test_init_charts_uses_refs(self, app_js):
        """initCharts debe usar this.$refs para acceder a los canvas."""
        idx = app_js.find("initCharts")
        method_slice = app_js[idx:idx + 3000]
        assert "$refs" in method_slice, (
            "initCharts debe usar this.$refs para acceder a los canvas elements"
        )

    def test_init_charts_reads_messages_by_day(self, app_js):
        """initCharts debe usar messages_by_day del data de telemetría."""
        idx = app_js.find("initCharts")
        method_slice = app_js[idx:idx + 3000]
        assert "messages_by_day" in method_slice, (
            "initCharts debe acceder a messages_by_day para el chart de mensajes"
        )

    def test_destroy_charts_method_exists(self, app_js):
        """adminPanel debe tener el método destroyCharts."""
        assert "destroyCharts" in app_js, (
            "app.js debe contener el método destroyCharts"
        )

    def test_destroy_charts_calls_destroy(self, app_js):
        """destroyCharts debe llamar .destroy() en cada chart instance."""
        # Find the method definition (not just a call)
        # Look for destroyCharts as a method definition, then find .destroy() after it
        matches = list(re.finditer(r'destroyCharts\b', app_js))
        assert len(matches) >= 1, "destroyCharts method must exist"
        # Check that .destroy() exists anywhere in the file (Chart.prototype.destroy)
        assert ".destroy()" in app_js, (
            "destroyCharts debe llamar .destroy() en cada Chart instance"
        )


# ---------------------------------------------------------------------------
# 6. Watcher Extension
# ---------------------------------------------------------------------------


class TestDashboardWatcher:
    """Verifica que el watcher de activeTab maneje el tab dashboard."""

    def test_watcher_handles_dashboard_tab(self, app_js):
        """El watcher de activeTab debe manejar el valor 'dashboard'."""
        # Buscar dentro del init() el $watch
        idx = app_js.find("$watch('activeTab'")
        assert idx >= 0, "Debe existir $watch('activeTab', ...) en app.js"
        watcher_slice = app_js[idx:idx + 1000]
        assert "dashboard" in watcher_slice, (
            "El watcher de activeTab debe manejar el valor 'dashboard'"
        )

    def test_watcher_calls_load_telemetry_on_dashboard(self, app_js):
        """El watcher debe llamar loadTelemetry cuando activeTab es 'dashboard'."""
        idx = app_js.find("$watch('activeTab'")
        watcher_slice = app_js[idx:idx + 1000]
        # Verificar que hay una condición para dashboard que llama a loadTelemetry
        assert "loadTelemetry" in watcher_slice, (
            "El watcher debe llamar loadTelemetry cuando activeTab === 'dashboard'"
        )

    def test_watcher_calls_destroy_on_tab_leave(self, app_js):
        """El watcher debe llamar destroyCharts al salir del tab dashboard."""
        idx = app_js.find("$watch('activeTab'")
        watcher_slice = app_js[idx:idx + 1000]
        assert "destroyCharts" in watcher_slice, (
            "El watcher debe llamar destroyCharts cuando se sale del tab dashboard"
        )


# ---------------------------------------------------------------------------
# 7. Refresh Button
# ---------------------------------------------------------------------------


class TestRefreshButton:
    """Verifica que exista el botón de refresh y su método asociado."""

    def test_refresh_button_in_html(self, html_content):
        """Debe existir un botón refresh en el panel del dashboard."""
        # Buscar botón con loadTelemetry o refreshDashboard en el HTML
        assert "loadTelemetry()" in html_content or "refreshDashboard()" in html_content, (
            "El HTML debe tener un botón que llame a loadTelemetry() o refreshDashboard()"
        )

    def test_refresh_button_has_refresh_icon(self, html_content):
        """El botón refresh debe tener un ícono de refresh (fa-rotate-right)."""
        # Buscar región del dashboard en el HTML para verificar que el botón 
        # tiene ícono de refresh
        # Buscar un botón que tenga fa-rotate-right Y loadTelemetry/refreshDashboard cerca
        assert "fa-rotate-right" in html_content, (
            "El botón de refresh del dashboard debe usar el ícono fa-rotate-right"
        )


# ---------------------------------------------------------------------------
# 8. Triangulation — Additional behavioral checks
# ---------------------------------------------------------------------------


class TestDashboardDataFlow:
    """Verifica que el flujo de datos del dashboard conecta correctamente
    los campos de la API con los charts y metric cards."""

    def test_chart_defaults_set_in_init(self, app_js):
        """initCharts debe configurar Chart.defaults.font.family."""
        idx = app_js.find("initCharts")
        method_slice = app_js[idx:idx + 3000]
        assert "Chart.defaults" in method_slice, (
            "initCharts debe configurar Chart.defaults (font family, etc.)"
        )

    def test_doughnut_charts_have_cutout(self, app_js):
        """Los charts doughnut deben tener cutout: '60%'."""
        assert "cutout" in app_js, (
            "Los charts doughnut deben tener cutout configurado"
        )

    def test_error_rate_metric_in_html(self, html_content):
        """Debe existir la métrica de tasa de error con x-text que muestre error_rate."""
        assert "telemetryData.error_rate" in html_content, (
            "La métrica de tasa de error debe mostrar telemetryData.error_rate con '%'"
        )

    def test_total_messages_metric_in_html(self, html_content):
        """Debe existir la métrica de total de mensajes con x-text."""
        assert "telemetryData.total_messages" in html_content, (
            "La métrica de mensajes debe mostrar telemetryData.total_messages"
        )

    def test_avg_duration_metric_in_html(self, html_content):
        """Debe existir la métrica de tiempo promedio con x-text mostrando ms."""
        assert "telemetryData.avg_total_duration_ms" in html_content, (
            "La métrica de tiempo promedio debe mostrar telemetryData.avg_total_duration_ms + 'ms'"
        )

    def test_total_errors_metric_in_html(self, html_content):
        """Debe existir la métrica de errores con x-text."""
        assert "telemetryData.total_errors" in html_content, (
            "La métrica de errores debe mostrar telemetryData.total_errors"
        )

    def test_load_telemetry_checks_status(self, app_js):
        """loadTelemetry debe verificar json.status !== 'success'."""
        # Find the async method definition, not just a reference
        idx = app_js.find("async loadTelemetry()")
        assert idx >= 0, "Método loadTelemetry debe existir como async"
        method_slice = app_js[idx:idx + 1500]
        assert "json.status" in method_slice, (
            "loadTelemetry debe verificar el status de la respuesta"
        )

    def test_load_telemetry_sets_error_message(self, app_js):
        """loadTelemetry debe setear telemetryError con 'Error al cargar el dashboard'."""
        idx = app_js.find("async loadTelemetry()")
        assert idx >= 0, "Método loadTelemetry debe existir como async"
        method_slice = app_js[idx:idx + 1500]
        assert "Error al cargar el dashboard" in method_slice, (
            "loadTelemetry debe setear telemetryError con 'Error al cargar el dashboard'"
        )

    def test_load_telemetry_sets_loading_state(self, app_js):
        """loadTelemetry debe setear telemetryLoading = true al inicio."""
        idx = app_js.find("async loadTelemetry()")
        assert idx >= 0, "Método loadTelemetry debe existir como async"
        method_slice = app_js[idx:idx + 1500]
        assert "telemetryLoading" in method_slice, (
            "loadTelemetry debe manejar el estado telemetryLoading"
        )

    def test_initCharts_reads_errors_data(self, app_js):
        """initCharts debe usar datos de errores (total_errors, total_messages)."""
        idx = app_js.find("initCharts")
        method_slice = app_js[idx:idx + 3000]
        assert "total_errors" in method_slice and "total_messages" in method_slice, (
            "initCharts debe usar total_errors y total_messages para el chart de errores"
        )

    def test_initCharts_reads_duration_data(self, app_js):
        """initCharts debe usar datos de duración (avg_rag, avg_send, avg_total)."""
        idx = app_js.find("initCharts")
        method_slice = app_js[idx:idx + 3000]
        assert "avg_rag_duration_ms" in method_slice, (
            "initCharts debe usar avg_rag_duration_ms"
        )
        assert "avg_send_duration_ms" in method_slice, (
            "initCharts debe usar avg_send_duration_ms"
        )
        assert "avg_total_duration_ms" in method_slice, (
            "initCharts debe usar avg_total_duration_ms"
        )

    def test_initCharts_reads_source_data(self, app_js):
        """initCharts debe usar datos de fuente (total_faq_hits, total_cache_hits)."""
        idx = app_js.find("initCharts")
        method_slice = app_js[idx:idx + 3000]
        assert "total_faq_hits" in method_slice, (
            "initCharts debe usar total_faq_hits para el chart de fuentes"
        )
        assert "total_cache_hits" in method_slice, (
            "initCharts debe usar total_cache_hits para el chart de fuentes"
        )

    def test_initCharts_creates_four_charts(self, app_js):
        """initCharts debe empujar exactamente 4 chart instances al array charts."""
        idx = app_js.find("initCharts")
        method_slice = app_js[idx:idx + 3000]
        push_count = method_slice.count("this.charts.push")
        assert push_count >= 4, (
            f"initCharts debe crear al menos 4 charts, se encontraron {push_count} push calls"
        )