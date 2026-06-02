import json
import os
from pathlib import Path
from logging_config import get_logger
from paths import BASE_PATH
from error_codes import ErrorCode
from exceptions import ConfigError

logger = get_logger("config_manager")

class ConfigManager:
    def __init__(self, filename="config_bot.json"):
        # Define la ruta en la raíz del proyecto (un nivel arriba de /src)
        self.path = BASE_PATH / filename
        
        # Intentamos cargar; si no existe, inicializamos y creamos el archivo
        if self.path.exists():
            self.config = {} # Iniciamos vacío para llenar con el archivo
            self.cargar()
        else:
            # Valores iniciales solo si el archivo es nuevo
            self.config = {
                "email": "soporte@empresa.com",
                "telefono": "+54 11 1234-5678",
                "bot_phone": "",
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
                self.config = {"email": "", "telefono": "", "bot_phone": ""}
        finally:
            self.config.setdefault("email", "")
            self.config.setdefault("telefono", "")
            self.config.setdefault("bot_phone", "")
            # Umbral de similitud coseno para que una consulta matchee una FAQ.
            # 0.88 = default conservador; configurable por el operador.
            self.config.setdefault("faq_threshold", 0.88)
            # Nombre de la instancia de Evolution actualmente activa para outbound.
            # Vacio = el bot usa os.environ["EVOLUTION_INSTANCE_NAME"] como fallback.
            # Es el campo que el instance_watcher (PR 3) relee via mtime para
            # hacer hot-swap de la WhatsAppClient sin reiniciar el contenedor.
            self.config.setdefault("active_instance_name", "")

    def guardar(self, nuevo_email=None, nuevo_tel=None, nuevo_bot_phone=None):
        """Actualiza los valores en memoria y los persiste en el disco."""
        if nuevo_email:
            self.config["email"] = nuevo_email
        if nuevo_tel:
            self.config["telefono"] = nuevo_tel
        if nuevo_bot_phone is not None:
            self.config["bot_phone"] = nuevo_bot_phone

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
            os.replace(tmp, self.path)
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