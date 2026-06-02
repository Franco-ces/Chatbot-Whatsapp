"""Operaciones de alto nivel sobre Evolution API v2.

Cada método de `EvolutionAdmin` corresponde 1:1 a un endpoint REST de
Evolution y se construye sobre el cliente genérico de `evolution_http`.
La capa de admin:
- Compone paths a partir de los nombres de instancia.
- Parsea el JSON de respuesta a modelos Pydantic (ver `evolution_models`).
- Remapea códigos HTTP a `APIError` con códigos específicos del bot
  (404 -> API_NOT_FOUND, 400 -> API_INVALID_PAYLOAD, 5xx -> API_SERVER_ERROR)
  para que la UI y la CLI puedan mostrar mensajes coherentes sin importar
  httpx.

Re-exporta los modelos para que los callers sólo necesiten
`from evolution_admin import EvolutionAdmin, InstanceInfo, ...`.
"""

from __future__ import annotations

from typing import Any, Dict, List

from exceptions import APIError, CommunicationError
from error_codes import ErrorCode
from evolution_http import EvolutionHTTP
from evolution_models import (
    ConnectionState,
    InstanceInfo,
    QRPayload,
    WebhookConfig,
)
from logging_config import get_logger

logger = get_logger("evolution_admin")

# Re-exports: la UI y la CLI importan desde acá para no acoplar a models directo.
__all__ = [
    "EvolutionAdmin",
    "ConnectionState",
    "InstanceInfo",
    "QRPayload",
    "WebhookConfig",
]


