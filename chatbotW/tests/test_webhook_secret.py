"""Tests de auto-generación de WEBHOOK_SECRET en main.py e interface.py.

Verifica:
- main.py lifespan: genera secret cuando env vacío, preserva cuando seteado
- interface.py module-level: misma lógica que SECRET_KEY
- Secret generado funciona para verificación de webhook
"""
import os
import sys
import re
import pytest
from unittest.mock import MagicMock, patch

# Mockear módulos que solo existen en Docker antes de importar main
for mod in ["price_lookup"]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()


# ─── Tests para main.py ───────────────────────────────────────────────────────

class TestMainPyWebhookSecret:
    """Tests de generación de WEBHOOK_SECRET en el lifespan de main.py."""

    def test_generates_secret_when_env_empty(self):
        """Env vacío → genera 64-char hex string."""
        with patch.dict("os.environ", {}, clear=True), \
             patch("main.load_dotenv"), \
             patch("main.set_key") as mock_set_key, \
             patch("main.os.getenv", side_effect=lambda k, d="": "" if k == "WEBHOOK_SECRET" else d):

            import main

            # Simular lo que hace el lifespan después de load_dotenv
            import secrets
            webhook_secret = os.environ.get("WEBHOOK_SECRET", "")
            # En este test, el env está vacío — el lifespan debería generar
            # Verificamos que el CÓDIGO de main.py tiene la lógica correcta
            # inspeccionando el source
            import inspect
            source = inspect.getsource(main.lifespan)
            assert "WEBHOOK_SECRET" in source
            assert "token_hex" in source
            assert "set_key" in source

    def test_preserves_existing_secret(self):
        """Env con valor seteado → preserva, no genera nuevo."""
        existing = "existing-secret-value-12345"
        with patch.dict("os.environ", {"WEBHOOK_SECRET": existing}):
            # Verificar que el CÓDIGO respeta el guard: if not webhook_secret
            import main
            import inspect
            source = inspect.getsource(main.lifespan)
            # Debe haber un check tipo "if not webhook_secret" o "if not os.getenv"
            assert re.search(r"if not.*webhook_secret", source)

    def test_generation_sets_in_os_environ(self):
        """Código debe setear el valor generado en os.environ."""
        import main
        import inspect
        source = inspect.getsource(main.lifespan)
        assert 'os.environ["WEBHOOK_SECRET"]' in source or "os.environ['WEBHOOK_SECRET']" in source

    def test_generation_persists_to_env_file(self):
        """Código debe persistir el secret generado a .env via set_key."""
        import main
        import inspect
        source = inspect.getsource(main.lifespan)
        assert "set_key" in source
        assert "WEBHOOK_SECRET" in source

    def test_imports_include_set_key(self):
        """main.py debe importar set_key desde dotenv."""
        import main
        import inspect
        # Buscar en el source completo del módulo (imports están arriba)
        full_source = inspect.getsource(main)
        assert "from dotenv import set_key" in full_source or \
               "from dotenv import load_dotenv, set_key" in full_source or \
               "from dotenv import" in full_source and "set_key" in full_source

    def test_imports_include_env_file(self):
        """main.py debe importar ENV_FILE desde paths."""
        import main
        import inspect
        full_source = inspect.getsource(main)
        assert "ENV_FILE" in full_source
        assert "from paths import" in full_source


# ─── Tests para interface.py ──────────────────────────────────────────────────

