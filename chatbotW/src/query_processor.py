from pathlib import Path

from langchain_google_genai import ChatGoogleGenerativeAI

# Recursos locales
from audio_handler import AudioProcessor
from ConfigManager import ConfigManager
from prompts import PROMPT_ASISTENTE_VIRTUAL
from guardrails import evaluar_guardrail_entrada, evaluar_guardrail_salida, detectar_solicitud_humano, _MSJ_HANDOFF
from context_builder import construir_contexto
from logging_config import get_logger

# SDK GEMINI
from google import genai
from google.genai import types

logger = get_logger("query_processor")


def notificar_handoff(remitente: str | None, texto: str, historial: str):
    """Stub para notificar handoff a un sistema externo.
    
    TODO: Implementar notificacion real (email, Slack, ticket, etc.)
    """
    logger.info("Handoff registrado", remitente=remitente, texto=texto[:100])


class QueryProcessor:
    """
    Procesa consultas del usuario: audio → guardrails → contexto → prompt → Gemini → guardrails.
    """

    def __init__(self, api_key):
        self.api_key = api_key

        # Cliente Gemini
        self.client = genai.Client(api_key=self.api_key)

        # Procesador de audio
        self.audio_processor = AudioProcessor(self.client)

        # LLM auxiliar para Guardrails con Langchain
        self.llm_guardrail = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", google_api_key=self.api_key)

        # Prompt base
        self.prompt_template = PROMPT_ASISTENTE_VIRTUAL

        # Gestión de configuración (email, teléfono)
        self.config_manager = ConfigManager()

    async def procesar(self, query_text, audio_bytes, retriever, folder_path, remitente, session_manager):
        """
        Maneja entradas de texto, de audio en memoria o ambas de forma híbrida (RAG + JSON).
        Si se provee session_manager, inyecta el historial de conversación en el prompt.
        """
        texto_para_buscar = query_text if query_text else ""
        transcripcion_detectada = query_text
        audio_part = None

        # Procesamiento desacoplado enteramente en memoria
        if audio_bytes:
            texto_extraido, audio_part = await self.audio_processor.extraer_transcripcion_memoria(audio_bytes)
            if not texto_para_buscar and texto_extraido:
                texto_para_buscar = texto_extraido
                transcripcion_detectada = texto_extraido

        # --- GUARDRAIL DE ENTRADA ---
        es_seguro, mensaje_rechazo = await evaluar_guardrail_entrada(
            texto_para_buscar if texto_para_buscar else "audio",
            self.llm_guardrail
        )
        if not es_seguro:
            return transcripcion_detectada, mensaje_rechazo

        # --- HANDOFF: deteccion de solicitud de humano ---
        if detectar_solicitud_humano(texto_para_buscar):
            logger.info("Handoff solicitado por usuario", remitente=remitente)
            notificar_handoff(remitente, texto_para_buscar, "")
            return transcripcion_detectada, _MSJ_HANDOFF

        # --- CONTEXTO (RAG + PRECIOS) ---
        contexto_total = await construir_contexto(
            retriever, texto_para_buscar, folder_path
        )

        # --- HISTORIAL DE CONVERSACIÓN (últimos 10 mensajes) ---
        historial_texto = ""
        if session_manager and remitente:
            historial = session_manager.leer_ultimos_mensajes(remitente, cantidad=10)
            if historial:
                lineas = []
                for msg in historial:
                    rol = "Usuario" if msg["role"] == "USER" else "Asistente"
                    lineas.append(f"[{msg['time']}] {rol}: {msg['message']}")
                historial_texto = "\n".join(lineas)

        # lee el disco por si la interfaz cambió algo
        self.config_manager.cargar()

        # Preparamos las instrucciones de sistema pasándole el contexto unificado
        instrucciones_sistema = self.prompt_template.format(
            history=historial_texto if historial_texto else "Sin historial previo.",
            context=contexto_total,
            input=texto_para_buscar if texto_para_buscar else "Responde a la duda del audio.",
            email=self.config_manager.config["email"],
            telefono=self.config_manager.config["telefono"]
        )

        mensaje_usuario = texto_para_buscar if texto_para_buscar else "Audio adjunto. Por favor responder."

        contenidos_gemini = []
        if audio_part:
            contenidos_gemini.append(audio_part)
        contenidos_gemini.append(mensaje_usuario)

        response = await self.client.aio.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=contenidos_gemini,
            config=types.GenerateContentConfig(
                system_instruction=instrucciones_sistema
            )
        )
        respuesta_texto = response.text

        # --- GUARDRAIL DE SALIDA ---
        es_aceptado, mensaje_rechazo_salida = await evaluar_guardrail_salida(
            respuesta_texto, contexto_total, self.llm_guardrail
        )
        if not es_aceptado:
            return transcripcion_detectada, mensaje_rechazo_salida

        return transcripcion_detectada, respuesta_texto
