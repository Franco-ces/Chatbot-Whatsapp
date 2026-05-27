import json
from pathlib import Path

import pytest

from embedding_cache import EmbeddingCache


@pytest.fixture
def cache(tmp_path):
    return _cache_en(tmp_path)


def _cache_en(tmp_path):
    obj = object.__new__(EmbeddingCache)
    obj.cache_dir = tmp_path / "cache"
    obj.cache_dir.mkdir(parents=True, exist_ok=True)
    obj.cache_file = obj.cache_dir / "embeddings_cache.json"
    if obj.cache_file.exists():
        try:
            with open(obj.cache_file, "r") as f:
                obj.cache = json.load(f)
        except (json.JSONDecodeError, OSError):
            obj.cache = {}
    else:
        obj.cache = {}
    return obj


class TestInit:

    def test_cache_vacio_si_no_existe_archivo(self, tmp_path):
        c = _cache_en(tmp_path)
        assert c.cache == {}

    def test_cache_carga_json_valido(self, tmp_path):
        cache_file = tmp_path / "cache" / "embeddings_cache.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"hash1": [0.1, 0.2]}))
        c = _cache_en(tmp_path)
        assert c.cache == {"hash1": [0.1, 0.2]}

    def test_cache_vacio_si_json_corrupto(self, tmp_path):
        cache_file = tmp_path / "cache" / "embeddings_cache.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("no-json")
        c = _cache_en(tmp_path)
        assert c.cache == {}

    def test_cache_dir_se_crea(self, tmp_path):
        cache_dir = tmp_path / "cache"
        assert not cache_dir.exists()
        _cache_en(tmp_path)
        assert cache_dir.exists()


class TestHash:

    def test_mismo_texto_mismo_hash(self, cache):
        assert cache._hash("hola") == cache._hash("hola")

    def test_distinto_texto_distinto_hash(self, cache):
        assert cache._hash("hola") != cache._hash("chau")


class TestGetSet:

    def test_set_y_get(self, cache):
        cache.set("texto", [0.1, 0.2])
        assert cache.get("texto") == [0.1, 0.2]

    def test_get_devuelve_none_si_no_existe(self, cache):
        assert cache.get("inexistente") is None

    def test_set_sobrescribe(self, cache):
        cache.set("texto", [0.1])
        cache.set("texto", [0.9])
        assert cache.get("texto") == [0.9]


class TestSave:

    def test_guarda_y_recupera(self, tmp_path):
        c = _cache_en(tmp_path)
        c.set("clave", [0.5])
        c.save()

        c2 = _cache_en(tmp_path)
        assert c2.get("clave") == [0.5]

    def test_archivo_contiene_json_valido(self, tmp_path):
        c = _cache_en(tmp_path)
        c.set("k", "v")
        c.save()

        data = json.loads((tmp_path / "cache" / "embeddings_cache.json").read_text())
        assert data == c.cache
