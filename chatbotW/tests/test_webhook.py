import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from payload_parser import EvolutionWebhook, WebhookData, MessageKey


def _make_watcher_stub(instance_name="bot_test"):
    """Stub del InstanceWatcher para tests de webhook.

    PR 3: el webhook resuelve el instance_name activo via
    `instance_watcher.get_active_name()`. Los tests parchean
    `main.instance_watcher` con este stub para que el resolution
    devuelva un nombre (sin esto, el webhook cae al branch
    "no_active_instance" y devuelve un status distinto de "ok").
    """
    stub = MagicMock()
    stub.get_active_name.return_value = instance_name
    return stub


def _make_payload(text="Hola", from_me=False, event="messages.upsert"):
    """Construye un payload EvolutionWebhook válido."""
    return EvolutionWebhook(
        event=event,
        data=WebhookData(
            key=MessageKey(
                remoteJid="5491123456789@s.whatsapp.net",
                fromMe=from_me,
                id="msg-001",
            ),
            message={"conversation": text},
            pushName="TestUser",
        ),
    )


class TestWebhookInstanceField:
    """Tests para el campo 'instance' en EvolutionWebhook (Task 1.1)."""

    def test_evolution_webhook_accepts_instance_field(self):
        """REQ: Payload con 'instance' se parsea correctamente."""
        payload = EvolutionWebhook(
            event="messages.upsert",
            data=WebhookData(
                key=MessageKey(
                    remoteJid="5491123456789@s.whatsapp.net",
                    fromMe=False,
                    id="msg-001",
                ),
                message={"conversation": "Hola"},
                pushName="TestUser",
            ),
            instance="bot_2",
        )
        assert payload.instance == "bot_2"

    def test_evolution_webhook_instance_defaults_to_none(self):
        """REQ: Sin campo 'instance', el valor es None."""
        payload = _make_payload()
        assert payload.instance is None


class TestWebhookInstanceRouting:
    """Tests para que el webhook use payload.instance como instance_name (Task 1.3)."""

    @pytest.fixture(autouse=True)
    def _mock_logger(self):
        """Asegura que main.logger no sea None durante los tests."""
        import main
        original_logger = main.logger
        original_dedup = main.mensajes_procesados.copy()
        main.logger = MagicMock()
        main.mensajes_procesados.clear()
        yield
        main.logger = original_logger
        main.mensajes_procesados.clear()
        main.mensajes_procesados.update(original_dedup)

    @pytest.mark.asyncio
    async def test_webhook_uses_payload_instance_when_present(self):
        """REQ: Si el payload trae 'instance', se usa como instance_name
        en vez del valor del watcher."""
        from main import app
        import httpx

        mock_wa = MagicMock()
        mock_wa.enviar_mensaje = AsyncMock()
        mock_session = MagicMock()
        mock_procesar = AsyncMock()

        with patch.dict("os.environ", {"WEBHOOK_SECRET": ""}, clear=False), \
             patch("main.rag", MagicMock()), \
             patch("main.wa_client", mock_wa), \
             patch("main.session_manager", mock_session), \
             patch("main.instance_watcher", _make_watcher_stub("watcher_instance")), \
             patch("main.usuario_excedido", return_value=False), \
             patch("main.procesar_mensaje_bot", mock_procesar):

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/webhook", json={
                    "event": "messages.upsert",
                    "data": {
                        "key": {
                            "remoteJid": "5491123456789@s.whatsapp.net",
                            "fromMe": False,
                            "id": "msg-100",
                        },
                        "message": {"conversation": "Hola"},
                        "pushName": "TestUser",
                    },
                    "instance": "bot_2",
                })

            assert resp.status_code == 200
            # procesar_mensaje_bot fue llamado (via create_task) con instance_name="bot_2"
            mock_procesar.assert_called_once()
            _, kwargs = mock_procesar.call_args
            assert kwargs["instance_name"] == "bot_2", \
                f"Esperaba instance_name='bot_2', obtuve '{kwargs['instance_name']}'"

    @pytest.mark.asyncio
    async def test_webhook_instance_fallback_to_watcher(self):
        """REQ: Sin campo 'instance' en el payload, usa _resolve_instance_name()."""
        from main import app
        import httpx

        mock_wa = MagicMock()
        mock_wa.enviar_mensaje = AsyncMock()
        mock_session = MagicMock()
        mock_procesar = AsyncMock()

        with patch.dict("os.environ", {"WEBHOOK_SECRET": ""}, clear=False), \
             patch("main.rag", MagicMock()), \
             patch("main.wa_client", mock_wa), \
             patch("main.session_manager", mock_session), \
             patch("main.instance_watcher", _make_watcher_stub("watcher_fallback")), \
             patch("main.usuario_excedido", return_value=False), \
             patch("main.procesar_mensaje_bot", mock_procesar):

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                # Sin campo "instance" en el payload
                resp = await client.post("/webhook", json={
                    "event": "messages.upsert",
                    "data": {
                        "key": {
                            "remoteJid": "5491123456789@s.whatsapp.net",
                            "fromMe": False,
                            "id": "msg-200",
                        },
                        "message": {"conversation": "Hola"},
                        "pushName": "TestUser",
                    },
                })

            assert resp.status_code == 200
            mock_procesar.assert_called_once()
            _, kwargs = mock_procesar.call_args
            assert kwargs["instance_name"] == "watcher_fallback", \
                f"Esperaba instance_name='watcher_fallback', obtuve '{kwargs['instance_name']}'"

    @pytest.mark.asyncio
    async def test_webhook_no_instance_returns_error(self):
        """REQ: Sin instance en payload Y watcher devuelve '', retorna no_active_instance."""
        from main import app
        import httpx

        mock_wa = MagicMock()
        mock_wa.enviar_mensaje = AsyncMock()

        with patch.dict("os.environ", {"WEBHOOK_SECRET": "", "EVOLUTION_INSTANCE_NAME": ""}, clear=False), \
             patch("main.rag", MagicMock()), \
             patch("main.wa_client", mock_wa), \
             patch("main.session_manager", MagicMock()), \
             patch("main.instance_watcher", _make_watcher_stub("")), \
             patch("main.usuario_excedido", return_value=False):

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/webhook", json={
                    "event": "messages.upsert",
                    "data": {
                        "key": {
                            "remoteJid": "5491123456789@s.whatsapp.net",
                            "fromMe": False,
                            "id": "msg-300",
                        },
                        "message": {"conversation": "Hola"},
                        "pushName": "TestUser",
                    },
                })

            assert resp.status_code == 200
            assert resp.json() == {"status": "no_active_instance"}
            # No se intentó enviar mensaje
            mock_wa.enviar_mensaje.assert_not_called()


