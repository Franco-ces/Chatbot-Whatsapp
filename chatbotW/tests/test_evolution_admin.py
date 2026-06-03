"""Unit tests for `evolution_admin.EvolutionAdmin`.

Mockeamos al nivel del transport (`evolution_http.EvolutionHTTP.get/post`)
para que cada test ejercite admin + http juntos con respuestas controladas.
"""

import httpx
import pytest

from evolution_admin import EvolutionAdmin
from evolution_http import EvolutionHTTP
from evolution_models import (
    ConnectionState,
    InstanceInfo,
    QRPayload,
    WebhookConfig,
)
from error_codes import ErrorCode
from exceptions import APIError, CommunicationError, ConfigError  # noqa: F401  (referenced for type checks)


@pytest.fixture
def admin():
    http = EvolutionHTTP(api_url="https://evo.example.com", api_key="k")
    return EvolutionAdmin(http)


def _mock_get(mocker, http: EvolutionHTTP, status: int, json_body):
    """Helper: mockea una respuesta GET 2xx o no-2xx."""
    resp = mocker.MagicMock()
    resp.status_code = status
    resp.json.return_value = json_body
    resp.text = str(json_body)
    resp.content = b"{}" if status >= 200 else b""
    mocker.patch.object(http._client, "request", return_value=resp)


def _mock_post(mocker, http: EvolutionHTTP, status: int, json_body):
    resp = mocker.MagicMock()
    resp.status_code = status
    resp.json.return_value = json_body
    resp.text = str(json_body)
    resp.content = b"{}" if status >= 200 else b""
    mocker.patch.object(http._client, "request", return_value=resp)


class TestListInstances:
    async def test_returns_list_of_instance_info(self, mocker, admin):
        _mock_get(
            mocker,
            admin._http,
            200,
            [
                {"name": "a", "connectionState": "open"},
                {"name": "b", "connectionState": "close"},
            ],
        )
        out = await admin.list_instances()
        assert len(out) == 2
        assert out[0].name == "a"
        assert out[0].connection_state == ConnectionState.OPEN
        assert out[1].connection_state == ConnectionState.CLOSE

    async def test_handles_object_wrapped_response(self, mocker, admin):
        """Algunas versiones de Evolution envuelven la lista en {instances: [...]}."""
        _mock_get(mocker, admin._http, 200, {"instances": [{"name": "x", "connectionState": "close"}]})
        out = await admin.list_instances()
        assert len(out) == 1
        assert out[0].name == "x"

    async def test_empty_list(self, mocker, admin):
        _mock_get(mocker, admin._http, 200, [])
        out = await admin.list_instances()
        assert out == []

    async def test_accepts_evolution_v2_connectionStatus(self, mocker, admin):
        """Regression: la respuesta REAL de Evolution v2.x usa
        `connectionStatus` (no `connectionState`). Sin el fix, este test
        falla con ValidationError -> 500 en /api/evolution/instances ->
        la lista nunca aparece en el panel admin."""
        payload = [
            {
                "id": "125e683d-8a73-4034-9257-bd5e7ab8fa6a",
                "name": "bot_2",
                "connectionStatus": "close",
                "ownerJid": None,
                "integration": "WHATSAPP-BAILEYS",
            },
            {
                "id": "45a21adf-e50f-460f-b19e-ae332ae3dba6",
                "name": "rag_bot",
                "connectionStatus": "open",
                "ownerJid": "5492494210126@s.whatsapp.net",
                "profileName": "NeuraDocs",
                "integration": "WHATSAPP-BAILEYS",
            },
        ]
        _mock_get(mocker, admin._http, 200, payload)
        out = await admin.list_instances()
        assert len(out) == 2
        assert out[0].connection_state == ConnectionState.CLOSE
        assert out[1].connection_state == ConnectionState.OPEN
        # Y el dump para el frontend debe seguir siendo camelCase.
        dumped = out[1].model_dump(by_alias=True, exclude_none=True)
        assert dumped["connectionState"] == "open"
        assert "connectionStatus" not in dumped


class TestCreateInstance:
    async def test_returns_parsed_instance_info(self, mocker, admin):
        body = {
            "instance": {
                "instanceName": "bot_1",
                "status": "close",
                "integration": "WHATSAPP-BAILEYS",
            }
        }
        _mock_post(mocker, admin._http, 201, body)
        out = await admin.create_instance("bot_1")
        assert isinstance(out, InstanceInfo)
        assert out.name == "bot_1"
        assert out.connection_state == ConnectionState.CLOSE
        assert out.integration == "WHATSAPP-BAILEYS"

    async def test_send_correct_payload(self, mocker, admin):
        _mock_post(mocker, admin._http, 201, {"instance": {"instanceName": "x", "status": "close"}})
        await admin.create_instance("x")
        args, kwargs = admin._http._client.request.call_args
        assert args[0] == "POST"
        assert args[1].endswith("/instance/create")
        assert kwargs["json"] == {
            "instanceName": "x",
            "integration": "WHATSAPP-BAILEYS",
        }


