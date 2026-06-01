import pytest
from unittest.mock import AsyncMock

from bot_service import procesar_mensaje_bot, _notificar_error, _question_cache
from exceptions import AppError, CommunicationError, RAGError
from error_codes import ErrorCode
from query_processor import QueryResult


@pytest.fixture(autouse=True)
def clear_cache():
    """Reset LRU cache between tests."""
    _question_cache.clear()
    yield
    _question_cache.clear()


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
    # check_faq es sync en RAGOrchestrator (match() no es awaitable);
    # lo mockeamos con Mock, no AsyncMock.
    from unittest.mock import Mock
    rag.check_faq = Mock(return_value=None)
    return rag


REMITTENTE = "5491123456789"
TEXTO = "consulta de prueba"
MENSAJE_DATA = {"key": {"id": "123"}}
RESPUESTA_OK = "Esta es la respuesta del bot."


class TestProcesarMensajeExitoso:

    @pytest.mark.asyncio
    async def test_envia_respuesta_sin_audio(self, wa_client, rag_instance):
        rag_instance.preguntar.return_value = QueryResult("transcripcion", RESPUESTA_OK, cacheable=True)
        await procesar_mensaje_bot(rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=False)
        rag_instance.preguntar.assert_called_once_with(
            query_text=TEXTO, audio_bytes=None, remitente=REMITTENTE, session_manager=None
        )
        wa_client.enviar_mensaje.assert_called_once_with(REMITTENTE, RESPUESTA_OK)

    @pytest.mark.asyncio
    async def test_envia_respuesta_con_audio(self, wa_client, rag_instance):
        wa_client.obtener_audio_base64.return_value = "YXVkaW8="
        rag_instance.preguntar.return_value = QueryResult("transcripcion", RESPUESTA_OK, cacheable=True)
        await procesar_mensaje_bot(rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=True)
        wa_client.obtener_audio_base64.assert_called_once_with(MENSAJE_DATA)
        rag_instance.preguntar.assert_called_once()
        kwargs = rag_instance.preguntar.call_args.kwargs
        assert kwargs["audio_bytes"] == b"audio"  # base64 decoded "YXVkaW8="
        wa_client.enviar_mensaje.assert_called_once_with(REMITTENTE, RESPUESTA_OK)

    @pytest.mark.asyncio
    async def test_no_envia_mensaje_de_error(self, wa_client, rag_instance):
        rag_instance.preguntar.return_value = QueryResult("", RESPUESTA_OK, cacheable=True)
        await procesar_mensaje_bot(rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=False)
        call_text = wa_client.enviar_mensaje.call_args[0][1]
        assert "E-" not in call_text


