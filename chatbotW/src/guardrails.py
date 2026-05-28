from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from prompts import PROMPT_GUARDRAIL_ENTRADA, PROMPT_GUARDRAIL_SALIDA
from logging_config import get_logger

logger = get_logger("guardrails")

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
    "GENERAL": "Lo siento, generé una respuesta que no cumple con mis parámetros de calidad. ¿Podés reformular tu consulta?",
}


async def evaluar_guardrail_entrada(texto: str, llm_guardrail) -> tuple[bool, str]:
    """Evaluate user input for safety.

    Returns:
        (True, "") if the input is safe.
        (False, rejection_message) if the input is unsafe.
    """
    cadena = ChatPromptTemplate.from_template(PROMPT_GUARDRAIL_ENTRADA) | llm_guardrail | StrOutputParser()
    evaluacion = (await cadena.ainvoke({"input": texto})).strip().upper()

    if evaluacion.startswith("INSEGURO"):
        categoria = evaluacion.split("-")[-1].strip() if "-" in evaluacion else "GENERAL"
        mensaje = _MSJ_RECHAZO_ENTRADA.get(categoria, _MSJ_RECHAZO_ENTRADA["GENERAL"])
        logger.info("Input guardrail blocked", category=categoria)
        return False, mensaje

    return True, ""


async def evaluar_guardrail_salida(respuesta: str, contexto: str, llm_guardrail) -> tuple[bool, str]:
    """Evaluate assistant response for quality and accuracy.

    Returns:
        (True, "") if the response is approved.
        (False, rejection_message) if the response is rejected.
    """
    cadena = ChatPromptTemplate.from_template(PROMPT_GUARDRAIL_SALIDA) | llm_guardrail | StrOutputParser()
    evaluacion = (await cadena.ainvoke({"output": respuesta, "context": contexto})).strip().upper()

    if evaluacion.startswith("RECHAZADO"):
        categoria = evaluacion.split("-")[-1].strip() if "-" in evaluacion else "GENERAL"
        mensaje = _MSJ_RECHAZO_SALIDA.get(categoria, _MSJ_RECHAZO_SALIDA["GENERAL"])
        logger.info("Output guardrail rejected", reason=evaluacion, category=categoria)
        return False, mensaje

    return True, ""
