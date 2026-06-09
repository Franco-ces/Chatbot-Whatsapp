from pathlib import Path
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from langchain_google_genai import ChatGoogleGenerativeAI

# Recursos locales
from audio_handler import AudioProcessor
from ConfigManager import ConfigManager
from prompts import PROMPT_ASISTENTE_VIRTUAL
from guardrails import evaluar_guardrail_entrada, evaluar_guardrail_salida, detectar_solicitud_humano, _MSJ_HANDOFF
from context_builder import construir_contexto
from logging_config import get_logger

if TYPE_CHECKING:
    # Evita import circular: faq_matcher importa numpy y logging_config; no necesita
    # query_processor, así que el TYPE_CHECKING es seguro y mantiene la firma tipada.
    from faq_matcher import FAQMatcher

# SDK GEMINI
from google import genai
from google.genai import types

logger = get_logger("query_processor")


@dataclass
class QueryResult:
    """Resultado de `QueryProcessor.procesar()`.

    Attributes:
        transcripcion: texto de la query (o transcripción de audio) tal como
            se pasó al pipeline. Puede ser None si la query vino sólo como audio.
        respuesta: texto que se va a enviar al usuario.
        cacheable: True sólo si la respuesta fue generada por Gemini a partir
            de contexto real (RAG + guardrail de salida aprobado). False para
            respuestas de fallback (rechazo de guardrail de entrada, handoff
            a humano, FAQ shortcut, rechazo de guardrail de salida). El caller
            usa este flag para decidir si cachea la respuesta en el LRU.
    """
    transcripcion: Optional[str]
    respuesta: str
    cacheable: bool


def notificar_handoff(remitente: str | None, texto: str, historial: str):
    """Stub para notificar handoff a un sistema externo.
    
    TODO: Implementar notificacion real (email, Slack, ticket, etc.)
    """
    logger.info("Handoff registrado", remitente=remitente, texto=texto[:100])


class QueryProcessor:
    """
    Procesa consultas del usuario: audio → guardrails → contexto → prompt → Gemini → guardrails.
    """

    def __init__(self, api_key, faq_matcher: Optional["FAQMatcher"] = None):
        self.api_key = api_key

        # Cliente Gemini
        self.client = genai.Client(api_key=self.api_key)

        # Gestión de configuración (email, teléfono, modelo Gemini)
        self.config_manager = ConfigManager()

        # Procesador de audio — modelo configurable desde config
        self.audio_processor = AudioProcessor(
            self.client,
            model=self.config_manager.config.get("gemini_model", "gemini-3.1-flash-lite"),
        )

        # LLM auxiliar para Guardrails con Langchain
        self.llm_guardrail = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", google_api_key=self.api_key)

        # Prompt base
        self.prompt_template = PROMPT_ASISTENTE_VIRTUAL

        # Gestión de configuración (email, teléfono)
        self.config_manager = ConfigManager()

        # Matcher semántico de FAQs (opcional). Si es None, el pipeline
        # opera como siempre (sólo RAG). Lo construye RAGOrchestrator.
        self.faq_matcher = faq_matcher

    async def procesar(self, query_text, audio_bytes, retriever, folder_path, remitente, session_manager) -> QueryResult:
        """
        Maneja entradas de texto, de audio en memoria o ambas de forma híbrida (RAG + JSON).
        Si se provee session_manager, inyecta el historial de conversación en el prompt.

        Devuelve un `QueryResult` con la transcripción, la respuesta y un flag
        `cacheable` que indica si la respuesta debería persistirse en el cache
        LRU del caller (bot_service). Las respuestas de fallback (rechazo de
        guardrail, handoff, FAQ shortcut, rechazo de output) llegan con
        `cacheable=False`; sólo la respuesta final de Gemini con contexto
        aprobado por el guardrail de salida llega con `cacheable=True`.
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
            return QueryResult(transcripcion_detectada, mensaje_rechazo, cacheable=False)

        # --- HANDOFF: deteccion de solicitud de humano ---
        if detectar_solicitud_humano(texto_para_buscar):
            logger.info("Handoff solicitado por usuario", remitente=remitente)
            notificar_handoff(remitente, texto_para_buscar, "")
            return QueryResult(transcripcion_detectada, _MSJ_HANDOFF, cacheable=False)

        # --- FAQ MATCHER: shortcut semántico contra filas del operador ---
        # Si hay match arriba del threshold, devolvemos la respuesta del operador
        # SIN construir contexto, SIN llamar a Gemini, SIN correr el output
        # guardrail (la respuesta es de confianza, la spec lo dice así).
        # El input guardrail ya corrió arriba y el handoff ya fue evaluado.
        if self.faq_matcher is not None and texto_para_buscar:
            try:
                faq_hit = self.faq_matcher.match(texto_para_buscar)
            except Exception as e:
                # Defensa de último recurso: un match() que tira no debe matar el bot.
                logger.warning("FAQMatcher.match() lanzó excepción, continúa con RAG", detail=str(e))
                faq_hit = None
            if faq_hit is not None:
                logger.info(
                    "FAQ shortcut",
                    score=round(faq_hit.score, 4),
                    matched_id=faq_hit.id,
                    returned=True,
                )
                return QueryResult(transcripcion_detectada, faq_hit.respuesta, cacheable=False)

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
        model_name = self.config_manager.config.get("gemini_model", "gemini-3.1-flash-lite")

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
            model=model_name,
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
            return QueryResult(transcripcion_detectada, mensaje_rechazo_salida, cacheable=False)

        return QueryResult(transcripcion_detectada, respuesta_texto, cacheable=True)
