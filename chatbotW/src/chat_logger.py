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

        # encabezado inicial
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write("=" * 50 + "\n")
            f.write(f"Chat iniciado: {datetime.now()}\n")
            f.write("=" * 50 + "\n\n")

    def guardar_usuario(self, mensaje):
        hora = datetime.now().strftime("%H:%M:%S")

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"[{hora}] USER: {mensaje}\n")

    def guardar_bot(self, mensaje):
        hora = datetime.now().strftime("%H:%M:%S")

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"[{hora}] BOT: {mensaje}\n")