class TestFAQAntesDelCache:
    """El chequeo de FAQ corre ANTES del cache LRU de respuestas.

    Bug: el cache LRU se llenaba con respuestas de RAG y devolvía
    respuestas cacheadas sin consultar al FAQMatcher. Cuando el operador
    editaba una fila en la UI, el bot devolvía la respuesta vieja
    cacheada y nunca llamaba a match(), así que el hot-reload no se
    enteraba. El FAQ es la fuente de verdad que el operador edita en
    vivo, así que su chequeo tiene que ir primero.
    """

    @pytest.mark.asyncio
    async def test_faq_hit_retorna_respuesta_y_no_consulta_rag(self, wa_client, rag_instance):
        """Si check_faq devuelve una respuesta, se envía y NO se llama a rag.preguntar()."""
        FAQ_ANSWER = "Lun a Vie de 9 a 18 hs"
        rag_instance.check_faq.return_value = FAQ_ANSWER
        await procesar_mensaje_bot(rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=False)
        rag_instance.check_faq.assert_called_once_with(TEXTO)
        rag_instance.preguntar.assert_not_called()
        wa_client.enviar_mensaje.assert_called_once_with(REMITTENTE, FAQ_ANSWER)

    @pytest.mark.asyncio
    async def test_faq_miss_falls_through_a_cache_y_rag(self, wa_client, rag_instance):
        """Si check_faq devuelve None, sigue el flujo normal: cache → rag.preguntar()."""
        rag_instance.check_faq.return_value = None
        rag_instance.preguntar.return_value = QueryResult("transcripcion", RESPUESTA_OK, cacheable=True)
        await procesar_mensaje_bot(rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=False)
        rag_instance.check_faq.assert_called_once_with(TEXTO)
        rag_instance.preguntar.assert_called_once()
        wa_client.enviar_mensaje.assert_called_once_with(REMITTENTE, RESPUESTA_OK)

    @pytest.mark.asyncio
    async def test_faq_hit_invalida_cache_stale(self, wa_client, rag_instance):
        """Si el cache tiene una respuesta vieja y la FAQ tiene la nueva, gana la FAQ.

        Reproduce el bug de la smoke E2E: el operador edita la respuesta
        en la UI, el usuario repregunta, el bot debe devolver la nueva
        (del FAQ), no la vieja (del cache).
        """
        # Primera pregunta: RAG responde, se cachea.
        rag_instance.check_faq.return_value = None
        rag_instance.preguntar.return_value = QueryResult("t", "RESPUESTA_VIEJA", cacheable=True)
        await procesar_mensaje_bot(rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=False)
        assert _question_cache.get(TEXTO) == "RESPUESTA_VIEJA"
        # El operador edita la FAQ. Ahora check_faq devuelve la nueva.
        rag_instance.check_faq.return_value = "RESPUESTA_NUEVA"
        wa_client.enviar_mensaje.reset_mock()
        # Segunda pregunta: la FAQ matchea, el cache NO se consulta.
        await procesar_mensaje_bot(rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=False)
        # Y la respuesta enviada es la nueva, no la cacheada.
        wa_client.enviar_mensaje.assert_called_once_with(REMITTENTE, "RESPUESTA_NUEVA")

    @pytest.mark.asyncio
    async def test_faq_miss_preserva_historial_y_ejecuta_rag(self, wa_client, rag_instance):
        """Spec query-processor delta:32-36: History is preserved on FAQ miss.

        GIVEN FAQ miss (check_faq=None) AND session_manager presente
        WHEN `procesar_mensaje_bot` corre THEN (a) el mensaje del usuario
        se agrega al historial, (b) RAG corre normal, (c) la respuesta del
        bot se agrega al historial. Cubre el path de miss específicamente.
        """
        from unittest.mock import MagicMock

        mock_session = MagicMock()
        rag_instance.check_faq.return_value = None  # miss
        rag_instance.preguntar.return_value = QueryResult("t", RESPUESTA_OK, cacheable=True)

        await procesar_mensaje_bot(
            rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA,
            es_audio=False, session_manager=mock_session,
        )

        # El chequeo de FAQ corrió, dio miss, y el pipeline RAG siguió.
        rag_instance.check_faq.assert_called_once_with(TEXTO)
        rag_instance.preguntar.assert_called_once()
        # El mensaje del usuario se agregó al historial ANTES del FAQ check.
        mock_session.agregar_mensaje.assert_any_call(REMITTENTE, TEXTO, es_bot=False, push_name="")
        # La respuesta del bot se agregó al historial DESPUÉS del RAG.
        mock_session.agregar_mensaje.assert_any_call(REMITTENTE, RESPUESTA_OK, es_bot=True, push_name="")
        # Se envió al usuario.
        wa_client.enviar_mensaje.assert_called_once_with(REMITTENTE, RESPUESTA_OK)


