"""Cliente HTTP delgado para Evolution API v2.

Envuelve `httpx_idle_client.IdleTimeoutClient` para:
- Reusar el pool de conexiones entre llamadas (como `whatsapp_client`).
- Auto-cerrar el cliente tras 5 minutos de inactividad.
- Construir la URL completa a partir de un prefijo + path.
- Inyectar la cabecera `apikey` que Evolution usa para autenticar.
- Mapear errores de transporte a `CommunicationError(COM_CONNECTION_FAILED)`
  y respuestas no-2xx a `CommunicationError(COM_SEND_MESSAGE_FAILED)`
  con `status_code` y `response_body` adjuntos para que las capas de
  arriba (admin) puedan traducir a `APIError` específicos.

No conoce Pydantic ni modelos: devuelve `httpx.Response` en crudo. La
capa `evolution_admin` es la que parsea.
"""

from __future__ import annotations

import httpx
import httpx_idle_client

from exceptions import CommunicationError
from error_codes import ErrorCode
from logging_config import get_logger

logger = get_logger("evolution_http")


class EvolutionHTTP:
    """Wrapper asíncrono sobre `IdleTimeoutClient` para Evolution API."""

    def __init__(self, api_url: str, api_key: str, *, timeout: float = 30.0):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx_idle_client.IdleTimeoutClient(
            timeout=httpx.Timeout(timeout)
        )

    def _build_url(self, path: str) -> str:
        """Une `api_url` y `path` con un solo `/`, normalizando ambos extremos."""
        return f"{self.api_url}/{path.lstrip('/')}"

    def _headers(self) -> dict:
        """Cabeceras por-request: autenticación + content type JSON."""
        return {
            "apikey": self.api_key,
            "Content-Type": "application/json",
        }

    async def get(self, path: str, **kwargs) -> httpx.Response:
        """GET a `path`. Levanta `CommunicationError` ante cualquier fallo."""
        url = self._build_url(path)
        try:
            response = await self._client.request(
                "GET", url, headers=self._headers(), **kwargs
            )
        except httpx.RequestError as e:
            raise CommunicationError(
                ErrorCode.COM_CONNECTION_FAILED,
                detail=f"Error de conexión con Evolution API: {e}",
                cause=e,
            )
        self._raise_for_status(response)
        return response

    async def post(self, path: str, json: dict | None = None, **kwargs) -> httpx.Response:
        """POST a `path` con cuerpo JSON. Levanta `CommunicationError` ante cualquier fallo."""
        url = self._build_url(path)
        try:
            response = await self._client.request(
                "POST", url, json=json, headers=self._headers(), **kwargs
            )
        except httpx.RequestError as e:
            raise CommunicationError(
                ErrorCode.COM_CONNECTION_FAILED,
                detail=f"Error de conexión con Evolution API: {e}",
                cause=e,
            )
        self._raise_for_status(response)
        return response

    async def aclose(self) -> None:
        """Cierra el cliente subyacente (libera conexiones del pool)."""
        await self._client.aclose()

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Si la respuesta no es 2xx, levanta `CommunicationError` con el status."""
        if 200 <= response.status_code < 300:
            return
        detail = (
            f"Evolution API respondió con código {response.status_code}: "
            f"{response.text[:200]}"
        )
        logger.debug(
            "Evolution API non-2xx response",
            status_code=response.status_code,
            body_preview=response.text[:200],
        )
        raise CommunicationError(
            ErrorCode.COM_SEND_MESSAGE_FAILED,
            detail=detail,
            status_code=response.status_code,
            response_body=response.text,
        )