class TestGetQr:
    async def test_returns_qr_payload(self, mocker, admin):
        _mock_get(
            mocker,
            admin._http,
            200,
            {"base64": "AAAA", "state": "close", "instance": "bot_1"},
        )
        out = await admin.get_qr("bot_1")
        assert isinstance(out, QRPayload)
        assert out.base64 == "AAAA"
        assert out.state == ConnectionState.CLOSE
        assert out.instance == "bot_1"

    async def test_already_open_returns_state_from_nested_instance(self, mocker, admin):
        """Regression: cuando la instancia YA esta vinculada (`open`),
        Evolution v2.x NO devuelve `base64` en el raiz; en su lugar
        envuelve todo en `{"instance": {"instanceName": ..., "state":
        "open"}}`. Si no leemos `instance.state` desde adentro, el
        panel reporta `state="close"` para siempre y el boton "Activar"
        nunca se desbloquea, aunque el operador ya haya escaneado el
        QR."""
        _mock_get(
            mocker,
            admin._http,
            200,
            {"instance": {"instanceName": "rag_bot", "state": "open"}},
        )
        out = await admin.get_qr("rag_bot")
        assert out.state == ConnectionState.OPEN
        assert out.base64 == ""  # No hay QR que escanear, OK.


class TestGetState:
    async def test_returns_connection_state_enum(self, mocker, admin):
        _mock_get(mocker, admin._http, 200, {"state": "open"})
        out = await admin.get_state("bot_1")
        assert out == ConnectionState.OPEN

    async def test_handles_nested_state_field(self, mocker, admin):
        """Evolution a veces devuelve {instance: {state: ...}}."""
        _mock_get(mocker, admin._http, 200, {"instance": {"state": "connecting"}})
        out = await admin.get_state("x")
        assert out == ConnectionState.CONNECTING


class TestDeleteInstance:
    async def test_calls_delete_with_correct_path(self, mocker, admin):
        """Debe llamar DELETE /instance/delete/{name} (sin body)."""
        from unittest.mock import AsyncMock
        mock_delete = AsyncMock(return_value=mocker.MagicMock(status_code=200, text=""))
        mocker.patch.object(admin._http, "delete", new=mock_delete)
        await admin.delete_instance("bot_2")
        mock_delete.assert_awaited_once_with("instance/delete/bot_2")

    async def test_404_from_evolution_maps_to_api_not_found(self, mocker, admin):
        from error_codes import ErrorCode
        from exceptions import APIError
        from exceptions import CommunicationError

        comm = CommunicationError(
            ErrorCode.COM_SEND_MESSAGE_FAILED,
            detail="not found",
            status_code=404,
            response_body="not found",
        )
        mocker.patch.object(admin._http, "delete", side_effect=comm)
        with pytest.raises(APIError) as exc:
            await admin.delete_instance("missing")
        assert exc.value.code == ErrorCode.API_NOT_FOUND

    async def test_5xx_from_evolution_maps_to_api_server_error(self, mocker, admin):
        from error_codes import ErrorCode
        from exceptions import APIError
        from exceptions import CommunicationError

        comm = CommunicationError(
            ErrorCode.COM_SEND_MESSAGE_FAILED,
            detail="boom",
            status_code=500,
            response_body="boom",
        )
        mocker.patch.object(admin._http, "delete", side_effect=comm)
        with pytest.raises(APIError) as exc:
            await admin.delete_instance("bot_2")
        assert exc.value.code == ErrorCode.API_SERVER_ERROR


class TestSetWebhook:
    async def test_sends_url_and_secret_header(self, mocker, admin):
        """Evolution API v2.3.7 espera `webhook` como OBJETO anidado con
        `url`, `events`, `enabled`, `headers`, `base64` adentro. El formato
        v2.1 (webhook como string) devuelve 400 'webhook is not of a type
        object'. Test protege contra una regresion al formato viejo."""
        _mock_post(mocker, admin._http, 200, {"webhook": "ok"})
        cfg = WebhookConfig(
            url="https://bot.example.com",
            headers={"X-Webhook-Secret": "s3cr3t"},
        )
        await admin.set_webhook("bot_1", cfg)
        args, kwargs = admin._http._client.request.call_args
        assert args[0] == "POST"
        assert args[1].endswith("/webhook/set/bot_1")
        body = kwargs["json"]
        # Formato v2.3.7: `webhook` es un objeto anidado, no un string.
        # Si alguien vuelve al formato viejo (string), este assert explota.
        assert isinstance(body["webhook"], dict)
        wh = body["webhook"]
        assert wh["url"] == "https://bot.example.com"
        assert wh["headers"]["X-Webhook-Secret"] == "s3cr3t"
        assert "MESSAGES_UPSERT" in wh["events"]
        assert wh["enabled"] is True
        assert wh["base64"] is False