class TestCacheLRUConFlagCacheable:
    """El cache LRU de respuestas respeta el flag `cacheable` del QueryResult.

    Bug original: `bot_service` cacheaba CUALQUIER respuesta no-vacía,
    incluyendo el fallback "Lo siento, no cuento con esa información..."
    que el prompt del RAG dispara cuando no hay contexto. Resultado: una
    respuesta mala quedaba cacheada en memoria y todas las repeticiones
    del mismo texto devolvían el fallback aunque la información ya
    estuviera disponible. Fix: el QueryResult trae `cacheable`, y el
    cache store solo se ejecuta cuando es True.
    """

    @pytest.mark.asyncio
    async def test_rag_respuesta_no_cacheable_no_se_guarda(self, wa_client, rag_instance):
        """Cuando el QueryProcessor marca la respuesta como no cacheable
        (ej. fallback de guardrail/handoff, FAQ shortcut, o la respuesta
        'no tengo información' cuando el RAG no encontró contexto), el
        cache LRU NO se debe llenar. Si se llenara, la siguiente vez que
        el usuario repita el mismo texto recibiría la respuesta mala
        cacheada en vez de un intento fresco del RAG.
        """
        rag_instance.check_faq.return_value = None
        FALLBACK = "Lo siento, no cuento con esa información específica. Escribinos a soporte@empresa.com"
        rag_instance.preguntar.return_value = QueryResult(
            "qué planes tienen", FALLBACK, cacheable=False,
        )

        await procesar_mensaje_bot(
            rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=False,
        )

        wa_client.enviar_mensaje.assert_called_once_with(REMITTENTE, FALLBACK)
        # El cache NO debe tener la entrada: el fallback se cachearía
        # envenenando respuestas futuras.
        assert _question_cache.get(TEXTO) is None, (
            "BUG: el cache LRU guardó una respuesta no cacheable. "
            "Próximas repeticiones del mismo texto devolverán el fallback cacheado."
        )

    @pytest.mark.asyncio
    async def test_rag_respuesta_cacheable_si_se_guarda(self, wa_client, rag_instance):
        """Cuando el QueryProcessor marca la respuesta como cacheable
        (respuesta de Gemini con contexto real y guardrail aprobado), el
        cache SÍ se llena para acelerar repeticiones del mismo texto.
        """
        rag_instance.check_faq.return_value = None
        rag_instance.preguntar.return_value = QueryResult(
            TEXTO, RESPUESTA_OK, cacheable=True,
        )

        await procesar_mensaje_bot(
            rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=False,
        )

        assert _question_cache.get(TEXTO) == RESPUESTA_OK

    @pytest.mark.asyncio
    async def test_faq_hit_no_se_cachea_tampoco(self, wa_client, rag_instance):
        """El shortcut de FAQ no pasa por el RAG, pero si pasara, su
        QueryResult llega con cacheable=False (decisión defensiva del
        QueryProcessor). Este test verifica que el bot_service NO cachea
        la respuesta del FAQ: si la cacheara y el operador edita la fila
        en la UI, el usuario recibiría la respuesta vieja cacheada.
        """
        FAQ_ANSWER = "Lun a Vie de 9 a 18 hs"
        rag_instance.check_faq.return_value = FAQ_ANSWER
        # Incluso si por algún refactor futuro el FAQ pasara por preguntar(),
        # el flag cacheable=False debe evitar el cache.
        rag_instance.preguntar.return_value = QueryResult(TEXTO, FAQ_ANSWER, cacheable=False)

        await procesar_mensaje_bot(
            rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=False,
        )

        wa_client.enviar_mensaje.assert_called_once_with(REMITTENTE, FAQ_ANSWER)
        # Importante: el FAQ matchea y la respuesta se envía SIN pasar
        # por el cache store (el short-circuit retorna antes).
        assert _question_cache.get(TEXTO) is None


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
        rag_instance.preguntar.return_value = QueryResult("transcripcion", RESPUESTA_OK, cacheable=True)
        await procesar_mensaje_bot(rag_instance, wa_client, REMITTENTE, TEXTO, MENSAJE_DATA, es_audio=True)
        rag_instance.preguntar.assert_called_once_with(
            query_text=TEXTO, audio_bytes=None, remitente=REMITTENTE, session_manager=None
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
        rag_instance.preguntar.return_value = QueryResult("transcripcion", RESPUESTA_OK, cacheable=True)
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
