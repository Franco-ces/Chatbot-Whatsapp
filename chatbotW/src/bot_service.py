import base64
import traceback

from exceptions import AppError, CommunicationError
from error_codes import ErrorCode


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
    print(f"--> [1] Iniciando consulta para: {remitente} (push_name: {push_name or 'N/A'})")

    # Log del mensaje del usuario (antes de procesar, para no perderlo si falla)
    if session_manager:
        session_manager.agregar_mensaje(remitente, texto, es_bot=False, push_name=push_name)

    try:
        audio_bytes = None

        if es_audio:
            print("--> [Audio detectado] Descargando desde Evolution API en memoria...")
            audio_b64 = await wa_client.obtener_audio_base64(mensaje_data)
            if audio_b64:
                audio_bytes = base64.b64decode(audio_b64)

        transcripcion, respuesta_texto = await rag_instance.preguntar(
            query_text=texto,
            audio_bytes=audio_bytes,
            remitente=remitente
        )

        print(f"--> [2] Gemini respondió exitosamente: {respuesta_texto}")

        # Log de la respuesta del bot
        if session_manager:
            session_manager.agregar_mensaje(remitente, respuesta_texto, es_bot=True, push_name=push_name)

        print("--> [3] Enviando petición a Evolution API...")
        resultado = await wa_client.enviar_mensaje(remitente, respuesta_texto)
        print(f"--> [4] Resultado final: {resultado}")

    except CommunicationError as e:
        error_code = e.code.value
        print(f"--> [ERROR {error_code}] {e.detail}")
        print(traceback.format_exc())
        await _notificar_error(wa_client, remitente, e)

    except AppError as e:
        error_code = e.code.value
        print(f"--> [ERROR {error_code}] {e.detail}")
        print(traceback.format_exc())
        await _notificar_error(wa_client, remitente, e)

    except Exception as e:
        error_code = ErrorCode.SYS_UNEXPECTED.value
        print(f"--> [ERROR {error_code}] {e}")
        print(traceback.format_exc())
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
        print(f"--> [ERROR] No se pudo notificar al usuario del error {error.code.value}: {e}")