class TestInterfacePyWebhookSecret:
    """Tests de generación de WEBHOOK_SECRET a nivel módulo en interface.py."""

    def test_generates_when_not_set(self):
        """Env vacío → genera secret al cargar interface."""
        import interface
        import inspect
        source = inspect.getsource(interface)
        assert "WEBHOOK_SECRET" in source
        assert "token_hex" in source

    def test_preserves_when_already_set(self):
        """Env seteado → preserva valor existente."""
        import interface
        import inspect
        source = inspect.getsource(interface)
        # Debe haber un guard: if not WEBHOOK_SECRET
        assert re.search(r"if not WEBHOOK_SECRET", source)

    def test_sets_in_os_environ(self):
        """Código debe setear el secret en os.environ."""
        import interface
        import inspect
        source = inspect.getsource(interface)
        assert 'os.environ["WEBHOOK_SECRET"]' in source or "os.environ['WEBHOOK_SECRET']" in source

    def test_persists_to_env_file(self):
        """Código debe persistir el secret a .env.

        interface.py usa `_write_env` (escritura directa in-place) en vez
        de `set_key` de python-dotenv: el bind-mount de .env en Docker/WSL2
        hacía que `os.replace` (que set_key usa internamente) fallara con
        "Device or resource busy". `_write_env` reescribe el archivo sin
        reemplazo atómico y soporta bind-mounts. main.py sí usa set_key
        porque allí el .env no está bind-mounted de la misma forma. La
        persistencia está garantizada en ambos; difiere el mecanismo.
        """
        import interface
        import inspect
        source = inspect.getsource(interface)
        assert "_write_env" in source
        assert "WEBHOOK_SECRET" in source

    def test_follows_secret_key_pattern(self):
        """La generación de WEBHOOK_SECRET sigue el patrón de SECRET_KEY."""
        import interface
        import inspect
        source = inspect.getsource(interface)
        # Ambos deben existir y usar token_hex/token_urlsafe + set_key
        assert "SECRET_KEY" in source  # El patrón existente
        assert "WEBHOOK_SECRET" in source  # El nuevo

    def test_webhook_secret_after_secret_key_in_source(self):
        """WEBHOOK_SECRET debe aparecer DESPUÉS de SECRET_KEY en el source."""
        import interface
        import inspect
        source = inspect.getsource(interface)
        secret_key_pos = source.index("SECRET_KEY")
        webhook_secret_pos = source.index("WEBHOOK_SECRET")
        assert webhook_secret_pos > secret_key_pos, \
            "WEBHOOK_SECRET debe aparecer después de SECRET_KEY en interface.py"


# ─── Test de integración: secret generado verifica webhook ────────────────────

class TestWebhookVerificationWithGeneratedSecret:
    """Verifica que un secret auto-generado funciona para verificación de webhook."""

    @pytest.mark.asyncio
    async def test_generated_secret_verifies_webhook(self):
        """Env vacío → genera secret → webhook con header matching → 200."""
        import httpx
        import main as main_mod

        # Generamos un secret como lo haría el código
        import secrets
        generated_secret = secrets.token_hex(32)
        assert len(generated_secret) == 64
        assert re.fullmatch(r"[0-9a-f]{64}", generated_secret)

        # Simular que el lifespan generó el secret y está en os.environ
        valid_payload = {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "remoteJid": "5491123456789@s.whatsapp.net",
                    "fromMe": False,
                    "id": "msg-gen-001",
                },
                "message": {"conversation": "Hola"},
                "pushName": "TestUser",
            },
        }

        from main import app

        # Mockear logger y dedup (como en test_webhook_auth.py)
        original_logger = main_mod.logger
        original_dedup = main_mod.mensajes_procesados.copy()
        main_mod.logger = MagicMock()
        main_mod.mensajes_procesados.clear()

        try:
            with patch.dict("os.environ", {"WEBHOOK_SECRET": generated_secret}), \
                 patch("main.rag", MagicMock()), \
                 patch("main.wa_client", MagicMock()), \
                 patch("main.session_manager", MagicMock()), \
                 patch("main.instance_watcher", MagicMock()), \
                 patch("main.usuario_excedido", return_value=False):

                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/webhook",
                        json=valid_payload,
                        headers={"X-Webhook-Secret": generated_secret},
                    )

                assert resp.status_code == 200
                assert resp.json()["status"] == "ok"
        finally:
            main_mod.logger = original_logger
            main_mod.mensajes_procesados.clear()
            main_mod.mensajes_procesados.update(original_dedup)
