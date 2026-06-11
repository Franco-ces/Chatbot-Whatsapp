import asyncio
import errno
import json
import os
import random
import time
from pathlib import Path
from logging_config import get_logger
from paths import CONFIG_FILE
from error_codes import ErrorCode
from exceptions import ConfigError

logger = get_logger("config_manager")

# 20 intentos con backoff 200ms→5s (suma ~100s) toleran locks prolongados
# del bind-mount de Docker Desktop WSL2 sobre `config_bot.json`. El lock
# puede durar mas de un minuto mientras el FS watcher o el instance_watcher
# suelta el handle; 10 reintentos previos (~50s) no alcanzaban.
MAX_RETRIES = 20
EBUSY_ERRNOS = {errno.EBUSY, errno.ETXTBSY}
# Jitter maximo como fraccion del base delay: 0.3 = hasta +30% aleatorio.
# Evita thundering-herd si varios writers pelean por el mismo lock
# (releasen sincronizado -> todos reintentan al mismo tiempo -> vuelven a chocar).
JITTER_FRACTION = 0.3

class ConfigManager:
    def __init__(self, filename=None):
        # Ruta del config: centralizada en paths.py.
        # Si se pasa un filename custom (ej. tests), se usa BASE_PATH / filename.
        # Si no, se usa paths.CONFIG_FILE que respeta CONFIG_BOT_PATH env var.
        if filename is not None:
            from paths import BASE_PATH
            self.path = BASE_PATH / filename
        else:
            self.path = CONFIG_FILE
        # Cola y worker del write async. Se crean lazy en el primer
        # set_active_instance_async; ver docstring de ese método.
        self._write_queue = None
        self._worker_task = None
        
        # Intentamos cargar; si no existe, inicializamos y creamos el archivo
        if self.path.exists():
            self.config = {} # Iniciamos vacío para llenar con el archivo
            self.cargar()
        else:
            # Valores iniciales solo si el archivo es nuevo
            self.config = {
                "email": "soporte@empresa.com",
                "telefono": "+54 11 1234-5678",
                "faq_threshold": 0.88,
            }
            self.guardar() # Lo creamos físicamente de entrada

    def cargar(self):
        """Carga la configuración desde el archivo JSON."""
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except Exception as e:
            logger.warning("Error loading configuration", detail=str(e))
            if not self.config:
                self.config = {"email": "", "telefono": ""}
        finally:
            self.config.setdefault("email", "")
            self.config.setdefault("telefono", "")
            self.config.setdefault("bot_tone", "profesional")
            # Umbral de similitud coseno para que una consulta matchee una FAQ.
            # 0.88 = default conservador; configurable por el operador.
            self.config.setdefault("faq_threshold", 0.88)
            # Nombre de la instancia de Evolution actualmente activa para outbound.
            # Vacio = el bot usa el LEGACY fallback (EVOLUTION_INSTANCE_NAME env var)
            # si está configurado. La UI de admin es el mecanismo recomendado.
            # Es el campo que el instance_watcher (PR 3) relee via mtime para
            # hacer hot-swap de la WhatsAppClient sin reiniciar el contenedor.
            self.config.setdefault("active_instance_name", "")
            # Modelo de Gemini para generacion (RAG) y transcripcion de audio.
            # Audio comparte la misma key (no hay config separada).
            self.config.setdefault("gemini_model", "gemini-3.1-flash-lite")
            # Modelo de embeddings para FAISS index. Cambiar invalida el vectorstore.
            self.config.setdefault("gemini_embeddings_model", "gemini-embedding-2-preview")

    def guardar(self, nuevo_email=None, nuevo_tel=None, nuevo_tono=None):
        """Actualiza los valores en memoria y los persiste en el disco."""
        if nuevo_email:
            self.config["email"] = nuevo_email
        if nuevo_tel:
            self.config["telefono"] = nuevo_tel
        if nuevo_tono:
            self.config["bot_tone"] = nuevo_tono

        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            logger.warning("Error saving configuration", detail=str(e))

    def set_active_instance(self, name: str) -> None:
        """Escribe `active_instance_name` de forma atomica (tmp + fsync + replace).

        Lo usa `instance_activation.set_active` (PR 2) cuando un admin activa
        una instancia desde la UI. La escritura es atomica para que el
        `instance_watcher` (PR 3) que polea el mtime jamas vea un archivo
        a medio escribir: o ve la version anterior, o ve la nueva completa.

        Garantias:
        - El contenido en disco es siempre un JSON valido y completo
          (porque `os.replace` es una rename atomica POSIX).
        - En `OSError` (disco lleno, permisos, etc.) se intenta borrar el
          tmp y se relanza como `ConfigError(CFG_WRITE_FAILED)` para que
          la UI/CLI pueda mostrar un mensaje claro sin filtrar la excepcion
          cruda.
        - No toca las otras claves del config (solo escribe self.config tal
          cual esta en memoria: el caller es responsable de cargarlo antes).
        """
        self.config["active_instance_name"] = name
        # `.with_suffix(".json.tmp")` sobre `config_bot.json` produce
        # `config_bot.json.tmp` (reemplaza la extension `.json`).
        tmp = self.path.with_suffix(".json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
                f.flush()
                # fsync fuerza el flush al disco antes del rename. Defiende
                # contra `docker compose down` mid-write (page cache muere
                # antes que el rename commitee). Costo: <1ms.
                os.fsync(f.fileno())
            # os.replace es atomica en POSIX cuando origen y destino estan
            # en el mismo filesystem (caso garantizado: mismo directorio).
            # Retry en EBUSY/ETXTBSY: ocurre cuando otro proceso (ej.
            # el instance_watcher o Docker Desktop WSL2 bind-mount)
            # esta leyendo el archivo durante el replace.
            # Backoff exponencial: 200ms, 400ms, 800ms ... max 5s.
            for attempt in range(MAX_RETRIES):
                try:
                    os.replace(tmp, self.path)
                    if attempt > 0:
                        logger.info(
                            "os.replace succeeded after retry",
                            attempt=attempt,
                            instance_name=name,
                        )
                    return
                except OSError as e:
                    if e.errno not in EBUSY_ERRNOS or attempt == MAX_RETRIES - 1:
                        raise
                    base = min(0.2 * (2 ** attempt), 5.0)
                    # Jitter aditivo: rompe sincronia entre writers que comparten
                    # el mismo lock de WSL2 bind-mount. random.uniform(low, high)
                    # con low=0 garantiza que el delay nunca baja del base.
                    jitter = random.uniform(0, base * JITTER_FRACTION)
                    delay = base + jitter
                    logger.warning(
                        "os.replace EBUSY, retrying",
                        attempt=attempt + 1,
                        max_retries=MAX_RETRIES,
                        delay_ms=int(delay * 1000),
                        errno=e.errno,
                    )
                    time.sleep(delay)
        except OSError as e:
            # Limpieza defensiva del tmp. Si ya no existe (otro writer compitio
            # o nunca se creo), swallow el OSError secundario: lo que importa
            # es que el original se propague.
            if tmp.exists():
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise ConfigError(ErrorCode.CFG_WRITE_FAILED, detail=str(e)) from e

    # ------------------------------------------------------------------
    # Write async: encolar el write en background para no bloquear al caller
    # ------------------------------------------------------------------
    #
    # Motivacion: `set_active_instance` puede tardar >100s cuando el bind-mount
    # de Docker Desktop WSL2 sobre `config_bot.json` tiene un lock prolongado
    # (FS watcher del host, instance_watcher leyendo, etc.). Si el endpoint
    # HTTP espera el write, el usuario ve el spinner colgado casi 2 minutos
    # y el request puede incluso timeoutear.
    #
    # Solucion: el endpoint encola el write y devuelve 202 Accepted. Un worker
    # en background drena la cola en orden FIFO y aplica cada write con sus
    # reintentos. El worker corre en un thread aparte (asyncio.to_thread) para
    # no bloquear el event loop mientras hace el `time.sleep` del backoff.
    #
    # Garantia de orden: la cola es FIFO y el worker es single-consumer, asi
    # que el orden de los writes en disco es el orden de los enqueues. Si
    # encolas A, B, C, el archivo final refleja C pero los writes A, B, C
    # se aplicaron en ese orden (cada uno esperó al anterior).
    #
    # Garantia de no-doble-activacion: el lock de activacion vive en
    # `instance_activation.activation_lock` y cubre la parte crítica
    # (disable_webhook + set_webhook). El write async es SOLO metadata para
    # el instance_watcher; si está desfasado, el watcher se sincroniza al
    # siguiente poll.
    async def set_active_instance_async(self, name: str) -> None:
        """Encola un write de `active_instance_name`. Retorna inmediato.

        El write real corre en background via `_write_worker`. Si el worker
        no existe (primer llamado), se crea lazy. Si el write falla, el
        worker loguea y sigue vivo para el siguiente.
        """
        if self._write_queue is None:
            self._write_queue = asyncio.Queue()
            self._worker_task = asyncio.create_task(self._write_worker())
        await self._write_queue.put(name)

    async def _write_worker(self) -> None:
        """Drena la cola FIFO. Un solo consumer, asi el orden es garantizado."""
        while True:
            name = await self._write_queue.get()
            try:
                # El set_active_instance es bloqueante (con reintentos + sleep).
                # Lo corremos en un thread para no trabar el event loop.
                await asyncio.to_thread(self.set_active_instance, name)
            except Exception as e:
                # Cualquier error (ConfigError por EBUSY agotado, OSError, etc.)
                # se loguea pero NO mata al worker. El siguiente write de la
                # cola se procesa normalmente.
                logger.error(
                    "Async write failed; worker continues",
                    instance_name=name,
                    error=str(e),
                )
            finally:
                self._write_queue.task_done()

    async def stop_worker(self) -> None:
        """Cancela el worker. Pensado para shutdown del proceso / fin de tests."""
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
            self._write_queue = None