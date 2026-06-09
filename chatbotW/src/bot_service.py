"""
Servicio de Orquestación de Mensajes (Bot Service).

Este módulo implementa el núcleo de la lógica de respuesta del bot siguiendo el 
patrón 'Chain of Responsibility' (Cadena de Responsabilidad). Cada mensaje 
atraviesa una serie de filtros de resolución en orden de costo y precisión:

1. Capa de FAQ (Atajo Semántico): Respuestas curadas por el operador. Latencia mínima.
2. Capa de Cache LRU: Respuestas exactas previas para optimizar recursos.
3. Capa de RAG (Retrieval Augmented Generation): Consulta a documentos PDF vía FAISS y Gemini.
4. Capa de Generación LLM: Respuesta final basada en contexto recuperado.

Este diseño asegura que el sistema sea eficiente en costos de API y rápido en la respuesta.
"""
import asyncio
import base64
import time
import traceback

from exceptions import AppError, CommunicationError
from error_codes import ErrorCode
from logging_config import get_logger
from cache import LRUCache
import telemetry as _telemetry

logger = get_logger("bot_service")

_question_cache = LRUCache(maxsize=100)


_USER_ERROR_MSG = (
    "Ocurrió un error al procesar tu mensaje.\n"
    "Código: {code}\n\n"
    "Por favor, intentá de nuevo más tarde o contactá al soporte con este código."
)


