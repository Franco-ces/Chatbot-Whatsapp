import time
import httpx_idle_client
from exceptions import CommunicationError
from error_codes import ErrorCode
from logging_config import get_logger

logger = get_logger("whatsapp_client")


class WhatsAppClient:
    def __init__(self, api_url: str, api_key: str, instance_name: str):
        self.api_url = api_url
        self.api_key = api_key
        self.instance_name = instance_name
        self.headers = {
            "apikey": self.api_key,
            "Content-Type": "application/json"
        }
        self._client = httpx_idle_client.IdleTimeoutClient()

    async def obtener_audio_base64(self, mensaje_data: dict):
        """
        Solicita a Evolution API que descargue el medio del mensaje y lo devuelva en Base64.
        """
        url = f"{self.api_url}/chat/getBase64FromMediaMessage/{self.instance_name}"
        
        payload = {
            "message": mensaje_data
        }
        
        try:
            response = await self._client.request("POST", url, json=payload, headers=self.headers)
            if response.status_code in [200, 201]:
                return response.json().get("base64")
            detail = f"Evolution API respondió con código {response.status_code}: {response.text}"
            raise CommunicationError(ErrorCode.COM_GET_AUDIO_FAILED, detail=detail)
        except httpx_idle_client.httpx.HTTPStatusError as e:
            detail = f"Evolution API respondió con código {e.response.status_code}: {e.response.text}"
            raise CommunicationError(ErrorCode.COM_GET_AUDIO_FAILED, detail=detail, cause=e)
        except httpx_idle_client.httpx.RequestError as e:
            detail = f"Error de conexión con Evolution API: {e}"
            raise CommunicationError(ErrorCode.COM_CONNECTION_FAILED, detail=detail, cause=e)

    async def enviar_mensaje(self, numero: str, texto: str):
        url = f"{self.api_url}/message/sendText/{self.instance_name}"
        
        payload = {
            "number": numero,
            "text": texto,
            "delay": 2500
        }
        
        start = time.perf_counter()
        try:
            response = await self._client.request("POST", url, json=payload, headers=self.headers)
            duration_ms = int((time.perf_counter() - start) * 1000)
            
            if response.status_code not in [200, 201]:
                logger.debug("Evolution API response error", status_code=response.status_code, send_duration_ms=duration_ms)
                detail = f"Evolution API rechazó el mensaje (código {response.status_code}): {response.text[:200]}"
                raise CommunicationError(ErrorCode.COM_SEND_MESSAGE_FAILED, detail=detail)
                
            logger.info("Message sent successfully", send_duration_ms=duration_ms)
            return response.json()
        except httpx_idle_client.httpx.HTTPStatusError as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.error("Evolution API HTTP error", send_duration_ms=duration_ms, status_code=e.response.status_code)
            detail = f"Evolution API respondió con código {e.response.status_code}: {e.response.text}"
            raise CommunicationError(ErrorCode.COM_SEND_MESSAGE_FAILED, detail=detail, cause=e)
        except httpx_idle_client.httpx.RequestError as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.error("Evolution API connection error", send_duration_ms=duration_ms, detail=str(e))
            detail = f"Error de conexión con Evolution API: {e}"
            raise CommunicationError(ErrorCode.COM_CONNECTION_FAILED, detail=detail, cause=e)
