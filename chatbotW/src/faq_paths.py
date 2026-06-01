"""Resolución centralizada de la ruta a `faqs.json`.

Tanto el bot (`RAGOrchestrator` → `QueryProcessor` → `FAQMatcher`) como
la UI admin (`interface.py`) necesitan saber dónde vive el archivo de
FAQs. Tener esa resolución duplicada en dos módulos ya nos dio un bug
en producción (PR 2 hotfix): el admin leía `FAQS_VOLUME_MOUNT` pero el
bot no, entonces admin escribía en `/app/faqs_data/faqs.json` y el bot
buscaba un inexistente `/app/faqs.json`.

Convención: `FAQS_VOLUME_MOUNT` es la ruta al DIRECTORIO donde está
montado el named volume `faq_data`. El archivo `faqs.json` vive
adentro. En dev local (sin la env var) se usa `<root>/faqs.json`.

Si cambiás esta lógica, **los dos call sites la ven automáticamente** —
no hay forma de que se desincronicen.
"""
import os
from pathlib import Path


# chatbotW/ → un nivel arriba de src/, donde vive (o vivía) faqs.json.
_ROOT_DIR = Path(__file__).resolve().parent.parent


def resolve_faqs_path() -> Path:
    """Devuelve la ruta absoluta al archivo faqs.json.

    Lee `FAQS_VOLUME_MOUNT` cada vez (no cachea) para que cambios de
    env var en runtime se reflejen sin reinicio. En la práctica la env
    var se setea al arrancar el container y queda fija, pero la
    función es segura de llamar muchas veces.
    """
    mount = os.getenv("FAQS_VOLUME_MOUNT")
    if mount:
        return Path(mount) / "faqs.json"
    return _ROOT_DIR / "faqs.json"


# Atajo: la ruta ya resuelta al momento de importar. Es lo que casi
# todos los call sites necesitan. Si necesitás re-leer (raro), usá
# `resolve_faqs_path()` directamente.
FAQS_PATH = resolve_faqs_path()
