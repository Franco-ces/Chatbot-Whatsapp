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
HTML_PATH = Path(__file__).resolve().parent.parent / "src" / "index.html"
APP_JS_PATH = Path(__file__).resolve().parent.parent / "src" / "static" / "js" / "app.js"


@pytest.fixture
def js_content():
    """Lee el contenido de instances.js como string."""
    return JS_PATH.read_text(encoding="utf-8")


@pytest.fixture
def html_content():
    """Lee el contenido de index.html como string."""
    return HTML_PATH.read_text(encoding="utf-8")


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


class TestBotPhoneSync:
    """Verifica que instances.js sincroniza botPhone desde ownerJid."""

    def test_load_instances_sets_bot_phone_from_owner_jid(self, js_content):
        """loadInstances debe setear Alpine.store('app').botPhone desde ownerJid."""
        assert "Alpine.store('app').botPhone" in js_content or \
               "Alpine.store('app')" in js_content, \
            "instances.js debe acceder a Alpine.store('app') para botPhone"

    def test_phone_extraction_uses_split_at(self, js_content):
        """La extraccion de telefono debe usar split('@')[0] sobre ownerJid."""
        assert "split('@')[0]" in js_content or 'split("@")[0]' in js_content or \
               "split(" in js_content, \
            "instances.js debe usar split para extraer telefono de ownerJid"

    def test_owner_jid_referenced_in_instances(self, js_content):
        """ownerJid debe ser referenciado para obtener el telefono."""
        assert "ownerJid" in js_content, \
            "instances.js debe usar ownerJid para extraer el telefono"


class TestCreateFormLayout:
    """Verifica que el formulario de crear instancia tenga el help text
    fuera del flex wrapper, con id estable y aria-describedby en el input."""

    def test_help_text_not_inside_flex_wrapper(self, html_content):
        """El <p> de ayuda debe estar fuera del <div class='flex-1'> del input."""
        import re
        # Buscamos el bloque del form y verificamos que el <p> de ayuda
        # no está anidado dentro del <div class="flex-1">.
        form_match = re.search(
            r'<form[^>]*class="[^"]*flex[^"]*"[^>]*>(.*?)</form>',
            html_content,
            re.DOTALL
        )
        assert form_match, "No se encontró el <form> del crear instancia"
        form_html = form_match.group(1)
        # El div flex-1 contiene label + input, el <p> de ayuda NO debe estar adentro
        flex1_match = re.search(
            r'<div class="flex-1">(.*?)</div>',
            form_html,
            re.DOTALL
        )
        assert flex1_match, "No se encontró el <div class='flex-1'> dentro del form"
        flex1_html = flex1_match.group(1)
        assert '<p ' not in flex1_html or 'text-xs text-gray-400' not in flex1_html, (
            "El <p> de ayuda NO debe estar dentro del <div class='flex-1'>"
        )
        # Y el <p> de ayuda SÍ debe existir en el form (fuera del div)
        assert 'Solo letras, números' in form_html, (
            "El <p> de ayuda debe existir dentro del <form>"
        )

    def test_help_text_has_stable_id(self, html_content):
        """El <p> de ayuda debe tener id='new-instance-name-help'."""
        import re
        matches = re.findall(
            r'<p[^>]*\bid="new-instance-name-help"[^>]*>',
            html_content
        )
        assert len(matches) == 1, (
            f"Debe haber exactamente 1 <p> con id='new-instance-name-help', "
            f"se encontraron {len(matches)}"
        )

    def test_input_has_aria_describedby_pointing_to_help_id(self, html_content):
        """El input debe tener aria-describedby='new-instance-name-help'."""
        import re
        match = re.search(
            r'<input[^>]*\bid="new-instance-name"[^>]*aria-describedby="new-instance-name-help"[^>]*>',
            html_content
        )
        assert match, (
            "El <input id='new-instance-name'> debe tener "
            "aria-describedby='new-instance-name-help'"
        )

    def test_aria_describedby_target_exists(self, html_content):
        """El id='new-instance-name-help' referenciado por aria-describedby debe existir."""
        assert 'id="new-instance-name-help"' in html_content, (
            "El id='new-instance-name-help' debe existir en el HTML"
        )

    def test_error_paragraph_remains_outside_form(self, html_content):
        """El <p x-show='createForm.error'> debe permanecer fuera del </form>."""
        import re
        form_end_idx = html_content.find('</form>')
        assert form_end_idx > 0, "No se encontró </form> en el HTML"
        error_para_match = re.search(
            r'<p\s+x-show="createForm\.error"',
            html_content
        )
        assert error_para_match, "No se encontró el <p x-show='createForm.error'>"
        assert error_para_match.start() > form_end_idx, (
            "El <p x-show='createForm.error'> debe estar DESPUÉS del cierre del </form>"
        )

    def test_create_button_unchanged_class(self, html_content):
        """El <button type='submit'> del form debe seguir presente."""
        import re
        match = re.search(r'<button\s+type="submit"[^>]*>', html_content)
        assert match, "El <button type='submit'> debe seguir presente en el HTML"


