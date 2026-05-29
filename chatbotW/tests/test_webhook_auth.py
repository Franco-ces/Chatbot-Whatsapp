"""Tests de autenticación del webhook: secret header verification.

Cubre los escenarios del spec:
- Secret válido → 200
- Header faltante → 401 + E-API-004
- Secret incorrecto → 401 + E-API-004
- Secret vacío → 200 (backward-compatible)
"""
import sys
import pytest
from unittest.mock import MagicMock, patch
import httpx

# Mockear módulos que solo existen en Docker antes de importar main
for mod in ["price_lookup"]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

# Payload válido para todos los tests
VALID_PAYLOAD = {
    "event": "messages.upsert",
    "data": {
        "key": {
            "remoteJid": "5491123456789@s.whatsapp.net",
            "fromMe": False,
            "id": "msg-auth-001",
        },
        "message": {"conversation": "Hola"},
        "pushName": "TestUser",
    },
}

TEST_SECRET = "test-secret-abc123"


class TestWebhookAuth:
    """Tests de verificación de secret en el webhook."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        """Mock logger y dedup antes de cada test."""
        import main
        self.original_logger = main.logger
        self.original_dedup = main.mensajes_procesados.copy()
        main.logger = MagicMock()
        main.mensajes_procesados.clear()
        yield
        main.logger = self.original_logger
        main.mensajes_procesados.clear()
        main.mensajes_procesados.update(self.original_dedup)

    @pytest.mark.asyncio
    async def test_valid_secret_returns_ok(self):
        """Secret correcto → request proceede → 200."""
        from main import app

        with patch.dict("os.environ", {"WEBHOOK_SECRET": TEST_SECRET}), \
             patch("main.rag", MagicMock()), \
             patch("main.wa_client", MagicMock()), \
             patch("main.session_manager", MagicMock()), \
             patch("main.usuario_excedido", return_value=False):

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/webhook",
                    json=VALID_PAYLOAD,
                    headers={"X-Webhook-Secret": TEST_SECRET},
                )

            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_missing_header_returns_401(self):
        """Header faltante → 401 con E-API-004."""
        from main import app

        with patch.dict("os.environ", {"WEBHOOK_SECRET": TEST_SECRET}):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/webhook", json=VALID_PAYLOAD)

            assert resp.status_code == 401
            body = resp.json()
            assert body["error"]["code"] == "E-API-004"
            assert body["error"]["message"] == "Acceso no autorizado."

    @pytest.mark.asyncio
    async def test_wrong_secret_returns_401(self):
        """Secret incorrecto → 401 con E-API-004."""
        from main import app

        with patch.dict("os.environ", {"WEBHOOK_SECRET": TEST_SECRET}):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/webhook",
                    json=VALID_PAYLOAD,
                    headers={"X-Webhook-Secret": "wrong-secret-value"},
                )

            assert resp.status_code == 401
            body = resp.json()
            assert body["error"]["code"] == "E-API-004"

    @pytest.mark.asyncio
    async def test_empty_secret_skips_verification(self):
        """Secret vacío → sin verificación → 200 (backward-compatible)."""
        from main import app

        with patch.dict("os.environ", {"WEBHOOK_SECRET": ""}), \
             patch("main.rag", MagicMock()), \
             patch("main.wa_client", MagicMock()), \
             patch("main.session_manager", MagicMock()), \
             patch("main.usuario_excedido", return_value=False):

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Sin header, secret vacío → debe pasar
                resp = await client.post("/webhook", json=VALID_PAYLOAD)

            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
