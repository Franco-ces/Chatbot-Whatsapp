"""Watcher que polea el mtime de `config_bot.json` y expone el nombre de
la instancia activa para outbound.

Diseno: ADR-1 (mtime polling <=1s, jitter +/-150ms; ver design.md).

Cuando un admin activa una instancia desde la UI (via
`instance_activation.set_active`, PR 2), el bridge escribe
`active_instance_name` en `config_bot.json` de forma atomica
(tmp + fsync + os.replace). Este watcher detecta el cambio de mtime
y refresca `_active_name` para que `main.py` pueda resolver el nombre
activo en cada webhook, sin reiniciar el bot.

Reglas arquitectonicas (enforcement en PR 4 con test de boundaries):
- READ-ONLY: este modulo NO llama a `evolution_*`, NO llama a
  `instance_activation`, NO escribe al config. Solo lee.
- La activacion (validar state, setear webhook, escribir config) la
  hace `instance_activation` desde la UI/CLI; el watcher es un
  observador pasivo.

Por que `threading.Lock` y no `asyncio.Lock`:
El design original sugiere `asyncio.Lock`, pero `reload_now` (parte
de la API publica) es sync, pensado para tests. Una `asyncio.Lock`
no se puede acquire sincronico sin un loop corriendo. Usar
`threading.Lock` resuelve ambos: serializa el swap entre el poll
loop async y los callers sync de `reload_now`, y permite adquirir
desde un test thread sin event loop. El lock se mantiene brevemente
(sin async ops adentro), asi que no bloquea el event loop en la
practica.
"""

from __future__ import annotations

import asyncio
import json
import random
import threading
from pathlib import Path
from typing import Union

from logging_config import get_logger

logger = get_logger("instance_watcher")

DEFAULT_POLL_SECONDS = 1.0
DEFAULT_JITTER_SECONDS = 0.15


