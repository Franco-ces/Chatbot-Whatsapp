"""Tests contractuales para instances.js — verifica que el archivo
contenga los métodos y patrones esperados del kebab menu y
desactivación.

Estrategia: leemos el JS como texto y verificamos:
1. `deactivateInstance` existe y llama al endpoint correcto.
2. `toggleMenu` existe y tiene la lógica de open/close.
3. Los patrones de enable/disable según estado de instancia existen.
"""
import re
from pathlib import Path

import pytest


JS_PATH = Path(__file__).resolve().parent.parent / "src" / "static" / "js" / "instances.js"


@pytest.fixture
def js_content():
    """Lee el contenido de instances.js como string."""
    return JS_PATH.read_text(encoding="utf-8")


class TestDeactivateInstanceMethod:
    """Verifica que deactivateInstance exista y use el endpoint correcto."""

    def test_deactivate_instance_method_exists(self, js_content):
        """instances.js debe contener un método deactivateInstance."""
        assert "deactivateInstance" in js_content

    def test_deactivate_calls_correct_endpoint(self, js_content):
        """deactivateInstance debe llamar al endpoint
        /api/evolution/instances/{name}/deactivate."""
        # Buscamos la llamada al endpoint dentro del método
        pattern = r"/api/evolution/instances/.*?/deactivate"
        assert re.search(pattern, js_content), (
            "deactivateInstance debe llamar a /api/evolution/instances/{name}/deactivate"
        )

    def test_deactivate_uses_post_method(self, js_content):
        """La llamada fetch debe usar method: 'POST'."""
        # Buscamos POST dentro de deactivateInstance (método completo ~600 chars)
        deactivate_section = js_content[js_content.index("deactivateInstance"):]
        deactivate_section = deactivate_section[:1500]
        assert "method: 'POST'" in deactivate_section, (
            "deactivateInstance debe usar method: 'POST'"
        )

    def test_deactivate_shows_confirmation(self, js_content):
        """deactivateInstance debe pedir confirmación antes de actuar."""
        deactivate_section = js_content[js_content.index("deactivateInstance"):]
        deactivate_section = deactivate_section[:800]
        assert "confirm" in deactivate_section.lower(), (
            "deactivateInstance debe usar confirm() para pedir confirmación"
        )

    def test_deactivate_refreshes_list_optimistic(self, js_content):
        """Tras desactivar exitosamente, debe setear activeName='' optimistamente
        (el write del config es async) y refrescar SOLO la lista (no el active,
        para no pisar el valor optimista con el stale del server)."""
        deactivate_section = js_content[js_content.index("deactivateInstance"):]
        # Tomamos hasta el cierre del metodo (siguiente `},` al nivel
        # del bloque del componente). 3000 chars es holgado para cubrir
        # el cuerpo del try/catch completo.
        deactivate_section = deactivate_section[:3000]
        # Optimistic update: activeName se limpia localmente para que la UI
        # muestre el estado consistente con lo que el usuario espera.
        assert "this.activeName = ''" in deactivate_section, (
            "deactivateInstance debe setear activeName='' optimistamente "
            "(el write del config es async, el GET /active puede devolver stale)"
        )
        # Refresh solo de la lista (no loadInstances, que pisaria el active).
        assert "refreshInstancesList" in deactivate_section, (
            "deactivateInstance debe llamar a refreshInstancesList "
            "(no loadInstances, que pisaria activeName con el stale)"
        )


class TestToggleMenuMethod:
    """Verifica que toggleMenu exista y maneje open/close."""

    def test_toggle_menu_method_exists(self, js_content):
        """instances.js debe contener un método toggleMenu."""
        assert "toggleMenu" in js_content

    def test_toggle_menu_manages_state(self, js_content):
        """toggleMenu debe alternar el valor de openMenus."""
        toggle_section = js_content[js_content.index("toggleMenu"):]
        toggle_section = toggle_section[:300]
        assert "openMenus" in toggle_section, (
            "toggleMenu debe usar la propiedad openMenus"
        )

    def test_toggle_menu_closes_when_already_open(self, js_content):
        """Si el menú ya está abierto, toggleMenu debe quitarlo del array."""
        toggle_section = js_content[js_content.index("toggleMenu"):]
        toggle_section = toggle_section[:500]
        assert "splice" in toggle_section, (
            "toggleMenu debe usar splice para quitar el menú del array"
        )

    def test_is_menu_open_method_exists(self, js_content):
        """instances.js debe contener un método isMenuOpen."""
        assert "isMenuOpen" in js_content

    def test_close_all_menus_method_exists(self, js_content):
        """instances.js debe contener un método closeAllMenus."""
        assert "closeAllMenus" in js_content


class TestInstanceStateLogic:
    """Verifica que existan patrones de enable/disable según estado."""

    def test_active_name_property_exists(self, js_content):
        """El componente debe tener la propiedad activeName."""
        assert "activeName" in js_content

    def test_is_active_method_exists(self, js_content):
        """El componente debe tener un método isActive."""
        assert "isActive" in js_content

    def test_connection_state_checked(self, js_content):
        """Debe verificarse connectionState para habilitar/deshabilitar."""
        assert "connectionState" in js_content
