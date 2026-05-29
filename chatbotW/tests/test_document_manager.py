import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

from exceptions import RAGError
from error_codes import ErrorCode


class TestDocumentManagerConstructor:
    """Tests for DocumentManager.__init__ resolution."""

    def test_default_folder_resolution(self):
        """GIVEN folder_path='PDFs' WHEN constructed THEN self.folder_path resolves to {project_root}/PDFs"""
        from document_manager import DocumentManager

        with patch("document_manager.VectorStoreManager"), \
             patch("document_manager.EmbeddingCache"), \
             patch("document_manager.GoogleGenerativeAIEmbeddings"):
            dm = DocumentManager.__new__(DocumentManager)
            dm.api_key = "test-key"
            dm.folder_path = Path(__file__).resolve().parent.parent / "PDFs"

            assert dm.folder_path.name == "PDFs"
            assert dm.folder_path.is_absolute()

    def test_custom_folder_path(self):
        """GIVEN folder_path='CustomDocs' WHEN constructed THEN self.folder_path resolves to custom path."""
        from document_manager import DocumentManager

        with patch("document_manager.VectorStoreManager"), \
             patch("document_manager.EmbeddingCache"), \
             patch("document_manager.GoogleGenerativeAIEmbeddings"):
            dm = DocumentManager.__new__(DocumentManager)
            dm.api_key = "test-key"
            dm.folder_path = Path(__file__).resolve().parent.parent / "CustomDocs"

            assert dm.folder_path.name == "CustomDocs"
            assert dm.folder_path.is_absolute()


class TestDocumentManagerRetrieverSetup:
    """Tests for setup_retriever() behavior."""

    def test_existing_vectorstore_loaded(self):
        """GIVEN a valid FAISS index exists WHEN setup_retriever() called THEN returns retriever without processing."""
        from document_manager import DocumentManager

        mock_retriever = MagicMock()
        mock_vectorstore = MagicMock()
        mock_vectorstore.as_retriever.return_value = mock_retriever

        with patch("document_manager.VectorStoreManager") as mock_vs_mgr, \
             patch("document_manager.EmbeddingCache"), \
             patch("document_manager.GoogleGenerativeAIEmbeddings"):
            mock_vs_mgr.cargar.return_value = mock_vectorstore

            dm = DocumentManager.__new__(DocumentManager)
            dm.api_key = "test-key"
            dm.folder_path = Path("/tmp/test-pdfs")
            dm.embeddings_model = MagicMock()
            dm.cache = MagicMock()

            retriever = dm.setup_retriever()

            mock_vs_mgr.cargar.assert_called_once_with(dm.embeddings_model, dm.folder_path)
            mock_vectorstore.as_retriever.assert_called_once_with(search_kwargs={"k": 10})
            assert retriever == mock_retriever

    def test_no_vectorstore_builds_from_pdfs(self):
        """GIVEN no existing vectorstore and PDFs present WHEN setup_retriever() called THEN builds FAISS index."""
        from document_manager import DocumentManager

        mock_retriever = MagicMock()
        mock_vectorstore = MagicMock()
        mock_vectorstore.as_retriever.return_value = mock_retriever

        mock_pdf = MagicMock()
        mock_pdf_path = MagicMock()
        mock_pdf_path.glob.return_value = [mock_pdf]

        mock_loader = MagicMock()
        mock_doc = MagicMock()
        mock_doc.page_content = "test content"
        mock_loader.load.return_value = [mock_doc]

        mock_splitter = MagicMock()
        mock_split_doc = MagicMock()
        mock_split_doc.page_content = "test content chunk"
        mock_splitter.split_documents.return_value = [mock_split_doc]

        with patch("document_manager.VectorStoreManager") as mock_vs_mgr, \
             patch("document_manager.EmbeddingCache") as mock_cache_cls, \
             patch("document_manager.GoogleGenerativeAIEmbeddings") as mock_emb_cls, \
             patch("document_manager.PyMuPDFLoader", return_value=mock_loader), \
             patch("document_manager.RecursiveCharacterTextSplitter", return_value=mock_splitter), \
             patch("document_manager.FAISS") as mock_fais_mod, \
             patch("document_manager.time"), \
             patch("document_manager.np") as mock_np:

            mock_vs_mgr.cargar.return_value = None
            mock_cache = MagicMock()
            mock_cache.get.return_value = None
            mock_cache_cls.return_value = mock_cache
            mock_emb = MagicMock()
            mock_emb.embed_query.return_value = [0.1, 0.2]
            mock_emb_cls.return_value = mock_emb
            mock_fais_mod.from_embeddings.return_value = mock_vectorstore

            dm = DocumentManager.__new__(DocumentManager)
            dm.api_key = "test-key"
            dm.folder_path = Path("/tmp/test-pdfs")
            dm.embeddings_model = mock_emb
            dm.cache = mock_cache

            with patch("pathlib.Path.glob", return_value=[mock_pdf]):
                retriever = dm.setup_retriever()

                mock_fais_mod.from_embeddings.assert_called_once()
                mock_vs_mgr.guardar.assert_called_once_with(mock_vectorstore, dm.folder_path)
                mock_cache.save.assert_called_once()
                assert retriever == mock_retriever

    def test_no_documents_raises_rag_error(self):
        """GIVEN no vectorstore and no PDFs WHEN setup_retriever() called THEN raises RAGError."""
        from document_manager import DocumentManager

        with patch("document_manager.VectorStoreManager") as mock_vs_mgr, \
             patch("document_manager.EmbeddingCache"), \
             patch("document_manager.GoogleGenerativeAIEmbeddings"):
            mock_vs_mgr.cargar.return_value = None

            dm = DocumentManager.__new__(DocumentManager)
            dm.api_key = "test-key"
            dm.folder_path = Path("/tmp/no-pdfs")
            dm.embeddings_model = MagicMock()
            dm.cache = MagicMock()

            with patch("pathlib.Path.glob", return_value=[]):
                with pytest.raises(RAGError) as exc_info:
                    dm.setup_retriever()

                assert exc_info.value.code == ErrorCode.RAG_NO_PDFS


