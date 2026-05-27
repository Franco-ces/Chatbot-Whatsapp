import json
from pathlib import Path

import pytest

from vectorstore_manager import VectorStoreManager


@pytest.fixture
def pdf_folder(tmp_path):
    folder = tmp_path / "pdfs"
    folder.mkdir()
    return folder


def _setup(mocker, tmp_path):
    vs_path = tmp_path / "vectorstore"
    vs_path.mkdir()
    meta_path = vs_path / "metadata.json"
    mocker.patch.object(VectorStoreManager, "_get_vectorstore_path", return_value=vs_path)
    mocker.patch.object(VectorStoreManager, "_get_metadata_path", return_value=meta_path)
    return vs_path, meta_path


class TestCalcularHash:

    def test_mismo_contenido_mismo_hash(self, pdf_folder):
        (pdf_folder / "doc.pdf").write_text("contenido")
        (pdf_folder / "precios.json").write_text('{"p": 1}')
        hash1 = VectorStoreManager.calcular_hash_archivos(pdf_folder)
        hash2 = VectorStoreManager.calcular_hash_archivos(pdf_folder)
        assert hash1 == hash2

    def test_distintos_archivos_distinto_hash(self, pdf_folder):
        (pdf_folder / "doc.pdf").write_text("contenido")
        hash_a = VectorStoreManager.calcular_hash_archivos(pdf_folder)
        (pdf_folder / "otro.pdf").write_text("otro")
        hash_b = VectorStoreManager.calcular_hash_archivos(pdf_folder)
        assert hash_a != hash_b


class TestCargar:

    def test_retorna_none_si_no_existe_vectorstore(self, mocker, tmp_path):
        vs_path = tmp_path / "vectorstore"
        mocker.patch.object(VectorStoreManager, "_get_vectorstore_path", return_value=vs_path)
        mocker.patch.object(VectorStoreManager, "_get_metadata_path", return_value=vs_path / "metadata.json")

        result = VectorStoreManager.cargar(None, tmp_path)
        assert result is None

    def test_retorna_none_si_no_existe_metadata(self, mocker, tmp_path):
        vs_path = tmp_path / "vectorstore"
        vs_path.mkdir()
        mocker.patch.object(VectorStoreManager, "_get_vectorstore_path", return_value=vs_path)
        mocker.patch.object(VectorStoreManager, "_get_metadata_path", return_value=vs_path / "metadata.json")

        result = VectorStoreManager.cargar(None, tmp_path)
        assert result is None

    def test_retorna_none_si_metadata_corrupto(self, mocker, tmp_path):
        vs_path, meta_path = _setup(mocker, tmp_path)
        meta_path.write_text("esto no es json")

        result = VectorStoreManager.cargar(None, tmp_path)
        assert result is None

    def test_retorna_none_si_hash_no_coincide(self, mocker, tmp_path, pdf_folder):
        vs_path, meta_path = _setup(mocker, tmp_path)
        (pdf_folder / "doc.pdf").write_text("original")
        meta_path.write_text(json.dumps({"hash": "hash_distinto"}))

        result = VectorStoreManager.cargar(None, pdf_folder)
        assert result is None

    def test_retorna_vectorstore_cuando_hash_coincide(self, mocker, tmp_path, pdf_folder):
        vs_path, meta_path = _setup(mocker, tmp_path)
        (pdf_folder / "doc.pdf").write_text("contenido")
        actual_hash = VectorStoreManager.calcular_hash_archivos(pdf_folder)
        meta_path.write_text(json.dumps({"hash": actual_hash}))

        mock_faiss = mocker.patch(
            "vectorstore_manager.FAISS.load_local",
            return_value="vectorstore_mockeado",
        )

        result = VectorStoreManager.cargar("embeddings_mock", pdf_folder)

        assert result == "vectorstore_mockeado"
        mock_faiss.assert_called_once_with(
            str(vs_path),
            "embeddings_mock",
            allow_dangerous_deserialization=True,
        )

    def test_retorna_none_si_faiss_load_falla(self, mocker, tmp_path, pdf_folder):
        vs_path, meta_path = _setup(mocker, tmp_path)
        (pdf_folder / "doc.pdf").write_text("contenido")
        actual_hash = VectorStoreManager.calcular_hash_archivos(pdf_folder)
        meta_path.write_text(json.dumps({"hash": actual_hash}))

        mocker.patch(
            "vectorstore_manager.FAISS.load_local",
            side_effect=RuntimeError("FAISS corrupto"),
        )

        result = VectorStoreManager.cargar("embeddings_mock", pdf_folder)
        assert result is None
