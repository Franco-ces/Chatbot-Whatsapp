import base64
import time
import traceback

from exceptions import AppError, CommunicationError
from error_codes import ErrorCode
from logging_config import get_logger
from cache import LRUCache

logger = get_logger("bot_service")

_question_cache = LRUCache(maxsize=100)


_USER_ERROR_MSG = (
    "Ocurrió un error al procesar tu mensaje.\n"
    "Código: {code}\n\n"
    "Por favor, intentá de nuevo más tarde o contactá al soporte con este código."
)


async def procesar_mensaje_bot(rag_instance, wa_client, remitente: str, texto: str,
                         mensaje_data: dict, es_audio: bool,
                         session_manager=None, push_name=""):
    """
    Ejecuta el ciclo de vida del bot: log, obtiene audio (si aplica),
    consulta al RAG, log respuesta y envía el mensaje.
    Ante un error, envía un mensaje amigable al usuario con un código de error.
    """
    logger.info("Starting bot processing", remitente=remitente, push_name=push_name or "N/A")

    # Log del mensaje del usuario (antes de procesar, para no perderlo si falla)
    if session_manager:
        session_manager.agregar_mensaje(remitente, texto, es_bot=False, push_name=push_name)

    try:
        # --- FAQ CHECK (operator-curated answers, hot-reload por mtime) ---
        # El FAQ es la fuente de verdad que el operador edita en vivo desde
        # la UI. Tiene que correr ANTES del cache LRU de respuestas: si
        # una respuesta cacheada stale coincide con la pregunta, el cache
        # la devuelve y el match() del FAQMatcher nunca se llama, así que
        # el hot-reload no se entera de las ediciones.
        if texto and not es_audio:
            faq_answer = rag_instance.check_faq(texto)
            if faq_answer:
                logger.info("FAQ shortcut (bot_service layer)")
                if session_manager:
                    session_manager.agregar_mensaje(remitente, faq_answer, es_bot=True, push_name=push_name)
                await wa_client.enviar_mensaje(remitente, faq_answer)
                return

        # --- CACHE CHECK (exact match, text-only) ---
        if texto and not es_audio:
            cached = _question_cache.get(texto)
            if cached:
                if session_manager:
                    session_manager.agregar_mensaje(remitente, cached, es_bot=True, push_name=push_name)
                await wa_client.enviar_mensaje(remitente, cached)
                return

        audio_bytes = None

        if es_audio:
            logger.info("Audio detected, downloading from Evolution API")
            audio_b64 = await wa_client.obtener_audio_base64(mensaje_data)
            if audio_b64:
                audio_bytes = base64.b64decode(audio_b64)

        rag_start = time.perf_counter()
        transcripcion, respuesta_texto = await rag_instance.preguntar(
            query_text=texto,
            audio_bytes=audio_bytes,
            remitente=remitente,
            session_manager=session_manager
        )
        rag_duration_ms = int((time.perf_counter() - rag_start) * 1000)

        logger.info("RAG responded successfully", rag_duration_ms=rag_duration_ms)

        # --- CACHE STORE (text-only, successful responses) ---
        if texto and not es_audio and respuesta_texto:
            _question_cache.set(texto, respuesta_texto)

        # Log de la respuesta del bot
        if session_manager:
            session_manager.agregar_mensaje(remitente, respuesta_texto, es_bot=True, push_name=push_name)

        logger.info("Sending message to Evolution API")
        send_start = time.perf_counter()
        resultado = await wa_client.enviar_mensaje(remitente, respuesta_texto)
        send_duration_ms = int((time.perf_counter() - send_start) * 1000)
        logger.info("Message sent", send_duration_ms=send_duration_ms, resultado=str(resultado)[:200])

    except CommunicationError as e:
        error_code = e.code.value
        logger.error("Communication error", error_code=error_code, detail=e.detail)
        await _notificar_error(wa_client, remitente, e)

    except AppError as e:
        error_code = e.code.value
        logger.error("Application error", error_code=error_code, detail=e.detail)
        await _notificar_error(wa_client, remitente, e)

    except Exception as e:
        error_code = ErrorCode.SYS_UNEXPECTED.value
        logger.error("Unexpected error", error_code=error_code, detail=str(e))
        app_error = AppError(ErrorCode.SYS_UNEXPECTED, detail=str(e), cause=e)
        await _notificar_error(wa_client, remitente, app_error)


async def _notificar_error(wa_client, remitente: str, error: AppError):
    """Envía un mensaje con el código de error al usuario por WhatsApp."""
    try:
        await wa_client.enviar_mensaje(
            remitente,
            _USER_ERROR_MSG.format(code=error.code.value)
        )
    except Exception as e:
        logger.error("Failed to notify user of error", error_code=error.code.value, detail=str(e))