class InstanceWatcher:
    """Polea `config_bot.json` mtime y expone `active_instance_name`.

    Uso en produccion (main.py):
        watcher = InstanceWatcher(Path("config_bot.json"))
        await watcher.start()
        # ... dentro del webhook handler:
        instance_name = watcher.get_active_name() or os.environ["EVOLUTION_INSTANCE_NAME"]
        # ... al apagar:
        await watcher.stop()

    Uso en tests:
        watcher = InstanceWatcher(config_path, poll_seconds=0.05, jitter_seconds=0.01)
        # Escribir el config a tmp_path, llamar reload_now() y assert.
    """

    def __init__(
        self,
        config_path: Union[str, Path],
        *,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        jitter_seconds: float = DEFAULT_JITTER_SECONDS,
    ):
        self._config_path = Path(config_path)
        self._poll_seconds = float(poll_seconds)
        self._jitter_seconds = float(jitter_seconds)
        # Estado observable
        self._active_name: str = ""
        self._known_mtime: float = 0.0
        # Task asyncio (None antes de start())
        self._task: asyncio.Task | None = None
        # Lock para serializar el swap entre el poll loop (async) y
        # reload_now() (sync). Ver docstring del modulo.
        self._lock = threading.Lock()

    # --- API publica ---

    async def start(self) -> None:
        """Carga el estado inicial y arranca la task de polling. Idempotente.

        El estado inicial se lee sincronico (reload_now) ANTES de
        spawnar la task: asi el primer webhook que llegue despues de
        start() ya tiene el nombre correcto, sin esperar al primer
        tick.
        """
        if self._task is not None and not self._task.done():
            return
        # Estado inicial sincronico: leemos el config una vez antes
        # de empezar a polear. Si el archivo no existe todavia (arranque
        # muy temprano), reload_now es un no-op y el primer tick lo
        # recogera cuando aparezca.
        self.reload_now()
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "InstanceWatcher started",
            config_path=str(self._config_path),
            active_name=self._active_name,
        )

    async def stop(self) -> None:
        """Cancela la task de polling. Idempotente y safe contra doble call."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("InstanceWatcher stopped")

    def get_active_name(self) -> str:
        """Devuelve el nombre activo actual (puede ser "" si no se seteo).

        Lectura sync, sin lock: bajo el GIL de CPython, una lectura
        de atributo string es atomica. El lector ve siempre un string
        consistente (viejo o nuevo), nunca un valor a medio construir.
        En la practica esto significa: si justo se hace el swap
        mientras se lee, el lector usa el nombre anterior para ese
        request y el siguiente ya ve el nuevo. Es el comportamiento
        esperado por el design (in-flight requests completan normal,
        nuevos requests usan el nuevo nombre).
        """
        return self._active_name

    def reload_now(self) -> None:
        """Fuerza un check inmediato. Usado en tests; no en produccion.

        Idempotente: si el mtime no cambio, no hace nada (no relee
        el JSON, no loggea). Si cambio, relee y swap bajo el lock.
        """
        with self._lock:
            try:
                mtime = self._config_path.stat().st_mtime
            except FileNotFoundError:
                # El config aun no existe. Dejamos _known_mtime en 0
                # para que el proximo tick (cuando aparezca) lo detecte
                # como cambio.
                return
            except OSError as e:
                logger.warning(
                    "InstanceWatcher: stat failed",
                    detail=str(e),
                )
                return
            if mtime == self._known_mtime:
                return
            self._known_mtime = mtime
            new_name = self._read_active_name()
            if new_name != self._active_name:
                old = self._active_name
                self._active_name = new_name
                logger.info(
                    "InstanceWatcher: active_instance_name changed",
                    old=old,
                    new=new_name,
                )

    # --- Internals ---

    async def _poll_loop(self) -> None:
        """Loop principal: duerme con jitter, checkea mtime, recarga si cambio.

        Un reload fallido NO mata el loop: se loggea y sigue. Asi si
        el archivo es borrado temporalmente o tiene JSON malformado
        (improbable por el atomic write de PR 2 pero posible por
        intervencion manual), el watcher sigue vivo y reintenta en
        el proximo tick.
        """
        try:
            while True:
                await asyncio.sleep(self._compute_sleep_for())
                try:
                    self.reload_now()
                except Exception as e:
                    # Defensive: reload_now ya captura sus propios
                    # errores, pero un bug futuro no deberia matar
                    # el watcher.
                    logger.warning(
                        "InstanceWatcher reload failed",
                        detail=str(e),
                    )
        except asyncio.CancelledError:
            # shutdown path: stop() nos cancela. Propagamos.
            raise

    def _compute_sleep_for(self) -> float:
        """Calcula cuanto debe dormir el poll loop en este tick.

        Formula: `poll_seconds + uniform(-jitter_seconds, +jitter_seconds)`,
        clampeado a 0 (por si jitter > poll). Expuesto como metodo
        (no inline en el loop) para que sea facil de testear sin
        patchear el modulo `asyncio` global.
        """
        sleep_for = self._poll_seconds + random.uniform(
            -self._jitter_seconds, self._jitter_seconds
        )
        if sleep_for < 0:
            sleep_for = 0
        return sleep_for

    def _read_active_name(self) -> str:
        """Lee el JSON y devuelve `active_instance_name` ('' si falta).

        Si la lectura falla (archivo a medio escribir por el writer
        atómico de PR 2, JSON corrupto, permisos), se loggea y se
        devuelve el `_active_name` anterior. Asi el watcher no
        "olvida" el nombre activo por un blip transitorio.
        """
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            # Caso limite: el archivo existia al stat() pero desaparecio
            # entre el stat y el open. Dejamos el valor anterior.
            return self._active_name
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(
                "InstanceWatcher: config read failed",
                detail=str(e),
            )
            return self._active_name
        if not isinstance(data, dict):
            # El config deberia ser un dict. Si alguien lo corrompio
            # a un tipo raro, no crasheamos: devolvemos el valor
            # anterior y esperamos que el proximo tick lo arregle.
            logger.warning(
                "InstanceWatcher: config is not a dict",
                config_type=type(data).__name__,
            )
            return self._active_name
        return data.get("active_instance_name", "") or ""
