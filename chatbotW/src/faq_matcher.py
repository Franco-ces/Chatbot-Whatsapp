"""Matcheo semántico de consultas del usuario contra FAQs del operador.

Lee `faqs.json` desde disco, embebe cada `pregunta` con Gemini y compara
contra el embedding de la consulta por cosine similarity. Hot-reload
automático por mtime. Tolerante a archivo inexistente, JSON inválido,
filas mal formadas o fallos de la API de embeddings: en cada caso loggea
un warning y degrada a "sin match" sin tirar el bot.

Historia de diseño: ver `openspec/changes/add-faq-admin-table/design.md`,
sección "Interfaces / Contracts".
"""
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from logging_config import get_logger

logger = get_logger("faq_matcher")


# Umbral por defecto si ConfigManager no tiene `faq_threshold` o está fuera de rango.
DEFAULT_THRESHOLD = 0.88


@dataclass
class FAQMatch:
    """Resultado de un match positivo contra una fila de FAQ."""
    id: str
    pregunta: str
    respuesta: str
    score: float


class FAQMatcher:
    """Matchea consultas del usuario contra FAQs del operador."""

    def __init__(self, faqs_path: Path, embeddings_model, config_manager, logger):
        # Guardamos referencias. `logger` se acepta posicionalmente para
        # alinearse con la firma del design.md; si el caller pasa `None`
        # usamos el logger del módulo.
        self.faqs_path = faqs_path
        self.embeddings_model = embeddings_model
        self.config_manager = config_manager
        self.logger = logger if logger is not None else globals()["logger"]

        # Estado interno: filas activas con su vector embebido.
        self._rows: List = []
        # Mtime cacheado; 0.0 significa "archivo ausente" (no se puede leer mtime).
        self._mtime: float = 0.0
        # Si True, el matcher se rinde y devuelve None para cualquier query
        # (caso: la API de embeddings falló durante __init__).
        self._disabled: bool = False

        # Carga inicial (mismo flujo que _reload_if_changed).
        self._reload_if_changed()

    def match(self, query: str) -> Optional[FAQMatch]:
        """Devuelve `FAQMatch` si la query matchea arriba del threshold; si no, None."""
        raise NotImplementedError("FAQMatcher.match pendiente de implementación (Task 3)")

    def _reload_if_changed(self) -> bool:
        """Recarga el archivo si su mtime cambió desde la última carga. Devuelve True si recargó."""
        raise NotImplementedError("FAQMatcher._reload_if_changed pendiente de implementación (Task 3)")