class TestWebhookValidPayload:

    @pytest.fixture(autouse=True)
    def _mock_logger(self):
        """Asegura que main.logger no sea None durante los tests."""
        import main
        original_logger = main.logger
        original_dedup = main.mensajes_procesados.copy()
        main.logger = MagicMock()
        main.mensajes_procesados.clear()
        yield
        main.logger = original_logger
        main.mensajes_procesados.clear()
        main.mensajes_procesados.update(original_dedup)

    @pytest.mark.asyncio
    async def test_returns_ok_and_spawns_task(self):
        """REQ-6: Payload válido → retorna ok, lanza tarea en background."""
        from main import app
        import httpx

        mock_rag = MagicMock()
        mock_rag.preguntar = AsyncMock(return_value=("hi", "Hello!"))
        mock_wa = MagicMock()
        mock_wa.enviar_mensaje = AsyncMock()
        mock_wa.obtener_audio_base64 = AsyncMock()
        mock_session = MagicMock()

        with patch.dict("os.environ", {"WEBHOOK_SECRET": ""}, clear=False), \
             patch("main.rag", mock_rag), \
             patch("main.wa_client", mock_wa), \
             patch("main.session_manager", mock_session), \
             patch("main.instance_watcher", _make_watcher_stub()), \
             patch("main.usuario_excedido", return_value=False):

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/webhook", json={
                    "event": "messages.upsert",
                    "data": {
                        "key": {
                            "remoteJid": "5491123456789@s.whatsapp.net",
                            "fromMe": False,
                            "id": "msg-001",
                        },
                        "message": {"conversation": "Hola"},
                        "pushName": "TestUser",
                    },
                })

            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_returns_ok_for_empty_payload(self):
        """REQ-6: Payload vacío/inválido → retorna ok, no lanza tarea."""
        from main import app
        import httpx

        with patch.dict("os.environ", {"WEBHOOK_SECRET": ""}, clear=False), \
             patch("main.rag", MagicMock()), \
             patch("main.wa_client", MagicMock()), \
             patch("main.session_manager", MagicMock()):

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                # fromMe=True hace que extraer_datos_limpios devuelva None
                resp = await client.post("/webhook", json={
                    "event": "messages.upsert",
                    "data": {
                        "key": {
                            "remoteJid": "5491123456789@s.whatsapp.net",
                            "fromMe": True,
                            "id": "msg-001",
                        },
                        "message": {"conversation": "Hola"},
                        "pushName": "TestUser",
                    },
                })

            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_rate_limited_sender(self):
        """REQ-6: Remitente con rate-limit → retorna rate_limited."""
        from main import app
        import httpx

        mock_wa = MagicMock()
        mock_wa.enviar_mensaje = AsyncMock()

        with patch.dict("os.environ", {"WEBHOOK_SECRET": ""}, clear=False), \
             patch("main.rag", MagicMock()), \
             patch("main.wa_client", mock_wa), \
             patch("main.session_manager", MagicMock()), \
             patch("main.instance_watcher", _make_watcher_stub()), \
             patch("main.usuario_excedido", return_value=True):

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/webhook", json={
                    "event": "messages.upsert",
                    "data": {
                        "key": {
                            "remoteJid": "5491123456789@s.whatsapp.net",
                            "fromMe": False,
                            "id": "msg-001",
                        },
                        "message": {"conversation": "Hola"},
                        "pushName": "TestUser",
                    },
                })

            assert resp.status_code == 200
            assert resp.json() == {"status": "rate_limited"}
            # El rate-limit path ahora tambien recibe instance_name kwarg
            _, kwargs = mock_wa.enviar_mensaje.call_args
            assert kwargs.get("instance_name") == "bot_test"
            mock_wa.enviar_mensaje.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_uses_create_task_not_background_tasks(self):
        """REQ-6: El webhook usa asyncio.create_task, no BackgroundTasks."""
        import inspect
        from main import webhook

        # Verificar que la firma del webhook no incluya BackgroundTasks
        sig = inspect.signature(webhook)
        assert "background_tasks" not in sig.parameters
        assert "BackgroundTasks" not in str(sig)
