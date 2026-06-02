"""Pydantic models for the Evolution API v2 instance/admin surface.

These are the only data contracts the rest of the Evolution layer depends on.
They are pure (no HTTP, no logging, no I/O) so they can be unit-tested without
mocks and reused by the admin UI, the CLI, and the future activation bridge.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ConnectionState(str, Enum):
    """Estado de una instancia de Evolution API.

    Los valores coinciden 1:1 con los strings que Evolution devuelve en
    `GET /instance/connectionState/{name}` y `GET /instance/connect/{name}`.
    """

    OPEN = "open"
    CLOSE = "close"
    CONNECTING = "connecting"
    UNKNOWN = "unknown"


class InstanceInfo(BaseModel):
    """Representa una instancia de Evolution tal como la lista
    `GET /instance/fetchInstances` la devuelve.

    Los campos usan alias camelCase para mapear directo al JSON de Evolution;
    `populate_by_name=True` permite construirlos también con los nombres en
    snake_case cuando viene de código Python (tests, CLI, fixtures).
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str
    owner_jid: Optional[str] = Field(None, alias="ownerJid")
    # `connectionState` (camelCase) es el alias "historico" del modelo.
    # `connectionStatus` es el nombre REAL que Evolution v2.x devuelve en
    # `GET /instance/fetchInstances` (campo raiz de cada item, no
    # envuelto). Sin este alias la lista revienta con 500 porque Pydantic
    # no encuentra el campo requerido. `status` (solo aparece en la
    # respuesta de `POST /instance/create` dentro de `instance.status`)
    # ya viene normalizado a `connectionState` por
    # `EvolutionAdmin._extract_instance_payload`, pero lo aceptamos
    # tambien aca por defensa.
    #
    # Acepta cualquiera de los tres al LEER. Al ESCRIBIR (model_dump con
    # by_alias=True) sigue saliendo como `connectionState` para no
    # romper al frontend (`instances.js` usa `inst.connectionState`).
    connection_state: ConnectionState = Field(
        ...,
        validation_alias=AliasChoices(
            "connectionState", "connectionStatus", "status"
        ),
        serialization_alias="connectionState",
    )
    server_url: Optional[str] = Field(None, alias="serverUrl")
    api_key: Optional[str] = Field(None, alias="apiKey")
    integration: Optional[str] = None
    profile_pic_url: Optional[str] = Field(None, alias="profilePicUrl")


class QRPayload(BaseModel):
    """Respuesta de `GET /instance/connect/{name}`.

    `base64` contiene el PNG del QR codificado en base64 (sin prefijo
    `data:image/png;base64,` — se agrega al renderizar). `state` describe
    el estado de la instancia al momento de pedir el QR: si devuelve `open`
    ya no hay nada que escanear y la UI debe dejar de pollear.
    """

    base64: str
    instance: str
    state: ConnectionState


class WebhookConfig(BaseModel):
    """Payload de `POST /webhook/set/{name}`.

    `headers` se usa para enviar `X-Webhook-Secret` (cabecera custom que
    valida el bot al recibir el webhook). `events` por default queda en
    `MESSAGES_UPSERT`, que es el único evento que el bot procesa hoy.
    """

    url: str
    enabled: bool = True
    events: List[str] = Field(default_factory=lambda: ["MESSAGES_UPSERT"])
    headers: dict = Field(default_factory=dict)