async def procesar_mensaje_bot(rag_instance, wa_client, remitente: str, texto: str,
                         mensaje_data: dict, es_audio: bool,
                         session_manager=None, push_name="",
                         *, instance_name: str, telemetry_pool=None):
    """
    Ejecuta el ciclo de vida del bot: log, obtiene audio (si aplica),
    consulta al RAG, log respuesta y envía el mensaje.
    Ante un error, envía un mensaje amigable al usuario con un código de error.

    `instance_name` es un kwarg keyword-only obligatorio: nombre de la
    instancia Evolution activa para este request. Lo resuelve main.py
    via `InstanceWatcher.get_active_name()` por cada webhook, y se
    propaga a TODAS las llamadas outbound (enviar_mensaje x4 +
    obtener_audio_base64 x1). Sin default para que el caller no pueda
    olvidarlo.

    `telemetry_pool` es el pool de asyncpg para registrar la interacción.
    Si es None, la telemetría se deshabilita (no-op).
    """
    start_time = time.perf_counter()
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
                faq_duration_ms = int((time.perf_counter() - start_time) * 1000)
                if session_manager:
                    session_manager.agregar_mensaje(remitente, faq_answer, es_bot=True, push_name=push_name)
                await wa_client.enviar_mensaje(remitente, faq_answer, instance_name=instance_name)
                asyncio.create_task(_telemetry.record_interaction(
                    telemetry_pool,
                    remitente=remitente, push_name=push_name, texto=texto,
                    es_audio=False, respuesta=faq_answer,
                    cacheable=False, cache_hit=False, faq_hit=True,
                    error_code=None, rag_duration_ms=None,
                    send_duration_ms=None, total_duration_ms=faq_duration_ms,
                ))
                return

        # --- CACHE CHECK (exact match, text-only) ---
        if texto and not es_audio:
            cached = _question_cache.get(texto)
            if cached:
                cache_duration_ms = int((time.perf_counter() - start_time) * 1000)
                if session_manager:
                    session_manager.agregar_mensaje(remitente, cached, es_bot=True, push_name=push_name)
                await wa_client.enviar_mensaje(remitente, cached, instance_name=instance_name)
                asyncio.create_task(_telemetry.record_interaction(
                    telemetry_pool,
                    remitente=remitente, push_name=push_name, texto=texto,
                    es_audio=False, respuesta=cached,
                    cacheable=False, cache_hit=True, faq_hit=False,
                    error_code=None, rag_duration_ms=None,
                    send_duration_ms=None, total_duration_ms=cache_duration_ms,
                ))
                return

        audio_bytes = None

        if es_audio:
            logger.info("Audio detected, downloading from Evolution API")
            audio_b64 = await wa_client.obtener_audio_base64(mensaje_data, instance_name=instance_name)
            if audio_b64:
                audio_bytes = base64.b64decode(audio_b64)

        # --- RAG RELOAD (hot-reload de CSVs/PDFs antes de cada query) ---
        # Verifica cambios en archivos y refresca el vectorstore si es necesario.
        # Si falla, no bloquea la respuesta: se usa el retriever anterior (stale).
        try:
            await rag_instance.actualizar_memoria()
        except Exception as e:
            logger.warning("RAG reload failed, using stale retriever", detail=str(e))

        rag_start = time.perf_counter()
        resultado = await rag_instance.preguntar(
            query_text=texto,
            audio_bytes=audio_bytes,
            remitente=remitente,
            session_manager=session_manager
        )
        transcripcion = resultado.transcripcion
        respuesta_texto = resultado.respuesta
        rag_duration_ms = int((time.perf_counter() - rag_start) * 1000)
        respuesta_cacheable = resultado.cacheable

        logger.info("RAG responded successfully", rag_duration_ms=rag_duration_ms)

        # --- CACHE STORE (text-only, successful responses) ---
        # Solo cacheamos respuestas que el QueryProcessor marcó como confiables
        # (es decir: vino de Gemini con contexto real y pasó el output guardrail).
        # Las respuestas de fallback (rechazo de guardrail, handoff, FAQ shortcut,
        # "no tengo información") llegan con cacheable=False y NO se persisten,
        # porque cachear el fallback "no info" envenenaba el cache LRU.
        if texto and not es_audio and respuesta_texto and respuesta_cacheable:
            _question_cache.set(texto, respuesta_texto)

        # Log de la respuesta del bot
        if session_manager:
            session_manager.agregar_mensaje(remitente, respuesta_texto, es_bot=True, push_name=push_name)

        logger.info("Sending message to Evolution API")
        send_start = time.perf_counter()
        resultado = await wa_client.enviar_mensaje(remitente, respuesta_texto, instance_name=instance_name)
        send_duration_ms = int((time.perf_counter() - send_start) * 1000)
        logger.info("Message sent", send_duration_ms=send_duration_ms, resultado=str(resultado)[:200])

        total_duration_ms = int((time.perf_counter() - start_time) * 1000)
        asyncio.create_task(_telemetry.record_interaction(
            telemetry_pool,
            remitente=remitente, push_name=push_name, texto=texto,
            es_audio=es_audio, respuesta=respuesta_texto,
            cacheable=respuesta_cacheable, cache_hit=False, faq_hit=False,
            error_code=None, rag_duration_ms=rag_duration_ms,
            send_duration_ms=send_duration_ms, total_duration_ms=total_duration_ms,
        ))

    except CommunicationError as e:
        error_code = e.code.value
        total_duration_ms = int((time.perf_counter() - start_time) * 1000)
        logger.error("Communication error", error_code=error_code, detail=e.detail)
        await _notificar_error(wa_client, remitente, e, instance_name=instance_name)
        asyncio.create_task(_telemetry.record_interaction(
            telemetry_pool,
            remitente=remitente, push_name=push_name, texto=texto,
            es_audio=es_audio, respuesta=None,
            cacheable=False, cache_hit=False, faq_hit=False,
            error_code=error_code, rag_duration_ms=None,
            send_duration_ms=None, total_duration_ms=total_duration_ms,
        ))

    except AppError as e:
        error_code = e.code.value
        total_duration_ms = int((time.perf_counter() - start_time) * 1000)
        logger.error("Application error", error_code=error_code, detail=e.detail)
        await _notificar_error(wa_client, remitente, e, instance_name=instance_name)
        asyncio.create_task(_telemetry.record_interaction(
            telemetry_pool,
            remitente=remitente, push_name=push_name, texto=texto,
            es_audio=es_audio, respuesta=None,
            cacheable=False, cache_hit=False, faq_hit=False,
            error_code=error_code, rag_duration_ms=None,
            send_duration_ms=None, total_duration_ms=total_duration_ms,
        ))

    except Exception as e:
        error_code = ErrorCode.SYS_UNEXPECTED.value
        total_duration_ms = int((time.perf_counter() - start_time) * 1000)
        logger.error("Unexpected error", error_code=error_code, detail=str(e))
        app_error = AppError(ErrorCode.SYS_UNEXPECTED, detail=str(e), cause=e)
        await _notificar_error(wa_client, remitente, app_error, instance_name=instance_name)
        asyncio.create_task(_telemetry.record_interaction(
            telemetry_pool,
            remitente=remitente, push_name=push_name, texto=texto,
            es_audio=es_audio, respuesta=None,
            cacheable=False, cache_hit=False, faq_hit=False,
            error_code=error_code, rag_duration_ms=None,
            send_duration_ms=None, total_duration_ms=total_duration_ms,
        ))


async def _notificar_error(wa_client, remitente: str, error: AppError, *, instance_name: str):
    """Envía un mensaje con el código de error al usuario por WhatsApp."""
    try:
        await wa_client.enviar_mensaje(
            remitente,
            _USER_ERROR_MSG.format(code=error.code.value),
            instance_name=instance_name,
        )
    except Exception as e:
        logger.error("Failed to notify user of error", error_code=error.code.value, detail=str(e))
