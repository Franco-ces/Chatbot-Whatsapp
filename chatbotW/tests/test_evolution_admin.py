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


class TestSetWebhook:
    async def test_sends_url_and_secret_header(self, mocker, admin):
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
        assert body["webhook"] == "https://bot.example.com"
        assert body["headers"]["X-Webhook-Secret"] == "s3cr3t"
        assert "MESSAGES_UPSERT" in body["events"]


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