class EvolutionAdmin:
    """API de alto nivel para listar, crear, vincular y configurar
    instancias de Evolution. Pensado para ser consumido por el panel admin
    y por el bridge de activacion (`instance_activation`, en PR 2).
    """

    def __init__(self, http: EvolutionHTTP):
        self._http = http

    # ---------------------------------------------------------------
    # list
    # ---------------------------------------------------------------
    async def list_instances(self) -> List[InstanceInfo]:
        """Devuelve todas las instancias registradas en Evolution.

        Raises:
            CommunicationError: error de transporte o HTTP no-2xx.
        """
        response = await self._http.get("instance/fetchInstances")
        data = response.json()
        if not isinstance(data, list):
            # Evolution a veces envuelve la lista en un objeto tipo {"instances": [...]}
            data = data.get("instances") if isinstance(data, dict) else []
        return [InstanceInfo.model_validate(item) for item in data]

    # ---------------------------------------------------------------
    # create
    # ---------------------------------------------------------------
    async def create_instance(
        self, name: str, integration: str = "WHATSAPP-BAILEYS"
    ) -> InstanceInfo:
        """Crea una nueva instancia. Devuelve el `InstanceInfo` resultante.

        El estado inicial esperado de una instancia recién creada es
        `close` (aun no escaneada). Si Evolution ya la tiene registrada
        responde 400 y la UI muestra 409 Conflict.

        Raises:
            APIError: 400 -> API_INVALID_PAYLOAD, 404 -> API_NOT_FOUND, 5xx -> API_SERVER_ERROR.
            CommunicationError: error de transporte.
        """
        payload = {"instanceName": name, "integration": integration}
        try:
            response = await self._http.post("instance/create", json=payload)
        except CommunicationError as e:
            self._raise_as_api_error(e, op=f"create_instance({name})")
            raise  # noqa: nunca llega aca; _raise_as_api_error siempre lanza

        body = response.json() if response.content else {}
        instance_data = self._extract_instance_payload(body, name)
        logger.info("Evolution instance created", instance_name=name, integration=integration)
        return InstanceInfo.model_validate(instance_data)

    # ---------------------------------------------------------------
    # qr
    # ---------------------------------------------------------------
    async def get_qr(self, name: str) -> QRPayload:
        """Devuelve el QR actual y el estado de la instancia.

        La UI debe pollear este endpoint; cuando `state == open`, ya no
        hay nada que escanear y `Activar` se desbloquea.

        Raises:
            APIError: 404 si la instancia no existe; otros mapeos en `_raise_as_api_error`.
        """
        try:
            response = await self._http.get(f"instance/connect/{name}")
        except CommunicationError as e:
            self._raise_as_api_error(e, op=f"get_qr({name})")
            raise  # noqa

        body = response.json()
        base64_value = body.get("base64") or body.get("code") or body.get("qrcode") or ""
        state_value = body.get("state") or body.get("status") or "close"
        return QRPayload(
            base64=base64_value,
            instance=name,
            state=ConnectionState(state_value),
        )

    # ---------------------------------------------------------------
    # state
    # ---------------------------------------------------------------
    async def get_state(self, name: str) -> ConnectionState:
        """Devuelve el estado de conexion de la instancia.

        Raises:
            APIError: 404 -> API_NOT_FOUND (instancia inexistente).
        """
        try:
            response = await self._http.get(f"instance/connectionState/{name}")
        except CommunicationError as e:
            self._raise_as_api_error(e, op=f"get_state({name})")
            raise  # noqa

        body = response.json()
        state = body.get("state") or body.get("instance", {}).get("state") or "unknown"
        return ConnectionState(state)

    # ---------------------------------------------------------------
    # set_webhook
    # ---------------------------------------------------------------
    async def set_webhook(self, name: str, config: WebhookConfig) -> None:
        """Registra el webhook que Evolution llamara cuando llegue un mensaje.

        Raises:
            APIError: 404 si la instancia no existe; otros mapeos en `_raise_as_api_error`.
        """
        # Evolution espera un body con `webhook` (objeto), `webhookByEvents` (false),
        # `events` (lista en raiz). Ajuste defensivo al formato v2 mas comun.
        payload = {
            "webhook": config.url,
            "webhookByEvents": False,
            "events": config.events,
            "enabled": config.enabled,
            "headers": config.headers,
        }
        try:
            await self._http.post(f"webhook/set/{name}", json=payload)
        except CommunicationError as e:
            self._raise_as_api_error(e, op=f"set_webhook({name})")
            raise  # noqa

        logger.info("Webhook configured", instance_name=name, url=config.url)

    # ---------------------------------------------------------------
    # helpers
    # ---------------------------------------------------------------
    def _raise_as_api_error(self, exc: CommunicationError, *, op: str) -> None:
        """Convierte un `CommunicationError` HTTP en `APIError` con codigo
        acorde al status. Si no hay status_code (transporte), re-lanza
        el `CommunicationError` original sin tocar.
        """
        status = exc.status_code
        if status is None:
            # Error de transporte: no tenemos codigo HTTP que mapear.
            return
        if status == 404:
            raise APIError(
                ErrorCode.API_NOT_FOUND,
                detail=f"Instancia no encontrada ({op})",
                cause=exc,
            ) from exc
        if status == 400:
            raise APIError(
                ErrorCode.API_INVALID_PAYLOAD,
                detail=f"Solicitud inválida ({op}): {exc.response_body or exc.detail}",
                cause=exc,
            ) from exc
        if 500 <= status < 600:
            raise APIError(
                ErrorCode.API_SERVER_ERROR,
                detail=f"Error interno de Evolution API ({op})",
                cause=exc,
            ) from exc
        # Otros 4xx: envolver como invalid payload para no filtrar el detalle crudo.
        raise APIError(
            ErrorCode.API_INVALID_PAYLOAD,
            detail=f"Evolution rechazó la solicitud ({op}, status={status})",
            cause=exc,
        ) from exc

    def _extract_instance_payload(self, body: Dict[str, Any], name: str) -> Dict[str, Any]:
        """Normaliza las distintas formas de respuesta de `POST /instance/create`
        a un dict compatible con `InstanceInfo`.
        """
        if "instance" in body and isinstance(body["instance"], dict):
            inner = body["instance"]
            return {
                "name": inner.get("instanceName") or name,
                "ownerJid": inner.get("ownerJid"),
                "connectionState": inner.get("status", "close"),
                "serverUrl": inner.get("serverUrl"),
                "apiKey": inner.get("apikey"),
                "integration": inner.get("integration"),
                "profilePicUrl": inner.get("profilePicUrl"),
            }
        # Fallback: el body ya viene plano con la forma de InstanceInfo.
        return {
            "name": body.get("name") or body.get("instanceName") or name,
            "ownerJid": body.get("ownerJid") or body.get("ownerJid"),
            "connectionState": body.get("connectionState") or body.get("status") or "close",
            "serverUrl": body.get("serverUrl"),
            "apiKey": body.get("apiKey") or body.get("apikey"),
            "integration": body.get("integration"),
            "profilePicUrl": body.get("profilePicUrl"),
        }
