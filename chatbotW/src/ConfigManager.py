import json
from pathlib import Path

class ConfigManager:
    def __init__(self, filename="config_bot.json"):
        # Define la ruta en la raíz del proyecto (un nivel arriba de /src)
        self.path = Path(__file__).resolve().parent.parent / filename
        
        # Intentamos cargar; si no existe, inicializamos y creamos el archivo
        if self.path.exists():
            self.config = {} # Iniciamos vacío para llenar con el archivo
            self.cargar()
        else:
            # Valores iniciales solo si el archivo es nuevo
            self.config = {
                "email": "soporte@empresa.com",
                "telefono": "+54 11 1234-5678"
            }
            self.guardar() # Lo creamos físicamente de entrada

    def cargar(self):
        """Carga la configuración desde el archivo JSON."""
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except Exception as e:
            print(f"⚠️ Error al cargar configuración: {e}")
            self.config = {}
        finally:
            self.config.setdefault("email", "")
            self.config.setdefault("telefono", "")

    def guardar(self, nuevo_email=None, nuevo_tel=None):
        """Actualiza los valores en memoria y los persiste en el disco."""
        if nuevo_email: 
            self.config["email"] = nuevo_email
        if nuevo_tel: 
            self.config["telefono"] = nuevo_tel
        
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"⚠️ Error al guardar configuración: {e}")