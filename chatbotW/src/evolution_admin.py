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
            APIError: 404 -> API_NOT_FOUND, 400 -> API_INVALID_PAYLOAD, 5xx -> API_SERVER_ERROR.
            CommunicationError: error de transporte sin respuesta HTTP.
        """
        try:
            response = await self._http.get("instance/fetchInstances")
        except CommunicationError as e:
            self._raise_as_api_error(e, op="list_instances")
            raise  # noqa
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
        # Evolution v2.x tiene DOS formas de responder segun el estado:
        # - `close` (sin vincular): `{"base64": "...png", "code": "...",
        #   "count": N}` en el RAIZ.
        # - `open` (ya vinculada): `{"instance": {"instanceName": "...",
        #   "state": "open"}}` SIN base64 (no hay nada que escanear).
        # Si no leemos el state de adentro de `instance`, la UI nunca
        # detecta el `open` y el boton "Activar" queda bloqueado para
        # siempre.
        base64_value = (
            body.get("base64")
            or body.get("code")
            or body.get("qrcode")
            or ""
        )
        nested = body.get("instance") if isinstance(body.get("instance"), dict) else {}
        state_value = (
            body.get("state")
            or body.get("status")
            or nested.get("state")
            or nested.get("status")
            or "close"
        )
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
        # Evolution v2.3.7 espera `webhook` como OBJETO anidado (url, events,
        # enabled, headers, base64 adentro). El formato v2.1 mandaba
        # `webhook` como string en la raiz y devuelve 400 'webhook is not
        # of a type object' contra v2.3.7. Cambio confirmado contra el
        # OpenAPI de Evolution Foundation v2.3.7 y probado live con curl
        # (devuelve 200 con el formato anidado, 400 con el viejo).
        payload = {
            "webhook": {
                "enabled": config.enabled,
                "url": config.url,
                "events": config.events,
                "headers": config.headers,
                "base64": False,
            },
        }
        try:
            await self._http.post(f"webhook/set/{name}", json=payload)
        except CommunicationError as e:
            self._raise_as_api_error(e, op=f"set_webhook({name})")
            raise  # noqa

        logger.info("Webhook configured", instance_name=name, url=config.url)

    # ---------------------------------------------------------------
    # get_webhook
    # ---------------------------------------------------------------
    async def get_webhook(self, name: str) -> WebhookConfig | None:
        """Obtiene la configuración actual del webhook de una instancia.

        Devuelve None si la instancia no tiene webhook configurado.

        Raises:
            APIError: mapeo via `_raise_as_api_error`.
            CommunicationError: error de transporte.
        """
        try:
            response = await self._http.get(f"webhook/get/{name}")
        except CommunicationError as e:
            self._raise_as_api_error(e, op=f"get_webhook({name})")
            raise  # noqa

        body = response.json()
        webhook_data = body.get("webhook") if isinstance(body.get("webhook"), dict) else None
        if not webhook_data:
            return None
        return WebhookConfig(
            url=webhook_data.get("url", ""),
            enabled=webhook_data.get("enabled", True),
            events=webhook_data.get("events", ["MESSAGES_UPSERT"]),
            headers=webhook_data.get("headers", {}),
        )

    # ---------------------------------------------------------------
    # disable_webhook
    # ---------------------------------------------------------------
    async def disable_webhook(self, name: str) -> None:
        """Deshabilita el webhook de una instancia (enabled: false).

        Usa el mismo endpoint que set_webhook pero con enabled=False.
        La instancia queda "dormida" — existe en Evolution pero no recibe
        mensajes.

        Si la instancia no tiene webhook configurado (get_webhook falla
        con NOT_FOUND), igual setea enabled=False como no-op seguro.

        Raises:
            APIError: mapeo via `_raise_as_api_error` (distinto de NOT_FOUND).
            CommunicationError: error de transporte.
        """
        try:
            current = await self.get_webhook(name)
        except APIError as e:
            if e.code == ErrorCode.API_NOT_FOUND:
                # Instancia sin webhook configurado — setear enabled=False
                # es un no-op seguro (no hay webhook que deshabilitar).
                current = None
            else:
                raise
        await self.set_webhook(
            name,
            WebhookConfig(
                url=current.url if current else "",
                enabled=False,
                headers=current.headers if current else {},
            ),
        )
        logger.info("Webhook disabled", instance_name=name)

    # ---------------------------------------------------------------
    # delete
    # ---------------------------------------------------------------
    async def delete_instance(self, name: str) -> None:
        """Elimina una instancia de Evolution. NO revisa si es la activa
        (esa decision es de `interface.py`, que cruza con `ConfigManager`
        via el bridge `instance_activation`); este modulo solo habla
        con Evolution.

        Raises:
            APIError: 404 si la instancia no existe, 400 si el nombre
                es invalido, 5xx si Evolution tiene un problema interno.
                Mapeo via `_raise_as_api_error`.
            CommunicationError: error de transporte.
        """
        try:
            await self._http.delete(f"instance/delete/{name}")
        except CommunicationError as e:
            self._raise_as_api_error(e, op=f"delete_instance({name})")
            raise  # noqa: nunca llega aca; _raise_as_api_error siempre lanza

        logger.info("Evolution instance deleted", instance_name=name)

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
        if status == 401:
            raise APIError(
                ErrorCode.API_UNAUTHORIZED,
                detail=f"API key de Evolution no configurada ({op})",
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
