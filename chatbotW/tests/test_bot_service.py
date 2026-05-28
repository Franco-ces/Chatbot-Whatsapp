import pytest
from unittest.mock import AsyncMock

from bot_service import procesar_mensaje_bot, _notificar_error
from exceptions import AppError, CommunicationError, RAGError
from error_codes import ErrorCode


@pytest.fixture
def wa_client():
    client = AsyncMock()
    client.enviar_mensaje = AsyncMock()
    client.obtener_audio_base64 = AsyncMock()
    return client


@pytest.fixture
def rag_instance():
    rag = AsyncMock()
    rag.preguntar = AsyncMock()
    return rag


REMITTENTE = "5491123456789"
TEXTO = "consulta de prueba"
MENSAJE_DATA = {"key": {"id": "123"}}
RESPUESTA_OK = "Esta es la respuesta del bot."


class TestProcesarMensajeExitoso:

    @pytest.mark.asyncio
    async def test_envia_respuesta_sin_audio(self, wa_client, rag_instance):
        rag_instance.preguntar.return_value = ("transcripcion", RESPUESTA_OK)
        await procesar_mensaje_bot(rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=False)
        rag_instance.preguntar.assert_called_once_with(
            query_text=TEXTO, audio_bytes=None, remitente=REMITTENTE
        )
        wa_client.enviar_mensaje.assert_called_once_with(REMITTENTE, RESPUESTA_OK)

    @pytest.mark.asyncio
    async def test_envia_respuesta_con_audio(self, wa_client, rag_instance):
        wa_client.obtener_audio_base64.return_value = "YXVkaW8="
        rag_instance.preguntar.return_value = ("transcripcion", RESPUESTA_OK)
        await procesar_mensaje_bot(rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=True)
        wa_client.obtener_audio_base64.assert_called_once_with(MENSAJE_DATA)
        rag_instance.preguntar.assert_called_once()
        kwargs = rag_instance.preguntar.call_args.kwargs
        assert kwargs["audio_bytes"] == b"audio"  # base64 decoded "YXVkaW8="
        wa_client.enviar_mensaje.assert_called_once_with(REMITTENTE, RESPUESTA_OK)

    @pytest.mark.asyncio
    async def test_no_envia_mensaje_de_error(self, wa_client, rag_instance):
        rag_instance.preguntar.return_value = ("", RESPUESTA_OK)
        await procesar_mensaje_bot(rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=False)
        call_text = wa_client.enviar_mensaje.call_args[0][1]
        assert "E-" not in call_text


class TestErroresEnRAG:

    @pytest.mark.asyncio
    async def test_communication_error_notifica_error(self, wa_client, rag_instance):
        rag_instance.preguntar.side_effect = CommunicationError(ErrorCode.COM_CONNECTION_FAILED)
        await procesar_mensaje_bot(rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=False)
        wa_client.enviar_mensaje.assert_called_once()
        call_text = wa_client.enviar_mensaje.call_args[0][1]
        assert ErrorCode.COM_CONNECTION_FAILED.value in call_text

    @pytest.mark.asyncio
    async def test_rag_error_notifica_error(self, wa_client, rag_instance):
        rag_instance.preguntar.side_effect = RAGError(ErrorCode.RAG_QUERY_FAILED)
        await procesar_mensaje_bot(rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=False)
        wa_client.enviar_mensaje.assert_called_once()
        call_text = wa_client.enviar_mensaje.call_args[0][1]
        assert ErrorCode.RAG_QUERY_FAILED.value in call_text

    @pytest.mark.asyncio
    async def test_exception_inesperada_notifica_sys_error(self, wa_client, rag_instance):
        rag_instance.preguntar.side_effect = RuntimeError("algo salio mal")
        await procesar_mensaje_bot(rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=False)
        wa_client.enviar_mensaje.assert_called_once()
        call_text = wa_client.enviar_mensaje.call_args[0][1]
        assert ErrorCode.SYS_UNEXPECTED.value in call_text

    @pytest.mark.asyncio
    async def test_app_error_notifica_error_code(self, wa_client, rag_instance):
        rag_instance.preguntar.side_effect = AppError(ErrorCode.SYS_DEPENDENCY_MISSING)
        await procesar_mensaje_bot(rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=False)
        wa_client.enviar_mensaje.assert_called_once()
        call_text = wa_client.enviar_mensaje.call_args[0][1]
        assert ErrorCode.SYS_DEPENDENCY_MISSING.value in call_text