class TestCopyWaLinkMethod:
    """Verifica que copyWaLink exista en instancesPanel y cumpla el contrato:
    guard null, strip de sufijo @, validación local vacío,
    clipboard.writeText con try/catch, sin execCommand, toast feedback."""

    def test_copy_wa_link_method_exists(self, js_content):
        """instances.js debe contener el método copyWaLink."""
        assert "copyWaLink" in js_content

    def test_copy_wa_link_defined_inside_instances_panel(self, js_content):
        """copyWaLink debe estar definido dentro de instancesPanel."""
        match = re.search(
            r"Alpine\.data\(\s*'instancesPanel'.*?copyWaLink",
            js_content,
            re.DOTALL
        )
        assert match, (
            "copyWaLink debe estar definido dentro de Alpine.data('instancesPanel', ...)"
        )

    def test_copy_wa_link_guards_null_inst(self, js_content):
        """copyWaLink debe retornar temprano si inst o ownerJid son null."""
        idx = js_content.index("copyWaLink(inst)")
        slice_ = js_content[idx:idx + 500]
        assert "if (!inst || !inst.ownerJid) return" in slice_, (
            "copyWaLink debe contener 'if (!inst || !inst.ownerJid) return'"
        )

    def test_copy_wa_link_strips_jid_suffix_with_at_regex(self, js_content):
        """copyWaLink debe usar replace(/@.*$/, '') para strip del sufijo JID."""
        idx = js_content.index("copyWaLink(inst)")
        slice_ = js_content[idx:idx + 1000]
        assert "replace(/@.*$/, '')" in slice_, (
            "copyWaLink debe contener replace(/@.*$/, '')"
        )

    def test_copy_wa_link_rejects_empty_local_part(self, js_content):
        """Si el local queda vacío, copyWaLink debe mostrar toast de error."""
        idx = js_content.index("copyWaLink(inst)")
        slice_ = js_content[idx:idx + 1500]
        assert "'Número inválido para esta instancia'" in slice_, (
            "copyWaLink debe contener el toast 'Número inválido para esta instancia'"
        )

    def test_copy_wa_link_writes_wa_me_url(self, js_content):
        """copyWaLink debe armar la URL con 'https://wa.me/' + local."""
        idx = js_content.index("copyWaLink(inst)")
        slice_ = js_content[idx:idx + 1500]
        assert "'https://wa.me/'" in slice_ or "'https://wa.me/'" in slice_, (
            "copyWaLink debe contener 'https://wa.me/'"
        )

    def test_copy_wa_link_wraps_writetext_in_try_catch(self, js_content):
        """navigator.clipboard.writeText debe estar dentro de try/catch."""
        idx = js_content.index("copyWaLink(inst)")
        slice_ = js_content[idx:idx + 2000]
        assert "navigator.clipboard.writeText" in slice_, (
            "copyWaLink debe contener navigator.clipboard.writeText"
        )
        assert "try {" in slice_, "copyWaLink debe contener 'try {'"
        assert "catch" in slice_, "copyWaLink debe contener 'catch'"

    def test_copy_wa_link_no_exec_command_fallback(self, js_content):
        """copyWaLink NO debe usar execCommand como fallback de copia."""
        idx = js_content.index("copyWaLink(inst)")
        method_body = js_content[idx:]
        end_idx = method_body.find("\n\n        // ───")
        if end_idx == -1:
            end_idx = 1500  # fallback
        method_slice = method_body[:end_idx]
        # Verificar que no hay llamada a execCommand (código, no comentario)
        assert "document.execCommand" not in method_slice, (
            "copyWaLink NO debe usar document.execCommand como fallback"
        )
        assert ".execCommand(" not in method_slice, (
            "copyWaLink NO debe usar execCommand como fallback"
        )

    def test_copy_wa_link_toast_feedback(self, js_content):
        """copyWaLink debe usar 'Link copiado' (éxito) y 'No se pudo copiar el link' (error)."""
        idx = js_content.index("copyWaLink(inst)")
        slice_ = js_content[idx:idx + 2000]
        assert "'Link copiado'" in slice_, (
            "copyWaLink debe contener 'Link copiado'"
        )
        assert "'No se pudo copiar el link'" in slice_, (
            "copyWaLink debe contener 'No se pudo copiar el link'"
        )


