import pytest

from whatsapp_client import WhatsAppClient
from exceptions import CommunicationError
from error_codes import ErrorCode


# Default instance name usado en la mayoria de los tests. En PR 3
# paso a ser kwarg, no atributo del cliente.
DEFAULT_INSTANCE = "instancia-test"
ALT_INSTANCE = "otra-instancia"


@pytest.fixture
def client():
    """Cliente sin `instance_name` en el ctor (post-PR-3)."""
    return WhatsAppClient(
        api_url="https://evolution.api",
        api_key="test-key-123",
    )


class TestInit:
    def test_headers_include_api_key(self):
        client = WhatsAppClient("https://url", "mi-key")
        assert client.headers["apikey"] == "mi-key"
        assert client.headers["Content-Type"] == "application/json"

    def test_url_stored(self):
        client = WhatsAppClient("https://url", "k")
        assert client.api_url == "https://url"

    def test_no_instance_name_attribute_after_init(self):
        """Post-PR-3: el ctor NO recibe instance_name ni lo guarda como atributo.

        El nombre se pasa por llamada, no por instancia. Si alguien
        intenta `client.instance_name` antes de llamar a un metodo,
        obtiene AttributeError (vs. el viejo string vacio o el valor
        del ctor).
        """
        client = WhatsAppClient("https://url", "k")
        assert not hasattr(client, "instance_name"), (
            "BUG: WhatsAppClient ctor deberia NO guardar instance_name. "
            "Si lo guardas, alguien podria olvidarse de pasar el kwarg "
            "y la URL se armaria con un valor stale."
        )


class TestEnviarMensaje:

    @pytest.mark.asyncio
    async def test_exitoso_retorna_json(self, mocker, client):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"key": {"id": "wa123"}}
        mocker.patch.object(client._client, "request", return_value=mock_resp)

        result = await client.enviar_mensaje("54911", "Hola", instance_name=DEFAULT_INSTANCE)

        assert result == {"key": {"id": "wa123"}}
        mock_resp.json.assert_called_once()

    @pytest.mark.asyncio
    async def test_201_tambien_exitoso(self, mocker, client):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"key": {"id": "wa456"}}
        mocker.patch.object(client._client, "request", return_value=mock_resp)

        result = await client.enviar_mensaje("54911", "Hola", instance_name=DEFAULT_INSTANCE)

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
            await client.enviar_mensaje("54911", "Hola", instance_name=DEFAULT_INSTANCE)

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
            await client.enviar_mensaje("54911", "Hola", instance_name=DEFAULT_INSTANCE)

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
            await client.enviar_mensaje("54911", "Hola", instance_name=DEFAULT_INSTANCE)

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
            await client.enviar_mensaje("54911", "Hola", instance_name=DEFAULT_INSTANCE)

        assert exc_info.value.code == ErrorCode.COM_CONNECTION_FAILED

    @pytest.mark.asyncio
    async def test_envia_payload_correcto(self, mocker, client):
        """URL se arma con el instance_name del kwarg, no de self.

        Test explicito del PR 3: el nombre viene por llamada, asi
        dos llamadas consecutivas con nombres distintos pegan a
        URLs distintas (hot-swap sin rebuild del cliente).
        """
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_request = mocker.patch.object(client._client, "request", return_value=mock_resp)

        await client.enviar_mensaje("5491123456789", "texto de prueba", instance_name=DEFAULT_INSTANCE)

        expected_url = f"https://evolution.api/message/sendText/{DEFAULT_INSTANCE}"
        expected_payload = {
            "number": "5491123456789",
            "text": "texto de prueba",
            "delay": 2500,
        }
        mock_request.assert_called_once_with(
            "POST", expected_url, json=expected_payload, headers=client.headers
        )

    @pytest.mark.asyncio
    async def test_per_call_instance_name_routes_correctly(self, mocker, client):
        """Dos llamadas, dos instance_name distintos -> dos URLs distintas.

        Es el caso de uso central del PR 3: el MISMO cliente sirve
        para A y B. La diferencia es el kwarg. Sin rebuild, sin pool.
        """
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_request = mocker.patch.object(client._client, "request", return_value=mock_resp)

        await client.enviar_mensaje("54911", "primero", instance_name=DEFAULT_INSTANCE)
        await client.enviar_mensaje("54911", "segundo", instance_name=ALT_INSTANCE)

        # Verificamos las URLs en orden
        assert mock_request.call_count == 2
        first_url = mock_request.call_args_list[0][0][1]
        second_url = mock_request.call_args_list[1][0][1]
        assert first_url == f"https://evolution.api/message/sendText/{DEFAULT_INSTANCE}"
        assert second_url == f"https://evolution.api/message/sendText/{ALT_INSTANCE}"

    @pytest.mark.asyncio
    async def test_requiere_instance_name_kwarg(self, mocker, client):
        """Olvidarse del kwarg debe ser TypeError explicito, no un valor vacio en la URL.

        El kwarg es keyword-only y sin default. Si alguien llama
        `enviar_mensaje("54911", "hola")` se queja Python con
        TypeError, en vez de armar silenciosamente una URL malformada.
        """
        with pytest.raises(TypeError) as exc_info:
            await client.enviar_mensaje("54911", "hola")
        # El mensaje de error menciona el kwarg faltante
        assert "instance_name" in str(exc_info.value)


