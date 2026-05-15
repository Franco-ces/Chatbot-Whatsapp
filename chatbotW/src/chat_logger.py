from pathlib import Path
from datetime import datetime

class ChatLogger:
    def __init__(self, folder="logs"):
        # raíz del proyecto
        base_path = Path(__file__).resolve().parent.parent

        # carpeta logs
        self.logs_dir = base_path / folder
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        # nombre del chat según inicio de conversación
        inicio = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        self.log_file = self.logs_dir / f"chat_{inicio}.txt"

        # encabezado inicial (mensaje de sistema)
        hora = datetime.now().strftime("%H:%M")
        fecha_linda = datetime.now().strftime("%d/%m/%Y")
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"Chat iniciado el {fecha_linda} a las {hora}\n")

    def guardar_usuario(self, mensaje, identificador="USER"):
        hora = datetime.now().strftime("%H:%M")
        # Usamos un placeholder único [BR] para los saltos de línea reales.
        # Esto evita que el archivo .txt se rompa físicamente.
        mensaje_limpio = mensaje.replace('\n', '[BR]')
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"id_usuario|||{identificador}|||{hora}|||{mensaje_limpio}\n")

    def guardar_bot(self, mensaje, identificador="BOT"):
        hora = datetime.now().strftime("%H:%M")
        mensaje_limpio = mensaje.replace('\n', '[BR]')
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"id_bot|||{identificador}|||{hora}|||{mensaje_limpio}\n")

    def finalizar_log(self):
        hora = datetime.now().strftime("%H:%M")
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"Chat finalizado a las {hora}\n")