class TestAudioFallos:

    @pytest.mark.asyncio
    async def test_audio_error_notifica_error(self, wa_client, rag_instance):
        wa_client.obtener_audio_base64.side_effect = CommunicationError(ErrorCode.COM_GET_AUDIO_FAILED)
        await procesar_mensaje_bot(rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=True)
        rag_instance.preguntar.assert_not_called()
        wa_client.enviar_mensaje.assert_called_once()
        call_text = wa_client.enviar_mensaje.call_args[0][1]
        assert ErrorCode.COM_GET_AUDIO_FAILED.value in call_text

    @pytest.mark.asyncio
    async def test_audio_devuelve_none_continua_sin_audio(self, wa_client, rag_instance):
        wa_client.obtener_audio_base64.return_value = None
        rag_instance.preguntar.return_value = ("transcripcion", RESPUESTA_OK)
        await procesar_mensaje_bot(rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=True)
        rag_instance.preguntar.assert_called_once_with(
            query_text=TEXTO, audio_bytes=None, remitente=REMITTENTE
        )
        wa_client.enviar_mensaje.assert_called_once_with(REMITTENTE, RESPUESTA_OK)


class TestNotificarError:

    @pytest.mark.asyncio
    async def test_envia_mensaje_con_codigo_de_error(self, wa_client):
        error = CommunicationError(ErrorCode.COM_SEND_MESSAGE_FAILED)
        await _notificar_error(wa_client, REMITTENTE, error)
        wa_client.enviar_mensaje.assert_called_once()
        call_text = wa_client.enviar_mensaje.call_args[0][1]
        assert ErrorCode.COM_SEND_MESSAGE_FAILED.value in call_text
        assert "intentá de nuevo más tarde" in call_text

    @pytest.mark.asyncio
    async def test_notificar_error_falla_silenciosamente(self, wa_client):
        wa_client.enviar_mensaje.side_effect = RuntimeError("error al notificar")
        error = CommunicationError(ErrorCode.COM_CONNECTION_FAILED)
        await _notificar_error(wa_client, REMITTENTE, error)
        wa_client.enviar_mensaje.assert_called_once()

    @pytest.mark.asyncio
    async def test_notificar_error_falla_con_communication_error(self, wa_client):
        wa_client.enviar_mensaje.side_effect = CommunicationError(ErrorCode.COM_SEND_MESSAGE_FAILED)
        error = RAGError(ErrorCode.RAG_QUERY_FAILED)
        await _notificar_error(wa_client, REMITTENTE, error)
        wa_client.enviar_mensaje.assert_called_once()


class TestErroresEnEnvio:

    @pytest.mark.asyncio
    async def test_error_al_enviar_respuesta_notifica_error(self, wa_client, rag_instance):
        rag_instance.preguntar.return_value = ("transcripcion", RESPUESTA_OK)
        wa_client.enviar_mensaje.side_effect = [
            CommunicationError(ErrorCode.COM_SEND_MESSAGE_FAILED),
            None,
        ]
        await procesar_mensaje_bot(rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=False)
        assert wa_client.enviar_mensaje.call_count == 2
        first_call_text = wa_client.enviar_mensaje.call_args_list[0][0][1]
        assert first_call_text == RESPUESTA_OK
        second_call_text = wa_client.enviar_mensaje.call_args_list[1][0][1]
        assert ErrorCode.COM_SEND_MESSAGE_FAILED.value in second_call_text
