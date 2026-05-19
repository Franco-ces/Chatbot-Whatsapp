# src/payload_parser.py
from pydantic import BaseModel
from typing import Optional, Dict, Any

class MessageKey(BaseModel):
    remoteJid: str
    fromMe: bool
    id: str

class WebhookData(BaseModel):
    key: MessageKey
    message: Optional[Dict[str, Any]] = None 
    pushName: Optional[str] = None

class EvolutionWebhook(BaseModel):
    event: str
    data: WebhookData

def extraer_datos_limpios(payload: EvolutionWebhook):
    """
    Parsea el objeto validado por Pydantic y devuelve los datos necesarios.
    """
    # 1. Ignorar si no es un mensaje nuevo o si es enviado por el bot
    if payload.event != "messages.upsert" or payload.data.key.fromMe:
        return None

    # Obtenemos el diccionario completo e intacto
    mensaje_data = payload.data.message or {}

    # 2. Extraer texto
    texto = mensaje_data.get("conversation")
    if not texto and mensaje_data.get("extendedTextMessage"):
        texto = mensaje_data["extendedTextMessage"].get("text")

    # 3. Detectar si hay audio
    es_audio = "audioMessage" in mensaje_data

    # 4. Si no hay nada útil, ignorar
    if not texto and not es_audio:
        return None

    return {
        "remitente": payload.data.key.remoteJid,
        "texto": texto,
        "es_audio": es_audio,
        "mensaje_data": {
            "key": {
                "remoteJid": payload.data.key.remoteJid,
                "fromMe": payload.data.key.fromMe,
                "id": payload.data.key.id
            },
            "message": mensaje_data
        }
    }