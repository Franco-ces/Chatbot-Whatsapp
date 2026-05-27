import re
from pathlib import Path
from datetime import datetime


class ChatLogger:
    """Logger con buffer en memoria que escribe a disco al hacer flush().

    Cada persona tiene su propio archivo: chat_{contact_name}.txt
    El buffer se acumula en memoria y se persigue cuando se llama a flush()
    (por ejemplo, después de 5 minutos de inactividad).
    """

    def __init__(self, contact_name="unknown"):
        base_path = Path(__file__).resolve().parent.parent
        self.logs_dir = base_path / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        safe_name = self._sanitize_filename(contact_name)
        self.log_file = self.logs_dir / f"chat_{safe_name}.txt"

        # Buffer de líneas en memoria (se escribe a disco en flush)
        self.buffer = []

    # ------------------------------------------------------------------
    # Métodos públicos
    # ------------------------------------------------------------------

    def guardar_usuario(self, mensaje, identificador="USER"):
        hora = datetime.now().strftime("%H:%M")
        mensaje_limpio = mensaje.replace('\n', '[BR]')
        self.buffer.append(f"id_usuario|||{identificador}|||{hora}|||{mensaje_limpio}\n")

    def guardar_bot(self, mensaje, identificador="Neuradocs"):
        hora = datetime.now().strftime("%H:%M")
        mensaje_limpio = mensaje.replace('\n', '[BR]')
        self.buffer.append(f"id_bot|||{identificador}|||{hora}|||{mensaje_limpio}\n")

    def flush(self):
        """Escribe el buffer acumulado a disco y lo vacía."""
        if not self.buffer:
            return

        # Añadimos cabecera de sesión si el archivo no existe
        linea_inicial = None
        if not self.log_file.exists():
            fecha_linda = datetime.now().strftime("%d/%m/%Y")
            hora = datetime.now().strftime("%H:%M")
            linea_inicial = f"Chat iniciado el {fecha_linda} a las {hora}\n"

        with open(self.log_file, "a", encoding="utf-8") as f:
            if linea_inicial:
                f.write(linea_inicial)
            f.writelines(self.buffer)

        self.buffer.clear()

    def finalizar_log(self):
        """Guarda el buffer pendiente y escribe la línea de cierre."""
        self.flush()
        hora = datetime.now().strftime("%H:%M")
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"Chat finalizado a las {hora}\n")

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Limpia el nombre para que sea seguro como nombre de archivo."""
        safe = re.sub(r'[<>:"/\\|?*]', '', name)
        safe = safe.strip().replace(' ', '_')
        return safe or "unknown"
