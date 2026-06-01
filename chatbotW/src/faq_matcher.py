"""Matcheo semántico de consultas del usuario contra FAQs del operador.

Lee `faqs.json` desde disco, embebe cada `pregunta` con Gemini y compara
contra el embedding de la consulta por cosine similarity. Hot-reload
automático por mtime. Tolerante a archivo inexistente, JSON inválido,
filas mal formadas o fallos de la API de embeddings: en cada caso loggea
un warning y degrada a "sin match" sin tirar el bot.

Historia de diseño: ver `openspec/changes/add-faq-admin-table/design.md`,
sección "Interfaces / Contracts".
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

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

    def __init__(self, faqs_path: Path, embeddings_model, config_manager, logger=None):
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
        try:
            self._reload_if_changed()
        except Exception as e:
            # Defensa de último recurso: __init__ jamás debe tirar.
            self.logger.warning("FAQMatcher init error no controlado", detail=str(e))
            self._rows = []
            self._disabled = True

    def _read_threshold(self) -> float:
        """Lee el threshold desde ConfigManager. Out-of-range → fallback a DEFAULT_THRESHOLD."""
        # Re-leemos la config en cada llamada (live edits del admin).
        try:
            self.config_manager.cargar()
        except Exception as e:
            self.logger.warning("No se pudo recargar config_manager en FAQMatcher", detail=str(e))

        v = self.config_manager.config.get("faq_threshold", DEFAULT_THRESHOLD)
        try:
            v = float(v)
        except (TypeError, ValueError):
            self.logger.warning("faq_threshold no es numérico, usando default", valor=str(v))
            return DEFAULT_THRESHOLD
        if not (0.0 <= v <= 1.0):
            self.logger.warning("faq_threshold fuera de rango, usando default", valor=v)
            return DEFAULT_THRESHOLD
        return v

    def _reload_if_changed(self) -> bool:
        """Recarga `faqs.json` si su mtime cambió. Devuelve True si recargó.

        Comportamiento por modo:
        - FileNotFoundError: rows=[], mtime=0.0 (silencioso).
        - JSONDecodeError / OSError: warn, rows=[], mtime se mantiene.
        - Fila malformada (faltan keys o tipos incorrectos): se descarta
          con warning por fila, las demás siguen.
        - Embedding falla durante reload: warn, _disabled=True, rows=[].
        """
        path = self.faqs_path
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            # Archivo ausente: estado vacío silencioso.
            self._rows = []
            self._mtime = 0.0
            return True
        except OSError as e:
            self.logger.warning("No se pudo leer mtime de faqs.json", detail=str(e))
            self._rows = []
            return False

        if mtime == self._mtime and self._rows is not None:
            return False

        # Parseamos el archivo.
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            self.logger.warning("faqs.json inválido o ilegible, matcher sin filas", detail=str(e))
            self._rows = []
            self._mtime = mtime
            return True

        if not isinstance(raw, list):
            self.logger.warning("faqs.json no es una lista, matcher sin filas", tipo=type(raw).__name__)
            self._rows = []
            self._mtime = mtime
            return True

        # Filtramos filas malformadas.
        valid_rows = []
        for i, row in enumerate(raw):
            if not isinstance(row, dict):
                self.logger.warning("Fila FAQ descartada (no es dict)", indice=i)
                continue
            pregunta = row.get("pregunta")
            respuesta = row.get("respuesta")
            faq_id = row.get("id")
            if (
                not isinstance(pregunta, str)
                or not isinstance(respuesta, str)
                or not isinstance(faq_id, str)
            ):
                self.logger.warning("Fila FAQ descartada (campos faltantes o de tipo incorrecto)", indice=i)
                continue
            valid_rows.append({"id": faq_id, "pregunta": pregunta, "respuesta": respuesta})

        # Embebemos las preguntas válidas. Si una sola falla, el matcher se rinde.
        new_state = []
        for row in valid_rows:
            try:
                vec = self.embeddings_model.embed_query(row["pregunta"])
                arr = np.asarray(vec, dtype=float)
            except Exception as e:
                self.logger.warning(
                    "Embedding falló durante reload, matcher se deshabilita",
                    detail=str(e),
                )
                self._disabled = True
                self._rows = []
                self._mtime = mtime
                return True
            new_state.append(_Row(row["id"], row["pregunta"], row["respuesta"], arr))

        self._rows = new_state
        self._mtime = mtime
        self._disabled = False
        return True

    def match(self, query: str) -> Optional[FAQMatch]:
        """Devuelve `FAQMatch` si la query matchea arriba del threshold; si no, None.

        Pasos:
        1. None si la query está vacía.
        2. Hot-reload por mtime.
        3. None si no hay filas o si el matcher está deshabilitado.
        4. Embebe la query. Si falla: warn + None (sin matar el bot).
        5. argmax(cosine(q, row.vec)) sobre todas las filas.
        6. Si score >= threshold: FAQMatch(...). Si no: None.
        """
        if not query or not str(query).strip():
            return None
        if self._disabled or not self._rows:
            return None

        # Hot-reload por mtime antes de cada match.
        try:
            self._reload_if_changed()
        except Exception as e:
            self.logger.warning("Reload durante match falló, usando estado cacheado", detail=str(e))

        # Si el reload deshabilitó el matcher o vació las filas, salimos.
        if self._disabled or not self._rows:
            return None

        # Embed de la query.
        try:
            q_vec = np.asarray(self.embeddings_model.embed_query(query), dtype=float)
        except Exception as e:
            # Spec: per-query embedding failure is isolated. Warn + None para ESTA query.
            self.logger.warning("Embedding falló en match(), consulta cae a RAG", detail=str(e))
            return None

        # argmax por cosine.
        best = None
        best_score = -1.0
        for row in self._rows:
            score = _cosine(q_vec, row.vec)
            if score > best_score:
                best_score = score
                best = row

        threshold = self._read_threshold()
        if best is None or best_score < threshold:
            return None

        self.logger.info(
            "FAQ match",
            matched_id=best.id,
            score=round(best_score, 4),
            threshold=threshold,
        )
        return FAQMatch(
            id=best.id,
            pregunta=best.pregunta,
            respuesta=best.respuesta,
            score=best_score,
        )


# ────────────────────────────────────────────────────────────────────────
# Internals
# ────────────────────────────────────────────────────────────────────────

@dataclass
class _Row:
    """Fila interna del matcher: incluye el vector embebido."""
    id: str
    pregunta: str
    respuesta: str
    vec: np.ndarray


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity. Defensivo: si alguna norma es 0, devuelve 0.0."""
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))
