from pathlib import Path
import json
import hashlib
from logging_config import get_logger

logger = get_logger("embedding_cache")


class EmbeddingCache:
    def __init__(self):
        # BASE DEL PROYECTO
        base_path = Path(__file__).resolve().parent.parent

        # CARPETA CACHE
        self.cache_dir = base_path / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # ARCHIVO CACHE
        self.cache_file = self.cache_dir / "embeddings_cache.json"

        # CARGAR CACHE
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
            except (json.JSONDecodeError, OSError):
                logger.warning("Embedding cache corrupt, resetting")
                self.cache = {}
        else:
            self.cache = {}

    def _hash(self, text):
        return hashlib.md5(text.encode()).hexdigest()

    def get(self, text):
        return self.cache.get(self._hash(text))

    def set(self, text, embedding):
        self.cache[self._hash(text)] = embedding

    def save(self):
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(self.cache, f)