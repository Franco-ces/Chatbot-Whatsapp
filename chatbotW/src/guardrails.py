from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from prompts import PROMPT_GUARDRAIL_ENTRADA, PROMPT_GUARDRAIL_SALIDA
from logging_config import get_logger

logger = get_logger("guardrails")

# --- Handoff detection ---

_FRASES_HANDOFF = [
    "habla con un humano",
    "hablá con un humano",
    "hablar con un humano",
    "quiero hablar con un humano",
    "quiero hablar con una persona",
    "habla con una persona",
    "hablá con una persona",
    "derivame",
    "derivame con un agente",
    "no me sirve",
    "no me sirve la respuesta",
    "necesito un agente",
    "necesito ayuda humana",
    "atencion al cliente",
    "atención al cliente",
    "soporte humano",
    "agente humano",
    "persona real",
    "humano por favor",
    "un humano por favor",
    "quiero una persona",
]

_MSJ_HANDOFF = "Entendido. Te derivo con un agente humano. Tu consulta quedó registrada. Alguien te contactará pronto."


def detectar_solicitud_humano(texto: str) -> bool:
    """Detecta si el usuario solicita hablar con un humano."""
    if not texto:
        return False
    texto_lower = texto.lower().strip()
    return any(frase in texto_lower for frase in _FRASES_HANDOFF)

# --- Rejection messages: input guardrail ---

_MSJ_RECHAZO_ENTRADA = {
    "INSULTO": "Por favor, mantengamos el respeto en la conversación.",
    "PROMPT_INJECTION": "Lo siento, no puedo procesar esa solicitud.",
    "TEMA_ILEGAL": "No puedo hablar sobre esos temas por políticas de uso.",
    "GENERAL": "Lo siento, no puedo procesar esta solicitud porque infringe las políticas de uso.",
}

# --- Rejection messages: output guardrail ---

_MSJ_RECHAZO_SALIDA = {
    "ALUCINACION": "Disculpa, generé información que no puedo verificar en este momento. ¿Podrías ser más específico con tu consulta?",
    "LENGUAJE_INAPROPIADO": "Lo siento, mi respuesta generada no cumplió con los estándares de profesionalismo. ¿Podemos intentar de nuevo?",
    "TONO_INCORRECTO": "Disculpá, mi respuesta no reflejó el tono adecuado. Voy a intentarlo de nuevo.",
    "GENERAL": "Lo siento, generé una respuesta que no cumple con mis parámetros de calidad. ¿Podés reformular tu consulta?",
}


async def evaluar_guardrail_entrada(texto: str, llm_guardrail) -> tuple[bool, str, str]:
    """Evaluate user input for safety.

    Returns:
        (True, "", "") if the input is safe.
        (False, rejection_message, category) if the input is unsafe.
            `category` is the rejection category string (e.g. "INSULTO",
            "PROMPT_INJECTION", "TEMA_ILEGAL", "GENERAL").
    """
    cadena = ChatPromptTemplate.from_template(PROMPT_GUARDRAIL_ENTRADA) | llm_guardrail | StrOutputParser()
    evaluacion = (await cadena.ainvoke({"input": texto})).strip().upper()

    if evaluacion.startswith("INSEGURO"):
        categoria = evaluacion.split("-")[-1].strip() if "-" in evaluacion else "GENERAL"
        mensaje = _MSJ_RECHAZO_ENTRADA.get(categoria, _MSJ_RECHAZO_ENTRADA["GENERAL"])
        logger.info("Input guardrail blocked", category=categoria)
        return False, mensaje, categoria

    return True, "", ""


async def evaluar_guardrail_salida(respuesta: str, contexto: str, llm_guardrail, bot_tone: str = "") -> tuple[bool, str, str]:
    """Evaluate assistant response for quality, accuracy and tone.

    Args:
        respuesta: the assistant's generated response.
        contexto: the original RAG context used to generate the response.
        llm_guardrail: the LangChain LLM instance for evaluation.
        bot_tone: the configured tone description (e.g. "profesional, serio y preciso").
            If empty, tone validation is skipped.

    Returns:
        (True, "", "") if the response is approved.
        (False, rejection_message, category) if the response is rejected.
            `category` is the rejection category string (e.g. "ALUCINACION",
            "LENGUAJE_INAPROPIADO", "TONO_INCORRECTO", "GENERAL").
    """
    cadena = ChatPromptTemplate.from_template(PROMPT_GUARDRAIL_SALIDA) | llm_guardrail | StrOutputParser()
    evaluacion = (await cadena.ainvoke({"output": respuesta, "context": contexto, "bot_tone": bot_tone})).strip().upper()

    if evaluacion.startswith("RECHAZADO"):
        categoria = evaluacion.split("-")[-1].strip() if "-" in evaluacion else "GENERAL"
        mensaje = _MSJ_RECHAZO_SALIDA.get(categoria, _MSJ_RECHAZO_SALIDA["GENERAL"])
        logger.info("Output guardrail rejected", reason=evaluacion, category=categoria)
        return False, mensaje, categoria

    return True, "", ""