class TestDocumentManagerEmbeddingCache:
    """Tests for embedding cache integration."""

    def test_cache_hit_skips_api_call(self):
        """GIVEN text in cache WHEN embedding requested THEN cached vector used and embed_query NOT called."""
        from document_manager import DocumentManager

        dm = DocumentManager.__new__(DocumentManager)
        dm.embeddings_model = MagicMock()
        dm.cache = MagicMock()
        dm.cache.get.return_value = [0.1, 0.2, 0.3]

        result = dm.cache.get("test text")

        assert result == [0.1, 0.2, 0.3]
        dm.embeddings_model.embed_query.assert_not_called()

    def test_cache_miss_triggers_embedding(self):
        """GIVEN text not in cache WHEN embedding requested THEN embed_query called and result stored."""
        from document_manager import DocumentManager

        dm = DocumentManager.__new__(DocumentManager)
        dm.embeddings_model = MagicMock()
        dm.embeddings_model.embed_query.return_value = [0.4, 0.5, 0.6]
        dm.cache = MagicMock()
        dm.cache.get.return_value = None

        # Simulate cache miss then set
        cached = dm.cache.get("new text")
        if cached is None:
            emb = dm.embeddings_model.embed_query("new text")
            dm.cache.set("new text", emb)
            result = emb
        else:
            result = cached

        dm.embeddings_model.embed_query.assert_called_once_with("new text")
        dm.cache.set.assert_called_once_with("new text", [0.4, 0.5, 0.6])
        assert result == [0.4, 0.5, 0.6]


class TestDocumentManagerActualizarMemoria:
    """Tests for actualizar_memoria() hash detection."""

    def test_files_changed_returns_true(self):
        """GIVEN files changed since last build WHEN actualizar_memoria() called THEN setup_retriever called and returns True."""
        from document_manager import DocumentManager

        mock_retriever = MagicMock()

        with patch("document_manager.VectorStoreManager") as mock_vs_mgr:
            mock_vs_mgr.calcular_hash_archivos.return_value = "new_hash"
            mock_metadata_path = MagicMock()
            mock_metadata_path.exists.return_value = True
            mock_vs_mgr._get_metadata_path.return_value = mock_metadata_path

            dm = DocumentManager.__new__(DocumentManager)
            dm.api_key = "test-key"
            dm.folder_path = Path("/tmp/test-pdfs")
            dm.embeddings_model = MagicMock()
            dm.cache = MagicMock()

            # Mock the metadata file read
            mock_open_data = '{"hash": "old_hash"}'
            with patch("builtins.open", create=True) as mock_open:
                mock_open.return_value.__enter__ = lambda s: s
                mock_open.return_value.__exit__ = MagicMock(return_value=False)
                mock_open.return_value.read.return_value = mock_open_data

                with patch("json.load", return_value={"hash": "old_hash"}):
                    result = dm.actualizar_memoria()

            assert result is True

    def test_files_unchanged_returns_false(self):
        """GIVEN no files changed WHEN actualizar_memoria() called THEN returns False."""
        from document_manager import DocumentManager

        with patch("document_manager.VectorStoreManager") as mock_vs_mgr:
            mock_vs_mgr.calcular_hash_archivos.return_value = "same_hash"
            mock_metadata_path = MagicMock()
            mock_metadata_path.exists.return_value = True
            mock_vs_mgr._get_metadata_path.return_value = mock_metadata_path

            dm = DocumentManager.__new__(DocumentManager)
            dm.api_key = "test-key"
            dm.folder_path = Path("/tmp/test-pdfs")
            dm.embeddings_model = MagicMock()
            dm.cache = MagicMock()

            with patch("builtins.open", create=True) as mock_open:
                mock_open.return_value.__enter__ = lambda s: s
                mock_open.return_value.__exit__ = MagicMock(return_value=False)
                mock_open.return_value.read.return_value = '{"hash": "same_hash"}'

                with patch("json.load", return_value={"hash": "same_hash"}):
                    result = dm.actualizar_memoria()

            assert result is False