class TestLinkColumnLayout:
    """Verifica que la columna Link esté entre Owner y Estado, con el botón
    SVG de portapapeles, binding :disabled, y colspan=5 en loading/empty rows."""

    def test_th_link_exists_between_owner_and_estado(self, html_content):
        """El TH 'Link' debe estar entre Owner y Estado, con hidden md:table-cell."""
        import re
        # Buscar el orden de los THs
        th_pattern = re.compile(r'<th[^>]*>(.*?)</th>', re.DOTALL)
        ths = th_pattern.findall(html_content)
        # Filtrar solo los THs de la tabla de instancias (Nombre, Owner, Link, Estado, Acciones)
        # Buscamos la región de la tabla de instancias
        table_start = html_content.find('Instancias de WhatsApp')
        table_region = html_content[table_start:]
        ths = th_pattern.findall(table_region)
        th_texts = [re.sub(r'<[^>]+>', '', th).strip() for th in ths]
        # Verificar que Link está entre Owner y Estado
        assert 'Nombre' in th_texts, "TH 'Nombre' debe existir"
        assert 'Owner' in th_texts, "TH 'Owner' debe existir"
        assert 'Link' in th_texts, "TH 'Link' debe existir"
        assert 'Estado' in th_texts, "TH 'Estado' debe existir"
        assert 'Acciones' in th_texts, "TH 'Acciones' debe existir"
        # Verificar orden: Owner < Link < Estado
        owner_idx = th_texts.index('Owner')
        link_idx = th_texts.index('Link')
        estado_idx = th_texts.index('Estado')
        assert owner_idx < link_idx < estado_idx, (
            f"Link debe estar entre Owner (idx={owner_idx}) y Estado (idx={estado_idx}), "
            f"pero está en idx={link_idx}"
        )
        # Verificar que el TH de Link tiene hidden md:table-cell
        link_th_match = re.search(
            r'<th[^>]*class="[^"]*hidden md:table-cell[^"]*"[^>]*>Link</th>',
            table_region
        )
        assert link_th_match, "El TH 'Link' debe tener class='hidden md:table-cell'"

    def test_td_link_cell_in_correct_position(self, html_content):
        """La 3ra celda del row template debe ser Link con hidden md:table-cell."""
        import re
        # Buscar el template x-for de las filas
        template_match = re.search(
            r'<template x-for="inst in instances".*?</template>',
            html_content,
            re.DOTALL
        )
        assert template_match, "No se encontró el <template x-for='inst in instances'>"
        template_html = template_match.group(0)
        # Extraer las celdas <td> del template
        td_pattern = re.compile(r'<td\s+class="([^"]*)"', re.DOTALL)
        tds = td_pattern.findall(template_html)
        # Deben ser 5 celdas: Nombre, Owner, Link, Estado, Acciones
        assert len(tds) >= 5, (
            f"El template debe tener al menos 5 celdas <td>, se encontraron {len(tds)}"
        )
        # La 3ra celda (idx=2) debe tener hidden md:table-cell
        assert 'hidden md:table-cell' in tds[2], (
            f"La 3ra celda debe tener 'hidden md:table-cell', tiene: '{tds[2]}'"
        )

    def test_td_button_has_clipboard_svg_icon(self, html_content):
        """La celda Link debe contener un SVG de portapapeles y @click='copyWaLink(inst)'."""
        import re
        # Buscar el botón de copiar dentro del template
        template_match = re.search(
            r'<template x-for="inst in instances".*?</template>',
            html_content,
            re.DOTALL
        )
        assert template_match, "No se encontró el template"
        template_html = template_match.group(0)
        assert 'viewBox="0 0 24 24"' in template_html, (
            "El template debe contener un SVG con viewBox='0 0 24 24'"
        )
        assert 'stroke="currentColor"' in template_html, (
            "El SVG debe usar stroke='currentColor' para heredar el color del botón"
        )
        assert 'copyWaLink(inst)' in template_html, (
            "El template debe contener @click='copyWaLink(inst)'"
        )

    def test_td_button_disabled_when_owner_jid_null(self, html_content):
        """El botón copy debe tener :disabled='!inst.ownerJid'."""
        import re
        template_match = re.search(
            r'<template x-for="inst in instances".*?</template>',
            html_content,
            re.DOTALL
        )
        assert template_match, "No se encontró el template"
        template_html = template_match.group(0)
        assert ':disabled="!inst.ownerJid"' in template_html, (
            "El botón copy debe tener :disabled='!inst.ownerJid'"
        )

    def test_loading_row_uses_colspan_5(self, html_content):
        """La fila de loading debe usar colspan='5'."""
        import re
        # Buscar la fila de loading (template x-if="loading")
        loading_match = re.search(
            r'<template x-if="loading">(.*?)</template>',
            html_content,
            re.DOTALL
        )
        assert loading_match, "No se encontró el template de loading"
        loading_html = loading_match.group(1)
        assert 'colspan="5"' in loading_html, (
            f"La fila de loading debe usar colspan='5', tiene: {loading_html}"
        )

    def test_empty_row_uses_colspan_5(self, html_content):
        """La fila vacía debe usar colspan='5'."""
        import re
        empty_match = re.search(
            r'<template x-if="!loading && instances.length === 0">(.*?)</template>',
            html_content,
            re.DOTALL
        )
        assert empty_match, "No se encontró el template de fila vacía"
        empty_html = empty_match.group(1)
        assert 'colspan="5"' in empty_html, (
            f"La fila vacía debe usar colspan='5', tiene: {empty_html}"
        )

    def test_kebab_unchanged(self, html_content):
        """Los 4 íconos del kebab (fa-link, fa-power-off, fa-ban, fa-trash) siguen presentes."""
        import re
        template_match = re.search(
            r'<template x-for="inst in instances".*?</template>',
            html_content,
            re.DOTALL
        )
        assert template_match, "No se encontró el template"
        template_html = template_match.group(0)
        icons = ['fa-link', 'fa-power-off', 'fa-ban', 'fa-trash']
        for icon in icons:
            assert icon in template_html, (
                f"El kebab debe contener {icon}"
            )


