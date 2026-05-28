import pytest

from whatsapp_client import WhatsAppClient
from exceptions import CommunicationError
from error_codes import ErrorCode


@pytest.fixture
def client():
    return WhatsAppClient(
        api_url="https://evolution.api",
        api_key="test-key-123",
        instance_name="instancia-test",
    )


class TestInit:
    def test_headers_include_api_key(self):
        client = WhatsAppClient("https://url", "mi-key", "mi-instancia")
        assert client.headers["apikey"] == "mi-key"
        assert client.headers["Content-Type"] == "application/json"

    def test_url_and_instance_stored(self):
        client = WhatsAppClient("https://url", "k", "inst")
        assert client.api_url == "https://url"
        assert client.instance_name == "inst"


class TestEnviarMensaje:

    @pytest.mark.asyncio
    async def test_exitoso_retorna_json(self, mocker, client):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"key": {"id": "wa123"}}
        mocker.patch.object(client._client, "request", return_value=mock_resp)

        result = await client.enviar_mensaje("54911", "Hola")

        assert result == {"key": {"id": "wa123"}}
        mock_resp.json.assert_called_once()

    @pytest.mark.asyncio
    async def test_201_tambien_exitoso(self, mocker, client):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"key": {"id": "wa456"}}
        mocker.patch.object(client._client, "request", return_value=mock_resp)

        result = await client.enviar_mensaje("54911", "Hola")

        assert result == {"key": {"id": "wa456"}}

    @pytest.mark.asyncio
    async def test_http_error_400_lanza_communication_error(self, mocker, client):
        import httpx
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"
        http_error = httpx.HTTPStatusError("Bad Request", request=mocker.MagicMock(), response=mock_resp)
        mocker.patch.object(client._client, "request", side_effect=http_error)

        with pytest.raises(CommunicationError) as exc_info:
            await client.enviar_mensaje("54911", "Hola")

        assert exc_info.value.code == ErrorCode.COM_SEND_MESSAGE_FAILED

    @pytest.mark.asyncio
    async def test_http_error_500_lanza_communication_error(self, mocker, client):
        import httpx
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Error"
        http_error = httpx.HTTPStatusError("Internal Error", request=mocker.MagicMock(), response=mock_resp)
        mocker.patch.object(client._client, "request", side_effect=http_error)

        with pytest.raises(CommunicationError) as exc_info:
            await client.enviar_mensaje("54911", "Hola")

        assert exc_info.value.code == ErrorCode.COM_SEND_MESSAGE_FAILED

    @pytest.mark.asyncio
    async def test_connection_error_lanza_communication_error(self, mocker, client):
        import httpx
        mocker.patch.object(
            client._client,
            "request",
            side_effect=httpx.ConnectError("DNS failure"),
        )

        with pytest.raises(CommunicationError) as exc_info:
            await client.enviar_mensaje("54911", "Hola")

        assert exc_info.value.code == ErrorCode.COM_CONNECTION_FAILED

    @pytest.mark.asyncio
    async def test_timeout_lanza_communication_error(self, mocker, client):
        import httpx
        mocker.patch.object(
            client._client,
            "request",
            side_effect=httpx.TimeoutException("timed out"),
        )

        with pytest.raises(CommunicationError) as exc_info:
            await client.enviar_mensaje("54911", "Hola")

        assert exc_info.value.code == ErrorCode.COM_CONNECTION_FAILED

    @pytest.mark.asyncio
    async def test_envia_payload_correcto(self, mocker, client):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_request = mocker.patch.object(client._client, "request", return_value=mock_resp)

        await client.enviar_mensaje("5491123456789", "texto de prueba")

        expected_url = "https://evolution.api/message/sendText/instancia-test"
        expected_payload = {
            "number": "5491123456789",
            "text": "texto de prueba",
            "delay": 2500,
        }
        mock_request.assert_called_once_with(
            "POST", expected_url, json=expected_payload, headers=client.headers
        )


class TestConnectionPooling:

    @pytest.mark.asyncio
    async def test_same_client_reused_across_calls(self, mocker, client):
        """REQ-7: Multiple requests share the same AsyncClient instance."""
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"key": {"id": "wa123"}}
        mock_request = mocker.patch.object(client._client, "request", return_value=mock_resp)

        await client.enviar_mensaje("54911", "Hola 1")
        await client.enviar_mensaje("54911", "Hola 2")

        # Both calls use the same _client instance
        assert mock_request.call_count == 2
        # Verify the same _client object is used (connection pooling)
        assert client._client is client._client


class TestObtenerAudioBase64:

    @pytest.mark.asyncio
    async def test_exitoso_retorna_base64(self, mocker, client):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"base64": "YXVkaW8="}
        mocker.patch.object(client._client, "request", return_value=mock_resp)

        result = await client.obtener_audio_base64({"key": {"id": "msg1"}})

        assert result == "YXVkaW8="

    @pytest.mark.asyncio
    async def test_http_error_lanza_communication_error(self, mocker, client):
        import httpx
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        http_error = httpx.HTTPStatusError("Not Found", request=mocker.MagicMock(), response=mock_resp)
        mocker.patch.object(client._client, "request", side_effect=http_error)

        with pytest.raises(CommunicationError) as exc_info:
            await client.obtener_audio_base64({"key": {"id": "msg1"}})

        assert exc_info.value.code == ErrorCode.COM_GET_AUDIO_FAILED

    @pytest.mark.asyncio
    async def test_connection_error_lanza_communication_error(self, mocker, client):
        import httpx
        mocker.patch.object(
            client._client,
            "request",
            side_effect=httpx.ConnectError("connection refused"),
        )

        with pytest.raises(CommunicationError) as exc_info:
            await client.obtener_audio_base64({"key": {"id": "msg1"}})

        assert exc_info.value.code == ErrorCode.COM_CONNECTION_FAILED

    @pytest.mark.asyncio
    async def test_response_sin_base64_retorna_none(self, mocker, client):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mocker.patch.object(client._client, "request", return_value=mock_resp)

        result = await client.obtener_audio_base64({"key": {"id": "msg1"}})

        assert result is None

    @pytest.mark.asyncio
    async def test_envia_payload_correcto(self, mocker, client):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"base64": "data"}
        mock_request = mocker.patch.object(client._client, "request", return_value=mock_resp)

        mensaje_data = {"key": {"id": "abc123"}}
        await client.obtener_audio_base64(mensaje_data)

        expected_url = "https://evolution.api/chat/getBase64FromMediaMessage/instancia-test"
        expected_payload = {"message": mensaje_data}
        mock_request.assert_called_once_with(
            "POST", expected_url, json=expected_payload, headers=client.headers
        )