class TestConnectionPooling:

    @pytest.mark.asyncio
    async def test_same_client_reused_across_calls(self, mocker, client):
        """REQ-7: Multiple requests share the same AsyncClient instance."""
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"key": {"id": "wa123"}}
        mock_request = mocker.patch.object(client._client, "request", return_value=mock_resp)

        await client.enviar_mensaje("54911", "Hola 1", instance_name=DEFAULT_INSTANCE)
        await client.enviar_mensaje("54911", "Hola 2", instance_name=DEFAULT_INSTANCE)

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

        result = await client.obtener_audio_base64({"key": {"id": "msg1"}}, instance_name=DEFAULT_INSTANCE)

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
            await client.obtener_audio_base64({"key": {"id": "msg1"}}, instance_name=DEFAULT_INSTANCE)

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
            await client.obtener_audio_base64({"key": {"id": "msg1"}}, instance_name=DEFAULT_INSTANCE)

        assert exc_info.value.code == ErrorCode.COM_CONNECTION_FAILED

    @pytest.mark.asyncio
    async def test_response_sin_base64_retorna_none(self, mocker, client):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mocker.patch.object(client._client, "request", return_value=mock_resp)

        result = await client.obtener_audio_base64({"key": {"id": "msg1"}}, instance_name=DEFAULT_INSTANCE)

        assert result is None

    @pytest.mark.asyncio
    async def test_envia_payload_correcto(self, mocker, client):
        """URL del audio se arma con el instance_name del kwarg."""
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"base64": "data"}
        mock_request = mocker.patch.object(client._client, "request", return_value=mock_resp)

        mensaje_data = {"key": {"id": "abc123"}}
        await client.obtener_audio_base64(mensaje_data, instance_name=DEFAULT_INSTANCE)

        expected_url = f"https://evolution.api/chat/getBase64FromMediaMessage/{DEFAULT_INSTANCE}"
        expected_payload = {"message": mensaje_data}
        mock_request.assert_called_once_with(
            "POST", expected_url, json=expected_payload, headers=client.headers
        )

    @pytest.mark.asyncio
    async def test_requiere_instance_name_kwarg(self, mocker, client):
        """Igual que enviar_mensaje: el kwarg es keyword-only y obligatorio."""
        with pytest.raises(TypeError) as exc_info:
            await client.obtener_audio_base64({"key": {"id": "msg1"}})
        assert "instance_name" in str(exc_info.value)


# ─── enviar_documento Tests (Task 4.1) ────────────────────────────────