class TestDisableWebhook:
    async def test_disable_webhook_success(self, mocker, admin):
        """disable_webhook llama al endpoint con enabled=False."""
        from unittest.mock import AsyncMock

        mock_webhook = WebhookConfig(
            url="https://bot.example.com",
            headers={"X-Webhook-Secret": "s3cr3t"},
        )
        admin.get_webhook = AsyncMock(return_value=mock_webhook)
        _mock_post(mocker, admin._http, 200, {"webhook": "ok"})

        await admin.disable_webhook("bot_1")

        admin.get_webhook.assert_awaited_once_with("bot_1")
        args, kwargs = admin._http._client.request.call_args
        assert args[0] == "POST"
        assert args[1].endswith("/webhook/set/bot_1")
        body = kwargs["json"]
        assert body["webhook"]["enabled"] is False
        assert body["webhook"]["url"] == "https://bot.example.com"
        assert body["webhook"]["headers"] == {"X-Webhook-Secret": "s3cr3t"}

    async def test_disable_webhook_handles_not_found_gracefully(self, mocker, admin):
        """Si get_webhook devuelve NOT_FOUND (instancia sin webhook),
        disable_webhook igual setea enabled=False como no-op seguro."""
        from unittest.mock import AsyncMock

        admin.get_webhook = AsyncMock(
            side_effect=APIError(ErrorCode.API_NOT_FOUND, detail="Instance not found")
        )
        mock_set = AsyncMock()
        admin.set_webhook = mock_set

        # No debe lanzar excepcion
        await admin.disable_webhook("missing")

        # Llama set_webhook con enabled=False
        mock_set.assert_awaited_once()
        config_arg = mock_set.call_args[0][1]  # segundo positional arg es WebhookConfig
        assert config_arg.enabled is False

    async def test_disable_webhook_propagates_other_errors(self, mocker, admin):
        """disable_webhook propaga errores que NO son NOT_FOUND."""
        from unittest.mock import AsyncMock

        admin.get_webhook = AsyncMock(
            side_effect=APIError(ErrorCode.API_SERVER_ERROR, detail="Server error")
        )

        with pytest.raises(APIError) as exc:
            await admin.disable_webhook("broken")
        assert exc.value.code == ErrorCode.API_SERVER_ERROR


class TestErrorMapping:
    async def test_404_raises_api_not_found(self, mocker, admin):
        resp = mocker.MagicMock()
        resp.status_code = 404
        resp.text = "not found"
        mocker.patch.object(admin._http._client, "request", return_value=resp)
        with pytest.raises(APIError) as exc:
            await admin.get_state("nope")
        assert exc.value.code == ErrorCode.API_NOT_FOUND
        assert exc.value.code.http_status == 404

    async def test_400_raises_api_invalid_payload(self, mocker, admin):
        resp = mocker.MagicMock()
        resp.status_code = 400
        resp.text = "bad name"
        mocker.patch.object(admin._http._client, "request", return_value=resp)
        with pytest.raises(APIError) as exc:
            await admin.create_instance("??")
        assert exc.value.code == ErrorCode.API_INVALID_PAYLOAD

    async def test_500_raises_api_server_error(self, mocker, admin):
        resp = mocker.MagicMock()
        resp.status_code = 500
        resp.text = "boom"
        mocker.patch.object(admin._http._client, "request", return_value=resp)
        with pytest.raises(APIError) as exc:
            await admin.list_instances()
        assert exc.value.code == ErrorCode.API_SERVER_ERROR

    async def test_transport_error_propagates_as_communication_error(
        self, mocker, admin
    ):
        """Sin status_code (transporte puro), el CommunicationError original
        se re-lanza sin envolver: el caller decide como manejarlo."""
        mocker.patch.object(
            admin._http._client,
            "request",
            side_effect=httpx.ConnectError("DNS"),
        )
        with pytest.raises(CommunicationError) as exc:
            await admin.list_instances()
        assert exc.value.code == ErrorCode.COM_CONNECTION_FAILED
        assert exc.value.status_code is None
