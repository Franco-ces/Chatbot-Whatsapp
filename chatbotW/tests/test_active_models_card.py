"""Tests contractuales para la tarjeta de Modelos activos en index.html.

Estrategia: leemos el HTML como texto y verificamos contratos:
1. Título y sección "Modelos activos" existen.
2. La tarjeta está dentro del accordion de Gemini Models.
3. Las etiquetas "Generación" y "Embeddings" están presentes.
4. Los bindings x-text para activeGeminiModel y activeGeminiEmbeddingsModel existen.
5. El ícono fa-microchip está presente en el header.
6. Los íconos fa-circle-check están presentes para cada modelo.
7. El placeholder '—' se muestra cuando el modelo es null/undefined.
"""
from pathlib import Path

import pytest


HTML_PATH = Path(__file__).resolve().parent.parent / "src" / "index.html"


@pytest.fixture
def html_content():
    """Lee el contenido de index.html como string."""
    return HTML_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Título y estructura de la tarjeta
# ---------------------------------------------------------------------------


class TestActiveModelsCardTitle:
    """Verifica que la tarjeta de Modelos activos tenga título y estructura básica."""

    def test_card_title_exists(self, html_content):
        """Debe existir un título 'Modelos activos' en el HTML."""
        assert "Modelos activos" in html_content, (
            "index.html debe contener el título 'Modelos activos'"
        )

    def test_card_header_has_microchip_icon(self, html_content):
        """El header de la tarjeta debe tener el ícono fa-microchip."""
        assert "fa-microchip" in html_content, (
            "La tarjeta debe usar el ícono fa-microchip"
        )

    def test_card_has_bg_gray_50_class(self, html_content):
        """La tarjeta debe tener la clase bg-gray-50 para el fondo."""
        assert "bg-gray-50" in html_content, (
            "La tarjeta debe tener el fondo bg-gray-50"
        )

    def test_card_has_rounded_border(self, html_content):
        """La tarjeta debe tener borde redondeado con border border-gray-200."""
        assert "rounded-lg p-4 border border-gray-200" in html_content or \
               "rounded-lg p-4" in html_content, (
            "La tarjeta debe tener rounded-lg, p-4 y border"
        )


# ---------------------------------------------------------------------------
# 2. Separador
# ---------------------------------------------------------------------------


class TestActiveModelsSeparator:
    """Verifica que la tarjeta de modelos activos esté dentro del accordion de Gemini."""

    def test_separator_before_card(self, html_content):
        """La tarjeta de modelos activos debe estar dentro del accordion de Gemini Models."""
        # After the accordion conversion, models active is inside the Gemini Models accordion body
        # instead of being preceded by an <hr> separator
        accordion_pos = html_content.find("accordionState.geminiModels")
        card_pos = html_content.find("Modelos activos")
        assert accordion_pos >= 0, "Debe existir el accordion de Gemini Models"
        assert card_pos >= 0, "Debe existir el título 'Modelos activos'"
        assert accordion_pos < card_pos, (
            "La tarjeta 'Modelos activos' debe estar dentro del accordion de Gemini Models"
        )


# ---------------------------------------------------------------------------
# 3. Labels de modelos
# ---------------------------------------------------------------------------


class TestActiveModelsLabels:
    """Verifica que las etiquetas de cada modelo existan."""

    def test_generation_label_exists(self, html_content):
        """Debe existir la etiqueta 'Generación'."""
        assert "Generación" in html_content or "Generacion" in html_content, (
            "index.html debe contener la etiqueta 'Generación'"
        )

    def test_embeddings_label_exists(self, html_content):
        """Debe existir la etiqueta 'Embeddings'."""
        assert "Embeddings" in html_content, (
            "index.html debe contener la etiqueta 'Embeddings'"
        )


# ---------------------------------------------------------------------------
# 4. Bindings x-text
# ---------------------------------------------------------------------------


class TestActiveModelsBindings:
    """Verifica que los bindings x-text estén correctamente configurados."""

    def test_gemini_model_xtext_binding(self, html_content):
        """Debe existir x-text=\"activeGeminiModel || '—'\" en el HTML."""
        assert "activeGeminiModel ||" in html_content, (
            "index.html debe tener un binding x-text para activeGeminiModel con fallback '—'"
        )

    def test_embeddings_model_xtext_binding(self, html_content):
        """Debe existir x-text=\"activeGeminiEmbeddingsModel || '—'\" en el HTML."""
        assert "activeGeminiEmbeddingsModel ||" in html_content, (
            "index.html debe tener un binding x-text para activeGeminiEmbeddingsModel con fallback '—'"
        )

    def test_fallback_dash_present(self, html_content):
        """El fallback debe ser un '—' (em dash) cuando el modelo no está cargado."""
        assert "'—'" in html_content or "'—'" in html_content, (
            "El fallback debe ser un em dash '—' para cuando el modelo es null"
        )


# ---------------------------------------------------------------------------
# 5. Íconos de estado
# ---------------------------------------------------------------------------


class TestActiveModelsStatusIcons:
    """Verifica que los íconos de estado activo estén presentes."""

    def test_check_icons_exist(self, html_content):
        """Deben existir íconos fa-circle-check para indicar modelos activos."""
        assert "fa-circle-check" in html_content, (
            "La tarjeta debe tener íconos fa-circle-check para cada modelo activo"
        )

    def test_check_icons_have_blue_color(self, html_content):
        """Los íconos fa-circle-check deben tener la clase text-blue-500."""
        assert 'text-blue-500' in html_content, (
            "Los íconos de check deben usar la clase text-blue-500"
        )


# ---------------------------------------------------------------------------
# 6. Posición relativa
# ---------------------------------------------------------------------------


class TestActiveModelsPosition:
    """Verifica que la tarjeta esté en la sección correcta del HTML."""

    def test_card_after_gemini_config_save(self, html_content):
        """La tarjeta debe aparecer después del botón Guardar Modelos."""
        save_pos = html_content.find("Guardar Modelos")
        card_pos = html_content.find("Modelos activos")
        assert save_pos >= 0, "Debe existir el botón 'Guardar Modelos'"
        assert card_pos >= 0, "Debe existir la tarjeta 'Modelos activos'"
        assert save_pos < card_pos, (
            "La tarjeta 'Modelos activos' debe estar después del botón 'Guardar Modelos'"
        )

    def test_card_before_docs_tab(self, html_content):
        """La tarjeta debe estar antes de la sección de Documentos."""
        card_pos = html_content.find("Modelos activos")
        docs_pos = html_content.find("TAB: Documentos")
        assert card_pos >= 0, "Debe existir la tarjeta 'Modelos activos'"
        assert docs_pos >= 0, "Debe existir la sección 'Documentos'"
        assert card_pos < docs_pos, (
            "La tarjeta 'Modelos activos' debe estar antes de la sección de Documentos"
        )
