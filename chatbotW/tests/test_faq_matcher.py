"""Tests para `FAQMatcher` (Task 2 + 3).

Cubre los escenarios del spec `faq-matcher`:
- Init missing / malformed / empty / valid
- Hit / miss / empty-query / no-rows
- Hot reload via mtime (`os.utime`)
- Embed failure en init (matcher disabled)
- Embed failure por query (solo esa consulta cae, las demás siguen)
- Threshold default 0.88, custom override, fallback por out-of-range
- `config_manager.cargar()` se llama en CADA `match()` (lectura por consulta)
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest


# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────

def _make_embedder(vectors_by_text: dict | None = None, side_effect=None, dim: int | None = None):
    """Devuelve un mock con `embed_query(text) -> list[float]`.

    Si `vectors_by_text` está dado, devuelve el vector asociado al texto
    y para los demás textos devuelve un vector de la MISMA dimensión
    (la del primer valor del dict, o `dim` si se pasa explícito).
    Si `side_effect` está dado, se aplica como `side_effect` (útil para
    simular que la API lanza una excepción).
    """
    embedder = MagicMock(name="embeddings_model")
    if side_effect is not None:
        embedder.embed_query.side_effect = side_effect
        return embedder

    # Si el caller pasó un dict, usamos la dimensión del primer vector
    # para mantener consistencia entre init y match.
    effective_dim = dim
    if effective_dim is None and vectors_by_text:
        first = next(iter(vectors_by_text.values()))
        effective_dim = len(first)
    if effective_dim is None:
        effective_dim = 8  # fallback razonable

    def _embed(text: str):
        if vectors_by_text and text in vectors_by_text:
            return vectors_by_text[text]
        # Vector base (canónico) de la dimensión correcta
        return [1.0 if i == 0 else 0.0 for i in range(effective_dim)]

    embedder.embed_query.side_effect = _embed
    return embedder


def _make_config_manager(threshold=0.88, side_effect=None):
    """Devuelve un mock de ConfigManager con `cargar()` y `config`."""
    cm = MagicMock(name="config_manager")
    cm.config = {"faq_threshold": threshold}
    if side_effect is not None:
        cm.cargar.side_effect = side_effect
    else:
        cm.cargar.return_value = None
    return cm


def _write_faqs(path: Path, rows: list) -> None:
    """Escribe una lista de FAQs (sin ids si no las tienen) en `path`."""
    with_ids = []
    for i, row in enumerate(rows):
        full = {"id": row.get("id", f"id-{i}"), "pregunta": row["pregunta"], "respuesta": row["respuesta"]}
        with_ids.append(full)
    path.write_text(json.dumps(with_ids, ensure_ascii=False), encoding="utf-8")


# ────────────────────────────────────────────────────────────────────────
# Init / startup resilience
# ────────────────────────────────────────────────────────────────────────

class TestFAQMatcherInit:
    def test_init_archivo_inexistente_no_falla(self, tmp_path):
        """Spec: Missing file at startup → 0 rows, no error."""
        from faq_matcher import FAQMatcher

        path = tmp_path / "no_existe.json"
        matcher = FAQMatcher(
            faqs_path=path,
            embeddings_model=_make_embedder(),
            config_manager=_make_config_manager(),
            logger=MagicMock(),
        )

        assert path.exists() is False
        assert matcher._rows == []  # 0 filas cargadas

    def test_init_archivo_vacio_no_falla(self, tmp_path):
        """Spec: Empty file at startup → 0 rows, no error."""
        from faq_matcher import FAQMatcher

        path = tmp_path / "faqs.json"
        path.write_text("[]", encoding="utf-8")

        matcher = FAQMatcher(
            faqs_path=path,
            embeddings_model=_make_embedder(),
            config_manager=_make_config_manager(),
            logger=MagicMock(),
        )

        assert matcher._rows == []

    def test_init_json_malformado_no_falla(self, tmp_path):
        """Spec: Malformed JSON at startup → warn, 0 rows, no crash."""
        from faq_matcher import FAQMatcher

        path = tmp_path / "faqs.json"
        path.write_text("{ esto no es json válido", encoding="utf-8")
        logger = MagicMock()

        matcher = FAQMatcher(
            faqs_path=path,
            embeddings_model=_make_embedder(),
            config_manager=_make_config_manager(),
            logger=logger,
        )

        assert matcher._rows == []
        # Se loggea la advertencia
        logger.warning.assert_called()

    def test_init_archivo_valido_carga_filas(self, tmp_path):
        """Spec: Valid file at startup → filas con pregunta, respuesta, id, vector."""
        from faq_matcher import FAQMatcher

        path = tmp_path / "faqs.json"
        _write_faqs(path, [
            {"pregunta": "¿Cuánto sale el Samsung A54?", "respuesta": "$520.000"},
            {"pregunta": "¿Horario de atención?", "respuesta": "Lun a Vie 9-18hs"},
        ])

        embedder = _make_embedder()
        matcher = FAQMatcher(
            faqs_path=path,
            embeddings_model=embedder,
            config_manager=_make_config_manager(),
            logger=MagicMock(),
        )

        # Se embebeó una vez por cada fila durante init
        assert embedder.embed_query.call_count == 2
        assert len(matcher._rows) == 2
        assert matcher._rows[0].pregunta == "¿Cuánto sale el Samsung A54?"
        assert matcher._rows[0].respuesta == "$520.000"
        assert matcher._rows[1].pregunta == "¿Horario de atención?"

    def test_init_fila_malformada_se_descarta_con_warning(self, tmp_path):
        """Fila sin `pregunta` o `respuesta` (o de tipo incorrecto) → se descarta."""
        from faq_matcher import FAQMatcher

        path = tmp_path / "faqs.json"
        path.write_text(json.dumps([
            {"id": "ok", "pregunta": "P1", "respuesta": "R1"},
            {"id": "bad1", "pregunta": "P2"},  # falta respuesta
            {"id": "bad2", "pregunta": 123, "respuesta": "R3"},  # pregunta no es str
            {"id": "ok2", "pregunta": "P4", "respuesta": "R4"},
        ]), encoding="utf-8")
        logger = MagicMock()

        matcher = FAQMatcher(
            faqs_path=path,
            embeddings_model=_make_embedder(),
            config_manager=_make_config_manager(),
            logger=logger,
        )

        # Solo las 2 filas válidas sobreviven
        assert len(matcher._rows) == 2
        # Se loggea al menos un warning por las filas inválidas
        assert logger.warning.call_count >= 1


# ────────────────────────────────────────────────────────────────────────
# Match: hit / miss / empty / no rows
# ────────────────────────────────────────────────────────────────────────

class TestFAQMatcherMatch:
    @pytest.fixture
    def matcher(self, tmp_path):
        """Matcher con 2 FAQs cuyas preguntas son vectores ortogonales."""
        from faq_matcher import FAQMatcher

        path = tmp_path / "faqs.json"
        _write_faqs(path, [
            {"pregunta": "P1", "respuesta": "R1"},
            {"pregunta": "P2", "respuesta": "R2"},
        ])

        # Vector para la query idéntico al de P1 → cosine = 1.0
        v_p1 = [1.0, 0.0, 0.0, 0.0]
        # Vector ortogonal → cosine = 0
        v_ortho = [0.0, 1.0, 0.0, 0.0]
        embedder = _make_embedder(vectors_by_text={"P1": v_p1, "P2": v_ortho})
        return FAQMatcher(
            faqs_path=path,
            embeddings_model=embedder,
            config_manager=_make_config_manager(threshold=0.88),
            logger=MagicMock(),
        )

    def test_match_query_vacia_devuelve_none(self, matcher):
        """Spec: query vacía o solo whitespace → no match."""
        assert matcher.match("") is None
        assert matcher.match("   ") is None
        assert matcher.match(None) is None

    def test_match_arriba_del_umbral_retorna_faqmatch(self, matcher):
        """Spec: cosine = 1.0 ≥ 0.88 → hit, devuelve el row correspondiente."""
        from faq_matcher import FAQMatch

        # La query se embebe con el mismo vector que P1
        result = matcher.match("texto cualquiera")
        assert result is not None
        assert isinstance(result, FAQMatch)
        assert result.pregunta == "P1"
        assert result.respuesta == "R1"
        assert result.score == pytest.approx(1.0)

    def test_match_debajo_del_umbral_devuelve_none(self, tmp_path):
        """Spec: cosine < threshold → no match (fallthrough a RAG)."""
        from faq_matcher import FAQMatcher

        path = tmp_path / "faqs.json"
        _write_faqs(path, [{"pregunta": "P1", "respuesta": "R1"}])
        v_p1 = [1.0, 0.0, 0.0, 0.0]
        v_ortho = [0.0, 1.0, 0.0, 0.0]
        embedder = _make_embedder(vectors_by_text={"P1": v_p1})

        matcher = FAQMatcher(
            faqs_path=path,
            embeddings_model=embedder,
            config_manager=_make_config_manager(threshold=0.88),
            logger=MagicMock(),
        )
        # Override: ahora la query embebe ortogonal → cosine 0
        embedder.embed_query.side_effect = lambda text: v_ortho

        result = matcher.match("otra cosa")
        assert result is None

    def test_match_sin_filas_devuelve_none(self, tmp_path):
        """Spec: faqs.json == [] → no match para cualquier query."""
        from faq_matcher import FAQMatcher

        path = tmp_path / "faqs.json"
        path.write_text("[]", encoding="utf-8")
        matcher = FAQMatcher(
            faqs_path=path,
            embeddings_model=_make_embedder(),
            config_manager=_make_config_manager(),
            logger=MagicMock(),
        )

        assert matcher.match("cualquier cosa") is None
        # embedder NO se llamó porque no hay nada con qué comparar
        matcher.embeddings_model.embed_query.assert_not_called()

    def test_match_miss_loggea_score_matched_id_none_returned_false(self, tmp_path):
        """Spec query-processor delta:50-54: Miss is logged with best score and no id.

        GIVEN a query that scores below threshold WHEN match() returns None
        THEN a structured log line records score=<best>, matched_id=None, returned=False.
        """
        from faq_matcher import FAQMatcher

        path = tmp_path / "faqs.json"
        _write_faqs(path, [{"id": "p1", "pregunta": "P1", "respuesta": "R1"}])
        v_p1 = [1.0, 0.0, 0.0, 0.0]
        v_ortho = [0.0, 1.0, 0.0, 0.0]  # cosine 0 vs v_p1
        embedder = _make_embedder(vectors_by_text={"P1": v_p1})

        logger = MagicMock()
        matcher = FAQMatcher(
            faqs_path=path,
            embeddings_model=embedder,
            config_manager=_make_config_manager(threshold=0.88),
            logger=logger,
        )
        # Override DESPUÉS de init: en match(), la query embebe ortogonal → cosine 0 → miss.
        embedder.embed_query.side_effect = lambda text: v_ortho

        result = matcher.match("consulta sin match")
        assert result is None  # miss

        # Buscamos el call con returned=False y matched_id=None
        miss_call = None
        for call in logger.info.call_args_list:
            kwargs = call.kwargs
            if kwargs.get("returned") is False and kwargs.get("matched_id") is None:
                miss_call = call
                break
        assert miss_call is not None, (
            f"Expected miss log call with returned=False, matched_id=None; "
            f"got: {logger.info.call_args_list}"
        )
        # El score debe estar presente y ser numérico (0.0 en este caso)
        assert "score" in miss_call.kwargs
        assert isinstance(miss_call.kwargs["score"], (int, float))

    def test_match_hit_loggea_score_matched_id_returned_true(self, tmp_path):
        """Spec query-processor delta:44-48: Match is logged with score and id.

        GIVEN a query that matches a FAQ row with cosine ≥ threshold
        WHEN match() returns FAQMatch THEN a structured log line records
        score=<cosine>, matched_id=<id>, returned=True.
        """
        from faq_matcher import FAQMatcher, FAQMatch

        path = tmp_path / "faqs.json"
        _write_faqs(path, [{"id": "p1", "pregunta": "P1", "respuesta": "R1"}])
        v_p1 = [1.0, 0.0, 0.0, 0.0]
        # Embedder devuelve el mismo vector para P1 y para la query → cosine 1.0
        embedder = _make_embedder(vectors_by_text={"P1": v_p1})
        embedder.embed_query.side_effect = lambda text: v_p1

        logger = MagicMock()
        matcher = FAQMatcher(
            faqs_path=path,
            embeddings_model=embedder,
            config_manager=_make_config_manager(threshold=0.88),
            logger=logger,
        )

        result = matcher.match("consulta con match")
        assert isinstance(result, FAQMatch)
        assert result.id == "p1"

        # Buscamos el call con returned=True y matched_id="p1"
        hit_call = None
        for call in logger.info.call_args_list:
            kwargs = call.kwargs
            if kwargs.get("returned") is True and kwargs.get("matched_id") == "p1":
                hit_call = call
                break
        assert hit_call is not None, (
            f"Expected hit log call with returned=True, matched_id='p1'; "
            f"got: {logger.info.call_args_list}"
        )
        assert "score" in hit_call.kwargs
        assert hit_call.kwargs["score"] == pytest.approx(1.0)


# ────────────────────────────────────────────────────────────────────────
# Threshold handling
# ────────────────────────────────────────────────────────────────────────

class TestFAQMatcherThreshold:
    def test_threshold_default_es_088_si_no_esta_en_config(self, tmp_path):
        """Spec: Default threshold is 0.88."""
        from faq_matcher import FAQMatcher

        path = tmp_path / "faqs.json"
        _write_faqs(path, [{"pregunta": "P1", "respuesta": "R1"}])
        v = [1.0, 0.0, 0.0, 0.0]
        embedder = _make_embedder(vectors_by_text={"P1": v})
        cm = _make_config_manager()  # no faq_threshold
        del cm.config["faq_threshold"]

        matcher = FAQMatcher(
            faqs_path=path,
            embeddings_model=embedder,
            config_manager=cm,
            logger=MagicMock(),
        )
        # El threshold efectivo es 0.88 → cosine 1.0 → hit
        result = matcher.match("x")
        assert result is not None
        assert result.score == pytest.approx(1.0)

    def test_threshold_custom_override_default(self, tmp_path):
        """Spec: Custom threshold overrides default."""
        from faq_matcher import FAQMatcher

        path = tmp_path / "faqs.json"
        _write_faqs(path, [{"pregunta": "P1", "respuesta": "R1"}])
        v_p1 = [1.0, 0.0, 0.0, 0.0]
        v_partial = [0.5, 0.5, 0.0, 0.0]  # cosine = 0.5 / (1*sqrt(0.5)) ≈ 0.707
        embedder = _make_embedder(vectors_by_text={"P1": v_p1})
        embedder.embed_query.side_effect = lambda text: v_partial

        cm = _make_config_manager(threshold=0.6)  # custom, < 0.707
        matcher = FAQMatcher(
            faqs_path=path,
            embeddings_model=embedder,
            config_manager=cm,
            logger=MagicMock(),
        )
        # 0.707 ≥ 0.6 → hit
        assert matcher.match("x") is not None

    def test_threshold_fuera_de_rango_cae_a_088(self, tmp_path):
        """Spec: out-of-range threshold → log warn + fallback a 0.88."""
        from faq_matcher import FAQMatcher

        path = tmp_path / "faqs.json"
        _write_faqs(path, [{"pregunta": "P1", "respuesta": "R1"}])
        v_p1 = [1.0, 0.0, 0.0, 0.0]
        embedder = _make_embedder(vectors_by_text={"P1": v_p1})
        embedder.embed_query.side_effect = lambda text: v_p1

        cm = _make_config_manager(threshold=1.5)  # fuera de rango
        logger = MagicMock()
        matcher = FAQMatcher(
            faqs_path=path,
            embeddings_model=embedder,
            config_manager=cm,
            logger=logger,
        )
        # Threshold efectivo = 0.88 → cosine 1.0 → hit
        result = matcher.match("x")
        assert result is not None
        # Y se loggeó un warning
        logger.warning.assert_called()

    def test_threshold_se_relee_en_cada_match(self, tmp_path):
        """Spec: `config_manager.cargar()` se llama en CADA `match()`."""
        from faq_matcher import FAQMatcher

        path = tmp_path / "faqs.json"
        _write_faqs(path, [{"pregunta": "P1", "respuesta": "R1"}])
        v_p1 = [1.0, 0.0, 0.0, 0.0]
        embedder = _make_embedder(vectors_by_text={"P1": v_p1})
        embedder.embed_query.side_effect = lambda text: v_p1
        cm = _make_config_manager(threshold=0.5)

        matcher = FAQMatcher(
            faqs_path=path,
            embeddings_model=embedder,
            config_manager=cm,
            logger=MagicMock(),
        )

        cm.cargar.reset_mock()
        matcher.match("a")
        matcher.match("b")
        matcher.match("c")

        # cargar() se llamó en cada match (3 veces, una por consulta)
        assert cm.cargar.call_count == 3

    def test_threshold_se_actualiza_en_runtime(self, tmp_path):
        """El operador cambia el threshold en disco → el siguiente match usa el nuevo."""
        from faq_matcher import FAQMatcher

        path = tmp_path / "faqs.json"
        _write_faqs(path, [{"pregunta": "P1", "respuesta": "R1"}])
        v_p1 = [1.0, 0.0, 0.0, 0.0]
        v_partial = [0.5, 0.5, 0.0, 0.0]  # cosine ~0.707

        # En init, embebemos P1 con v_p1 → row.vec = v_p1.
        # En match(), embebemos la query con v_partial → cos 0.707 con v_p1.
        phase = {"mode": "init"}
        def embed(text):
            return v_p1 if phase["mode"] == "init" else v_partial
        embedder = MagicMock()
        embedder.embed_query.side_effect = embed

        # ConfigManager mutable: el orquestador "edita" el threshold en runtime
        config_state = {"faq_threshold": 0.9}
        cm = MagicMock()
        cm.config = config_state
        cm.cargar.side_effect = lambda: None  # no-op, ya está en config_state

        matcher = FAQMatcher(
            faqs_path=path,
            embeddings_model=embedder,
            config_manager=cm,
            logger=MagicMock(),
        )
        assert len(matcher._rows) == 1

        # Threshold 0.9: cosine 0.707 < 0.9 → miss
        phase["mode"] = "match"
        assert matcher.match("x") is None

        # Operador baja el threshold a 0.5
        config_state["faq_threshold"] = 0.5
        # Ahora cosine 0.707 ≥ 0.5 → hit
        assert matcher.match("x") is not None


# ────────────────────────────────────────────────────────────────────────
# Hot reload (mtime)
# ────────────────────────────────────────────────────────────────────────

class TestFAQMatcherHotReload:
    def test_cambio_en_disco_se_refleja_en_proximo_match(self, tmp_path):
        """Spec: Edit is visible on the next match (sin reinicio)."""
        from faq_matcher import FAQMatcher

        path = tmp_path / "faqs.json"
        _write_faqs(path, [{"id": "p1", "pregunta": "vieja pregunta", "respuesta": "vieja respuesta"}])
        v_vieja = [1.0, 0.0, 0.0, 0.0]
        v_nueva = [0.0, 1.0, 0.0, 0.0]
        embedder = _make_embedder(vectors_by_text={
            "vieja pregunta": v_vieja,
            "nueva pregunta": v_nueva,
        })
        cm = _make_config_manager(threshold=0.88)

        matcher = FAQMatcher(
            faqs_path=path,
            embeddings_model=embedder,
            config_manager=cm,
            logger=MagicMock(),
        )

        # Antes del cambio: query embebe como v_vieja → matchea vieja pregunta
        embedder.embed_query.side_effect = lambda text: v_vieja
        result = matcher.match("x")
        assert result is not None
        assert result.respuesta == "vieja respuesta"

        # Operador edita la fila en el admin UI (escribe en disco)
        _write_faqs(path, [{"id": "p1", "pregunta": "nueva pregunta", "respuesta": "nueva respuesta"}])
        # Forzamos bump de mtime por si el FS tiene resolución de 1s
        st = path.stat()
        os.utime(path, (st.st_atime, st.st_mtime + 5))

        # Ahora la query embebe como v_nueva → matchea la nueva fila
        embedder.embed_query.side_effect = lambda text: v_nueva
        result = matcher.match("x")
        assert result is not None
        assert result.respuesta == "nueva respuesta"
        assert result.pregunta == "nueva pregunta"

    def test_archivo_borrado_en_runtime_vacia_las_filas(self, tmp_path):
        """Si el operador borra faqs.json, el siguiente match devuelve None."""
        from faq_matcher import FAQMatcher

        path = tmp_path / "faqs.json"
        _write_faqs(path, [{"pregunta": "P1", "respuesta": "R1"}])
        embedder = _make_embedder()
        cm = _make_config_manager()

        matcher = FAQMatcher(
            faqs_path=path,
            embeddings_model=embedder,
            config_manager=cm,
            logger=MagicMock(),
        )
        assert len(matcher._rows) == 1

        path.unlink()
        # Forzamos bump de mtime para que se dispare el reload
        # (en este caso el archivo no existe, así que getmtime fallará)
        result = matcher.match("x")
        assert result is None


# ────────────────────────────────────────────────────────────────────────
# Embedding API failures
# ────────────────────────────────────────────────────────────────────────

class TestFAQMatcherEmbeddingFailures:
    def test_embed_falla_en_init_matchers_queda_disabled(self, tmp_path):
        """Spec: Initial embedding call fails → matcher disabled, 0 rows, no crash."""
        from faq_matcher import FAQMatcher

        path = tmp_path / "faqs.json"
        _write_faqs(path, [{"pregunta": "P1", "respuesta": "R1"}])
        embedder = MagicMock()
        embedder.embed_query.side_effect = RuntimeError("API caída")
        logger = MagicMock()

        matcher = FAQMatcher(
            faqs_path=path,
            embeddings_model=embedder,
            config_manager=_make_config_manager(),
            logger=logger,
        )

        # 0 rows activas, matcher en estado disabled
        assert matcher._rows == []
        assert matcher._disabled is True
        # Se loggeó un warning
        logger.warning.assert_called()
        # match() devuelve None sin volver a llamar a embed_query
        embedder.embed_query.reset_mock()
        assert matcher.match("x") is None
        embedder.embed_query.assert_not_called()

    def test_embed_falla_en_una_sola_query_devuelve_none_para_esa(self, tmp_path):
        """Spec: Per-query embedding failure is isolated."""
        from faq_matcher import FAQMatcher

        path = tmp_path / "faqs.json"
        _write_faqs(path, [{"pregunta": "P1", "respuesta": "R1"}])
        v_p1 = [1.0, 0.0, 0.0, 0.0]

        # Init usa el dict → fila cargada OK con row.vec = v_p1.
        embedder = _make_embedder(vectors_by_text={"P1": v_p1})
        logger = MagicMock()

        matcher = FAQMatcher(
            faqs_path=path,
            embeddings_model=embedder,
            config_manager=_make_config_manager(threshold=0.88),
            logger=logger,
        )
        assert len(matcher._rows) == 1

        # Ahora en match, la primera llamada falla, la segunda pasa.
        match_calls = {"n": 0}
        def flaky_embed(text):
            match_calls["n"] += 1
            if match_calls["n"] == 1:
                raise RuntimeError("API rate limit")
            return v_p1
        embedder.embed_query.side_effect = flaky_embed

        # Primera query: embedding falla → matcher devuelve None (sin matar el bot).
        assert matcher.match("primera") is None
        # Segunda query: embedding pasa → hit.
        result = matcher.match("segunda")
        assert result is not None
        assert result.respuesta == "R1"
        # Se loggeó el warning del fallo.
        logger.warning.assert_called()


# ────────────────────────────────────────────────────────────────────────
# Sanity: dataclass y tipos públicos
# ────────────────────────────────────────────────────────────────────────

class TestFAQMatchDataclass:
    def test_faqmatch_tiene_campos_esperados(self):
        """Sanity: FAQMatch expone id/pregunta/respuesta/score."""
        from faq_matcher import FAQMatch

        m = FAQMatch(id="x", pregunta="p", respuesta="r", score=0.9)
        assert m.id == "x"
        assert m.pregunta == "p"
        assert m.respuesta == "r"
        assert m.score == 0.9