class TestEnviarDocumento:

    @pytest.mark.asyncio
    async def test_successful_send_returns_json(self, mocker, client):
        """enviar_documento returns JSON on 200."""
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"key": {"id": "doc123"}}
        mocker.patch.object(client._client, "request", return_value=mock_resp)

        result = await client.enviar_documento("5491112345678", b"PDF_BYTES", "reporte.pdf", instance_name=DEFAULT_INSTANCE)

        assert result == {"key": {"id": "doc123"}}

    @pytest.mark.asyncio
    async def test_201_tambien_exitoso(self, mocker, client):
        """enviar_documento returns JSON on 201."""
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"key": {"id": "doc456"}}
        mocker.patch.object(client._client, "request", return_value=mock_resp)

        result = await client.enviar_documento("5491112345678", b"PDF_BYTES", "reporte.pdf", instance_name=DEFAULT_INSTANCE)

        assert result == {"key": {"id": "doc456"}}

    @pytest.mark.asyncio
    async def test_sends_correct_url(self, mocker, client):
        """URL must include sendMedia and instance_name."""
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_request = mocker.patch.object(client._client, "request", return_value=mock_resp)

        await client.enviar_documento("5491112345678", b"PDF_BYTES", "reporte.pdf", instance_name=DEFAULT_INSTANCE)

        expected_url = f"https://evolution.api/message/sendMedia/{DEFAULT_INSTANCE}"
        call_args = mock_request.call_args
        assert call_args[0][1] == expected_url

    @pytest.mark.asyncio
    async def test_sends_base64_payload(self, mocker, client):
        """Payload must use Evolution API v2 format: mediatype (lowercase),
        mimetype required, media as data URI."""
        import base64
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_request = mocker.patch.object(client._client, "request", return_value=mock_resp)

        pdf_bytes = b"%PDF-1.4 test content"
        await client.enviar_documento("5491112345678", pdf_bytes, "reporte.pdf", instance_name=DEFAULT_INSTANCE)

        json_payload = mock_request.call_args[1]["json"]
        # Evolution API v2 usa lowercase "mediatype", no "mediaType"
        assert json_payload["mediatype"] == "document"
        # mimetype es obligatorio en Evolution API v2
        assert json_payload["mimetype"] == "application/pdf"
        assert json_payload["fileName"] == "reporte.pdf"
        assert json_payload["number"] == "5491112345678"
        # media debe ser data URI, no base64 crudo
        expected_b64 = base64.b64encode(pdf_bytes).decode()
        assert json_payload["media"] == expected_b64

    @pytest.mark.asyncio
    async def test_400_raises_communication_error(self, mocker, client):
        """Evolution API 400 must raise CommunicationError with COM_SEND_DOCUMENT_FAILED."""
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"
        # enviar_documento uses the post() method on _client, not request()
        mocker.patch.object(client._client, "request", return_value=mock_resp)

        with pytest.raises(CommunicationError) as exc_info:
            await client.enviar_documento("5491112345678", b"PDF_BYTES", "reporte.pdf", instance_name=DEFAULT_INSTANCE)

        assert exc_info.value.code == ErrorCode.COM_SEND_DOCUMENT_FAILED

    @pytest.mark.asyncio
    async def test_connection_error_raises_communication_error(self, mocker, client):
        """Network error must raise CommunicationError with COM_CONNECTION_FAILED."""
        import httpx
        mocker.patch.object(
            client._client,
            "request",
            side_effect=httpx.ConnectError("DNS failure"),
        )

        with pytest.raises(CommunicationError) as exc_info:
            await client.enviar_documento("5491112345678", b"PDF_BYTES", "reporte.pdf", instance_name=DEFAULT_INSTANCE)

        assert exc_info.value.code == ErrorCode.COM_CONNECTION_FAILED

    @pytest.mark.asyncio
    async def test_per_call_instance_name_routes_correctly(self, mocker, client):
        """Two calls with different instance names -> two different URLs."""
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_request = mocker.patch.object(client._client, "request", return_value=mock_resp)

        await client.enviar_documento("54911", b"PDF1", "r1.pdf", instance_name=DEFAULT_INSTANCE)
        await client.enviar_documento("54911", b"PDF2", "r2.pdf", instance_name=ALT_INSTANCE)

        assert mock_request.call_count == 2
        first_url = mock_request.call_args_list[0][0][1]
        second_url = mock_request.call_args_list[1][0][1]
        assert first_url == f"https://evolution.api/message/sendMedia/{DEFAULT_INSTANCE}"
        assert second_url == f"https://evolution.api/message/sendMedia/{ALT_INSTANCE}"

    @pytest.mark.asyncio
    async def test_requiere_instance_name_kwarg(self, mocker, client):
        """enviar_documento must require instance_name as keyword-only arg."""
        with pytest.raises(TypeError) as exc_info:
            await client.enviar_documento("54911", b"PDF", "r.pdf")
        assert "instance_name" in str(exc_info.value)
