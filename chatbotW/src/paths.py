"""
Resolución centralizada de rutas relativas a chatbotW/.

Funciona tanto en desarrollo como en ejecutables (PyInstaller, etc).
Todos los módulos deben importar aquí las rutas, no calcularlas por su cuenta.
"""
import sys
from pathlib import Path


def get_base_path() -> Path:
    """
    Retorna la ruta absoluta a la carpeta raíz para datos/configuración.
    
    - En desarrollo: Path(__file__).parent.parent (src/../ = chatbotW/)
    - En ejecutable: sys.executable.parent (PDFs, logs, cache al mismo nivel que .exe)
    """
    if getattr(sys, 'frozen', False):
        # Ejecutable empaquetado (PyInstaller, cx_Freeze, etc)
        # Carpetas de datos al mismo nivel que el .exe
        return Path(sys.executable).parent
    else:
        # Desarrollo: estamos en src/paths.py
        return Path(__file__).resolve().parent.parent


# Paths absolutas a las carpetas principales
BASE_PATH = get_base_path()

PDF_FOLDER = BASE_PATH / "PDFs"
LOGS_DIR = BASE_PATH / "logs"
CACHE_DIR = BASE_PATH / "cache"
VECTORSTORE_DIR = BASE_PATH / "vectorstore"
CSV_FOLDER = BASE_PATH / "CSVs"
CONFIG_FILE = BASE_PATH / "config_bot.json"
ENV_FILE = BASE_PATH / ".env"

# En desarrollo: src/static. En ejecutable: static/ (al nivel del .exe)
if getattr(sys, 'frozen', False):
    STATIC_DIR = BASE_PATH / "static"
else:
    STATIC_DIR = BASE_PATH / "src" / "static"

FAQS_FILE = BASE_PATH / "faqs.json"

# Crear directorios si no existen (útil para primera ejecución)
for folder in [PDF_FOLDER, LOGS_DIR, CACHE_DIR, VECTORSTORE_DIR, CSV_FOLDER, STATIC_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

# FAQS_FILE parent también
FAQS_FILE.parent.mkdir(parents=True, exist_ok=True)