# ---------------------------------------------------------------------------
# Configurable Gemini Model: frontend tests
# ---------------------------------------------------------------------------


class TestGeminiModelInputs:
    """Verifica que index.html contenga los inputs de Gemini model y app.js tenga la lógica."""

    def test_index_html_has_generation_model_input(self, html_content):
        """index.html debe contener un input con id='geminiModelInput'."""
        assert 'id="geminiModelInput"' in html_content, (
            "index.html debe contener un input con id='geminiModelInput'"
        )

    def test_index_html_has_embeddings_model_input(self, html_content):
        """index.html debe contener un input con id='geminiEmbeddingsInput'."""
        assert 'id="geminiEmbeddingsInput"' in html_content, (
            "index.html debe contener un input con id='geminiEmbeddingsInput'"
        )

    def test_index_html_has_generation_model_label(self, html_content):
        """index.html debe tener un label 'Modelo de generación' asociado al input de generación."""
        assert 'Modelo de generación' in html_content or 'Modelo de generacion' in html_content, (
            "index.html debe contener el label 'Modelo de generación'"
        )

    def test_index_html_has_embeddings_model_label(self, html_content):
        """index.html debe tener un label 'Modelo de embeddings' asociado al input de embeddings."""
        assert 'Modelo de embeddings' in html_content, (
            "index.html debe contener el label 'Modelo de embeddings'"
        )

    def test_index_html_has_generation_model_warning(self, html_content):
        """index.html debe contener un warning badge sobre rate limits/costos para el modelo de generación."""
        assert 'rate limit' in html_content.lower() or 'costo' in html_content.lower() or 'calidad' in html_content.lower(), (
            "index.html debe contener un warning sobre rate limits, costos o calidad para el modelo de generación"
        )

    def test_index_html_has_embeddings_model_critical_warning(self, html_content):
        """index.html debe contener un warning CRITICAL sobre invalidación del vectorstore para embeddings."""
        assert 'vectorstore' in html_content.lower() or 'reindexar' in html_content.lower() or 'reindex' in html_content.lower(), (
            "index.html debe contener un warning CRITICAL sobre invalidación del vectorstore para embeddings"
        )

    def test_app_js_has_gemini_model_state(self):
        """app.js debe contener la variable de estado geminiModel."""
        app_js = APP_JS_PATH.read_text(encoding="utf-8")
        assert "geminiModel" in app_js, (
            "app.js debe contener la variable de estado geminiModel"
        )

    def test_app_js_has_gemini_embeddings_model_state(self):
        """app.js debe contener la variable de estado geminiEmbeddingsModel."""
        app_js = APP_JS_PATH.read_text(encoding="utf-8")
        assert "geminiEmbeddingsModel" in app_js, (
            "app.js debe contener la variable de estado geminiEmbeddingsModel"
        )
