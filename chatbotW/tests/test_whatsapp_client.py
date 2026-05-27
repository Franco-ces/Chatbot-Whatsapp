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

    def test_exitoso_retorna_json(self, mocker, client):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"key": {"id": "wa123"}}
        mocker.patch("whatsapp_client.requests.post", return_value=mock_resp)

        result = client.enviar_mensaje("54911", "Hola")

        assert result == {"key": {"id": "wa123"}}
        mock_resp.json.assert_called_once()

    def test_201_tambien_exitoso(self, mocker, client):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"key": {"id": "wa456"}}
        mocker.patch("whatsapp_client.requests.post", return_value=mock_resp)

        result = client.enviar_mensaje("54911", "Hola")

        assert result == {"key": {"id": "wa456"}}

    def test_http_error_400_lanza_communication_error(self, mocker, client):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"
        mocker.patch("whatsapp_client.requests.post", return_value=mock_resp)

        with pytest.raises(CommunicationError) as exc_info:
            client.enviar_mensaje("54911", "Hola")

        assert exc_info.value.code == ErrorCode.COM_SEND_MESSAGE_FAILED

    def test_http_error_500_lanza_communication_error(self, mocker, client):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Error"
        mocker.patch("whatsapp_client.requests.post", return_value=mock_resp)

        with pytest.raises(CommunicationError) as exc_info:
            client.enviar_mensaje("54911", "Hola")

        assert exc_info.value.code == ErrorCode.COM_SEND_MESSAGE_FAILED

    def test_connection_error_lanza_communication_error(self, mocker, client):
        from requests.exceptions import ConnectionError as ReqConnectionError

        mocker.patch(
            "whatsapp_client.requests.post",
            side_effect=ReqConnectionError("DNS failure"),
        )

        with pytest.raises(CommunicationError) as exc_info:
            client.enviar_mensaje("54911", "Hola")

        assert exc_info.value.code == ErrorCode.COM_CONNECTION_FAILED

    def test_timeout_lanza_communication_error(self, mocker, client):
        from requests.exceptions import Timeout

        mocker.patch(
            "whatsapp_client.requests.post",
            side_effect=Timeout("timed out"),
        )

        with pytest.raises(CommunicationError) as exc_info:
            client.enviar_mensaje("54911", "Hola")

        assert exc_info.value.code == ErrorCode.COM_CONNECTION_FAILED

    def test_envia_payload_correcto(self, mocker, client):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_post = mocker.patch("whatsapp_client.requests.post", return_value=mock_resp)

        client.enviar_mensaje("5491123456789", "texto de prueba")

        expected_url = "https://evolution.api/message/sendText/instancia-test"
        expected_payload = {
            "number": "5491123456789",
            "text": "texto de prueba",
            "delay": 2500,
        }
        mock_post.assert_called_once_with(
            expected_url, json=expected_payload, headers=client.headers
        )


class TestObtenerAudioBase64:

    def test_exitoso_retorna_base64(self, mocker, client):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"base64": "YXVkaW8="}
        mocker.patch("whatsapp_client.requests.post", return_value=mock_resp)

        result = client.obtener_audio_base64({"key": {"id": "msg1"}})

        assert result == "YXVkaW8="

    def test_http_error_lanza_communication_error(self, mocker, client):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mocker.patch("whatsapp_client.requests.post", return_value=mock_resp)

        with pytest.raises(CommunicationError) as exc_info:
            client.obtener_audio_base64({"key": {"id": "msg1"}})

        assert exc_info.value.code == ErrorCode.COM_GET_AUDIO_FAILED

    def test_connection_error_lanza_communication_error(self, mocker, client):
        from requests.exceptions import ConnectionError as ReqConnectionError

        mocker.patch(
            "whatsapp_client.requests.post",
            side_effect=ReqConnectionError("connection refused"),
        )

        with pytest.raises(CommunicationError) as exc_info:
            client.obtener_audio_base64({"key": {"id": "msg1"}})

        assert exc_info.value.code == ErrorCode.COM_CONNECTION_FAILED

    def test_response_sin_base64_retorna_none(self, mocker, client):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mocker.patch("whatsapp_client.requests.post", return_value=mock_resp)

        result = client.obtener_audio_base64({"key": {"id": "msg1"}})

        assert result is None

    def test_envia_payload_correcto(self, mocker, client):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"base64": "data"}
        mock_post = mocker.patch("whatsapp_client.requests.post", return_value=mock_resp)

        mensaje_data = {"key": {"id": "abc123"}}
        client.obtener_audio_base64(mensaje_data)

        expected_url = "https://evolution.api/chat/getBase64FromMediaMessage/instancia-test"
        expected_payload = {"message": mensaje_data}
        mock_post.assert_called_once_with(
            expected_url, json=expected_payload, headers=client.headers
        )
