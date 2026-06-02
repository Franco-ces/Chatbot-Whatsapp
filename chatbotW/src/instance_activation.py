"""Bridge de activacion: unico modulo que cruza `ConfigManager` y `evolution_admin`.

Cuando un admin pulsa "Activar" en la UI (o invoca el subcomando CLI
`set-active`), se ejecuta `set_active(name)` que hace TRES cosas en orden:

  1) Re-verifica `state == OPEN` contra Evolution (defiende contra drift
     entre lo que la UI vio por polling y el estado real al click).
  2) Configura el webhook de la instancia con `BOT_URL` + `WEBHOOK_SECRET`
     (cada instancia tiene su propio webhook; el de la instancia anterior
     queda intacto para rollback).
  3) Escribe `config_bot.json.active_instance_name` de forma atomica
     (ConfigManager.set_active_instance hace tmp+fsync+os.replace).

Orden importa: si `set_webhook` falla, NO escribimos el config. Asi el
watcher (PR 3) no ve un swap parcial donde el config dice "bot_2" pero
el webhook sigue apuntando a la config vieja.

Reglas arquitectonicas (enforcement en PR 4 con test de boundaries):
- Este es el UNICO modulo que importa tanto `ConfigManager` como
  `evolution_admin`. Si otra pieza necesita cruzar el dominio, va
  por aca.
- `ConfigManager` no importa nada de evolution_*; `evolution_admin` no
  importa nada de ConfigManager. Mantener limpia la linea entre los dos
  dominios.
"""

from __future__ import annotations

from logging_config import get_logger

from ConfigManager import ConfigManager
from error_codes import ErrorCode
from evolution_admin import EvolutionAdmin
from evolution_models import ConnectionState, WebhookConfig
from exceptions import APIError

logger = get_logger("instance_activation")


async def set_active(
    name: str,
    *,
    admin: EvolutionAdmin,
    config: ConfigManager | None = None,
    config_path: str | None = None,
    webhook_url: str,
    webhook_secret: str,
) -> None:
    """Activa una instancia: re-verifica estado, setea webhook, escribe config.

    Args:
        name: nombre de la instancia a activar (debe matchear un Evolution
            instance existente y vinculado).
        admin: cliente de alto nivel ya construido contra Evolution.
        config: ConfigManager ya instanciado apuntando al config_bot.json
            que el bot esta usando (el watcher de PR 3 polea este mismo
            archivo). Si es None, se construye uno a partir de `config_path`
            (o con el path por defecto si `config_path` tambien es None).
            Tests pasan `config=` para inyectar un mock; callers de
            produccion (CLI, admin UI) suelen pasar `config_path=` y dejar
            que el bridge construya.
        config_path: ruta al config_bot.json. Solo se usa si `config` es None.
        webhook_url: URL publica del bot (el destino que Evolution va a
            llamar cuando llegue un mensaje). Viene de `os.environ["BOT_URL"]`.
        webhook_secret: valor del header `X-Webhook-Secret` que el bot
            valida al recibir el webhook. Viene de
            `os.environ["WEBHOOK_SECRET"]`.

    Raises:
        APIError(code=EVO_INSTANCE_NOT_LINKED): si la instancia no esta
            en estado `open` al momento de activar (drift, `connecting`,
            `close`, `unknown`). La UI traduce esto a 409.
        APIError: cualquier error HTTP de Evolution (mapeado por
            `EvolutionAdmin._raise_as_api_error`).
        ConfigError: si la escritura atomica de config_bot.json falla.
    """
    if config is None:
        # Caller de produccion (CLI, admin) prefiere pasar config_path
        # y dejar que el bridge construya. Asi NO necesita importar
        # ConfigManager (mantiene limpia la frontera de dominios).
        config = ConfigManager(config_path) if config_path else ConfigManager()
    # 1) Re-verificar estado contra Evolution. NO confiamos en lo que la UI
    # mostro por polling: entre el ultimo GET /state y este click pueden
    # haber pasado varios segundos y la instancia pudo haber caido.
    state = await admin.get_state(name)
    # El contrato de `EvolutionAdmin.get_state` es devolver `ConnectionState`,
    # pero normalizamos aca por dos motivos: (a) los tests mockean con strings
    # crudos para no acoplarse al enum, (b) si en el futuro evolution_admin
    # cambia la representacion interna, este bridge no se entera.
    if not isinstance(state, ConnectionState):
        state = ConnectionState(state)
    if state != ConnectionState.OPEN:
        if state == ConnectionState.CONNECTING:
            # Caso especial: la instancia esta en pleno handshake con
            # WhatsApp. Mensaje mas util que el default ("no vinculada"),
            # porque el admin probablemente SI escaneo el QR pero todavia
            # no termino de conectar.
            detail = "La instancia aún está conectando"
        else:
            # close / unknown / cualquier estado no aceptable.
            detail = (
                f"La instancia '{name}' está en estado '{state.value}' "
                "y no puede activarse"
            )
        logger.warning(
            "Activation aborted: instance not in OPEN state",
            instance_name=name,
            state=state.value,
        )
        raise APIError(ErrorCode.EVO_INSTANCE_NOT_LINKED, detail=detail)

    # 2) Configurar webhook. Si esto falla, NO seguimos: el config
    # quedaria apuntando a una instancia sin webhook apuntando al bot,
    # y los mensajes nunca llegarian.
    await admin.set_webhook(
        name,
        WebhookConfig(
            url=webhook_url,
            headers={"X-Webhook-Secret": webhook_secret},
        ),
    )

    # 3) Escritura atomica del config. Es la ultima operacion y es la
    # unica que el watcher de PR 3 va a observar (via mtime).
    config.set_active_instance(name)
    logger.info("Instance activated", instance_name=name, webhook_url=webhook_url)
