import base64
import time
import httpx_idle_client
from exceptions import CommunicationError
from error_codes import ErrorCode
from logging_config import get_logger

logger = get_logger("whatsapp_client")


class WhatsAppClient:
    """Cliente HTTP para Evolution API. `instance_name` es per-call, no de instancia.

    Antes (pre-PR-3): el nombre de instancia se pasaba en el constructor
    y se guardaba como atributo. Cada llamada armaba la URL a partir de
    `self.instance_name`. Eso ataba el cliente a UNA instancia para
    toda la vida del proceso: para cambiar de instancia (hot-swap) habia
    que reconstruir el cliente (descartando el connection pool) o
    mantener un pool por instancia (YAGNI).

    Ahora (post-PR-3): el cliente es un wrapper HTTP generico. El
    nombre de instancia llega como kwarg en cada llamada. main.py
    resuelve el nombre via `InstanceWatcher.get_active_name()` antes
    de cada outbound y lo pasa aca. La misma instancia del cliente
    sirve para A y B; el nombre cambia por llamada, no por rebuild.

    Atomicidad: el kwarg es keyword-only (`*, instance_name: str`) y
    NO tiene default — asi el caller no puede olvidarlo accidentalmente.
    """

    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url
        self.api_key = api_key
        self.headers = {
            "apikey": self.api_key,
            "Content-Type": "application/json"
        }
        self._client = httpx_idle_client.IdleTimeoutClient()

    async def obtener_audio_base64(self, mensaje_data: dict, *, instance_name: str):
        """
        Solicita a Evolution API que descargue el medio del mensaje y lo devuelva en Base64.
        """
        url = f"{self.api_url}/chat/getBase64FromMediaMessage/{instance_name}"

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

    async def enviar_mensaje(self, numero: str, texto: str, *, instance_name: str):
        url = f"{self.api_url}/message/sendText/{instance_name}"

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

    async def enviar_documento(self, numero: str, pdf_bytes: bytes, filename: str, *, instance_name: str) -> dict:
        """Envía un documento PDF vía Evolution API sendMedia.

        Codifica pdf_bytes en base64 como data URI y lo envía como
        mediatype=document con mimetype=application/pdf.
        Usa el patrón per-call instance_name igual que enviar_mensaje.
        """
        pdf_b64 = base64.b64encode(pdf_bytes).decode()
        payload = {
            "number": numero,
            "mediatype": "document",
            "mimetype": "application/pdf",
            "media": pdf_b64,
            "fileName": filename,
        }
        url = f"{self.api_url}/message/sendMedia/{instance_name}"

        start = time.perf_counter()
        try:
            response = await self._client.request("POST", url, json=payload, headers=self.headers)
            duration_ms = int((time.perf_counter() - start) * 1000)

            if response.status_code not in (200, 201):
                logger.debug("Evolution API response error", status_code=response.status_code, send_duration_ms=duration_ms)
                detail = f"Evolution API rechazó el documento (código {response.status_code}): {response.text[:200]}"
                raise CommunicationError(ErrorCode.COM_SEND_DOCUMENT_FAILED, detail=detail)

            logger.info("Document sent successfully", send_duration_ms=duration_ms)
            return response.json()
        except httpx_idle_client.httpx.HTTPStatusError as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.error("Evolution API HTTP error", send_duration_ms=duration_ms, status_code=e.response.status_code)
            detail = f"Evolution API respondió con código {e.response.status_code}: {e.response.text}"
            raise CommunicationError(ErrorCode.COM_SEND_DOCUMENT_FAILED, detail=detail, cause=e)
        except httpx_idle_client.httpx.RequestError as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.error("Evolution API connection error", send_duration_ms=duration_ms, detail=str(e))
            detail = f"Error de conexión con Evolution API: {e}"
            raise CommunicationError(ErrorCode.COM_CONNECTION_FAILED, detail=detail, cause=e)
