"""Unit tests for `evolution_http.EvolutionHTTP`.

Mockeamos al nivel del `IdleTimeoutClient.request` (el patron que ya usa
`test_whatsapp_client.py`): asi probamos la logica de URL/headers/error
mapping sin hacer I/O real.
"""

import httpx
import pytest

from evolution_http import EvolutionHTTP
from error_codes import ErrorCode
from exceptions import CommunicationError


@pytest.fixture
def client():
    return EvolutionHTTP(api_url="https://evo.example.com", api_key="k-123")


class TestUrlBuild:
    def test_basic_join(self, client):
        assert client._build_url("instance/fetchInstances") == (
            "https://evo.example.com/instance/fetchInstances"
        )

    def test_api_url_with_trailing_slash_is_normalized(self):
        c = EvolutionHTTP(api_url="https://evo.example.com/", api_key="k")
        assert c._build_url("instance/fetchInstances") == (
            "https://evo.example.com/instance/fetchInstances"
        )

    def test_path_with_leading_slash_is_normalized(self, client):
        assert client._build_url("/instance/fetchInstances") == (
            "https://evo.example.com/instance/fetchInstances"
        )

    def test_both_slashes_do_not_produce_double_slash(self, client):
        url = client._build_url("/instance/fetchInstances/")
        # El design permite trailing slash en el path (Evolution lo acepta);
        # el contrato es que NO haya '//' en el medio.
        assert "//" not in url.replace("https://", "")


class TestHeaders:
    def test_apikey_is_injected(self, client):
        assert client._headers()["apikey"] == "k-123"

    def test_content_type_is_json(self, client):
        assert client._headers()["Content-Type"] == "application/json"


class TestGet:
    async def test_2xx_returns_response(self, mocker, client):
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"instances": []}
        resp.content = b"{}"
        mocker.patch.object(client._client, "request", return_value=resp)

        out = await client.get("instance/fetchInstances")
        assert out is resp
        # Verifica que la URL y el metodo se armaron bien.
        args, kwargs = client._client.request.call_args
        assert args[0] == "GET"
        assert args[1] == "https://evo.example.com/instance/fetchInstances"
        assert kwargs["headers"]["apikey"] == "k-123"

    async def test_404_raises_communication_error_with_status_code(
        self, mocker, client
    ):
        resp = mocker.MagicMock()
        resp.status_code = 404
        resp.text = '{"error": "Instance not found"}'
        mocker.patch.object(client._client, "request", return_value=resp)

        with pytest.raises(CommunicationError) as exc:
            await client.get("instance/connect/bot_X")
        assert exc.value.code == ErrorCode.COM_SEND_MESSAGE_FAILED
        assert exc.value.status_code == 404
        assert "not found" in (exc.value.response_body or "")

    async def test_500_raises_communication_error_with_status_code(
        self, mocker, client
    ):
        resp = mocker.MagicMock()
        resp.status_code = 500
        resp.text = "internal"
        mocker.patch.object(client._client, "request", return_value=resp)

        with pytest.raises(CommunicationError) as exc:
            await client.get("instance/connectionState/x")
        assert exc.value.status_code == 500


class TestPost:
    async def test_transport_error_raises_connection_failed(self, mocker, client):
        mocker.patch.object(
            client._client,
            "request",
            side_effect=httpx.ConnectError("DNS failure"),
        )
        with pytest.raises(CommunicationError) as exc:
            await client.post("instance/create", json={"name": "x"})
        assert exc.value.code == ErrorCode.COM_CONNECTION_FAILED
        assert exc.value.status_code is None  # no HTTP response -> no status_code

    async def test_post_sends_json_body(self, mocker, client):
        resp = mocker.MagicMock()
        resp.status_code = 201
        resp.json.return_value = {"instance": {"instanceName": "x"}}
        resp.content = b"{}"
        mock_request = mocker.patch.object(
            client._client, "request", return_value=resp
        )
        await client.post("instance/create", json={"name": "x"})
        args, kwargs = mock_request.call_args
        assert args[0] == "POST"
        assert args[1] == "https://evo.example.com/instance/create"
        assert kwargs["json"] == {"name": "x"}
        assert kwargs["headers"]["apikey"] == "k-123"


class TestDelete:
    async def test_delete_sends_correct_method_and_path(self, mocker, client):
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.text = ""
        resp.content = b""
        mock_request = mocker.patch.object(
            client._client, "request", return_value=resp
        )
        await client.delete("instance/delete/bot_2")
        args, kwargs = mock_request.call_args
        assert args[0] == "DELETE"
        assert args[1] == "https://evo.example.com/instance/delete/bot_2"
        # DELETE no lleva body, pero la API key + content-type van igual
        # (Evolution los ignora en DELETE pero el header sigue siendo
        # consistente con GET/POST).
        assert kwargs["headers"]["apikey"] == "k-123"

    async def test_delete_404_raises_communication_error(self, mocker, client):
        resp = mocker.MagicMock()
        resp.status_code = 404
        resp.text = "instance not found"
        mocker.patch.object(client._client, "request", return_value=resp)
        with pytest.raises(CommunicationError) as exc:
            await client.delete("instance/delete/nope")
        assert exc.value.status_code == 404

    async def test_delete_transport_error_raises_connection_failed(self, mocker, client):
        mocker.patch.object(
            client._client,
            "request",
            side_effect=httpx.ConnectError("DNS failure"),
        )
        with pytest.raises(CommunicationError) as exc:
            await client.delete("instance/delete/bot_2")
        assert exc.value.code == ErrorCode.COM_CONNECTION_FAILED
        assert exc.value.status_code is None


class TestAclose:
    async def test_aclose_calls_underlying_client(self, mocker, client):
        mock_aclose = mocker.patch.object(client._client, "aclose")
        await client.aclose()
        mock_aclose.assert_awaited_once()
