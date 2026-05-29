import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

# Mock price_lookup before importing modules (pre-existing missing module)
sys.modules.setdefault("price_lookup", MagicMock())


class TestRAGOrchestratorConstructor:
    """Tests for RAGOrchestrator.__init__ initialization."""

    def test_constructor_creates_both_components(self):
        """GIVEN api_key='key', folder_path='PDFs' WHEN constructed THEN doc_manager and query_processor created."""
        with patch("rag_orchestrator.DocumentManager") as mock_dm_cls, \
             patch("rag_orchestrator.QueryProcessor") as mock_qp_cls:

            mock_dm = mock_dm_cls.return_value
            mock_dm.folder_path = Path("/tmp/PDFs")
            mock_dm.setup_retriever.return_value = MagicMock()

            from rag_orchestrator import RAGOrchestrator
            rag = RAGOrchestrator("key", folder_path="PDFs")

            mock_dm_cls.assert_called_once_with("key", "PDFs")
            mock_qp_cls.assert_called_once_with("key")
            assert rag.retriever is not None

    def test_constructor_with_custom_path(self):
        """GIVEN folder_path='CustomDocs' WHEN constructed THEN folder_path resolves correctly."""
        with patch("rag_orchestrator.DocumentManager") as mock_dm_cls, \
             patch("rag_orchestrator.QueryProcessor"):

            mock_dm = mock_dm_cls.return_value
            mock_dm.folder_path = Path("/tmp/CustomDocs")
            mock_dm.setup_retriever.return_value = MagicMock()

            from rag_orchestrator import RAGOrchestrator
            rag = RAGOrchestrator("key", folder_path="CustomDocs")

            mock_dm_cls.assert_called_once_with("key", "CustomDocs")
            assert rag.folder_path == Path("/tmp/CustomDocs")


class TestRAGOrchestratorPreguntar:
    """Tests for preguntar() delegation."""

    @pytest.fixture
    def mock_rag(self):
        """Create a RAGOrchestrator with mocked sub-components."""
        with patch("rag_orchestrator.DocumentManager") as mock_dm_cls, \
             patch("rag_orchestrator.QueryProcessor") as mock_qp_cls:

            mock_dm = mock_dm_cls.return_value
            mock_dm.folder_path = Path("/tmp/PDFs")
            mock_retriever = MagicMock()
            mock_dm.setup_retriever.return_value = mock_retriever

            mock_qp = mock_qp_cls.return_value
            mock_qp.procesar = AsyncMock(return_value=("transcripcion", "respuesta"))

            from rag_orchestrator import RAGOrchestrator
            rag = RAGOrchestrator("key")

            return rag, mock_qp, mock_retriever

    @pytest.mark.asyncio
    async def test_text_query_delegates_correctly(self, mock_rag):
        """GIVEN query_text='test' WHEN preguntar() called THEN query_processor.procesar() called with correct args."""
        rag, mock_qp, mock_retriever = mock_rag

        result = await rag.preguntar(query_text="test", audio_bytes=None, remitente="user123", session_manager=None)

        mock_qp.procesar.assert_called_once_with(
            query_text="test",
            audio_bytes=None,
            retriever=mock_retriever,
            folder_path=rag.folder_path,
            remitente="user123",
            session_manager=None
        )
        assert result == ("transcripcion", "respuesta")

    @pytest.mark.asyncio
    async def test_audio_query_delegates_correctly(self, mock_rag):
        """GIVEN audio_bytes=b'data' WHEN preguntar() called THEN procesar() receives audio."""
        rag, mock_qp, _ = mock_rag

        result = await rag.preguntar(query_text=None, audio_bytes=b"data", remitente="user", session_manager=None)

        call_args = mock_qp.procesar.call_args
        assert call_args[1]["audio_bytes"] == b"data"
        assert call_args[1]["query_text"] is None
        assert result == ("transcripcion", "respuesta")

    @pytest.mark.asyncio
    async def test_return_type_preserved(self, mock_rag):
        """GIVEN any valid input WHEN preguntar() completes THEN returns tuple[str|None, str]."""
        rag, mock_qp, _ = mock_rag

        result = await rag.preguntar(query_text="test", audio_bytes=None, remitente="user", session_manager=None)

        assert isinstance(result, tuple)
        assert len(result) == 2


class TestRAGOrchestratorActualizarMemoria:
    """Tests for actualizar_memoria() delegation."""

    def test_memory_updated_refreshes_retriever(self):
        """GIVEN files changed WHEN actualizar_memoria() called THEN retriever refreshed and returns True."""
        with patch("rag_orchestrator.DocumentManager") as mock_dm_cls, \
             patch("rag_orchestrator.QueryProcessor"):

            mock_dm = mock_dm_cls.return_value
            mock_dm.folder_path = Path("/tmp/PDFs")
            old_retriever = MagicMock()
            new_retriever = MagicMock()
            mock_dm.setup_retriever.return_value = old_retriever
            mock_dm.actualizar_memoria.return_value = True

            from rag_orchestrator import RAGOrchestrator
            rag = RAGOrchestrator("key")

            # Setup retriever will be called twice: once in __init__, once in actualizar_memoria
            mock_dm.setup_retriever.return_value = new_retriever
            result = rag.actualizar_memoria()

            assert result is True
            mock_dm.actualizar_memoria.assert_called_once()
            # setup_retriever called again after memory update
            assert mock_dm.setup_retriever.call_count == 2
            assert rag.retriever is new_retriever

    def test_memory_unchanged_retriever_untouched(self):
        """GIVEN no files changed WHEN actualizar_memoria() called THEN retriever unchanged and returns False."""
        with patch("rag_orchestrator.DocumentManager") as mock_dm_cls, \
             patch("rag_orchestrator.QueryProcessor"):

            mock_dm = mock_dm_cls.return_value
            mock_dm.folder_path = Path("/tmp/PDFs")
            original_retriever = MagicMock()
            mock_dm.setup_retriever.return_value = original_retriever
            mock_dm.actualizar_memoria.return_value = False

            from rag_orchestrator import RAGOrchestrator
            rag = RAGOrchestrator("key")

            result = rag.actualizar_memoria()

            assert result is False
            mock_dm.actualizar_memoria.assert_called_once()
            # setup_retriever only called once (in __init__)
            assert mock_dm.setup_retriever.call_count == 1
            assert rag.retriever is original_retriever


class TestRAGOrchestratorInterfaceContract:
    """Tests for drop-in replacement contract."""

    def test_constructor_signature_matches_old(self):
        """GIVEN RAGOrchestrator WHEN constructed THEN signature matches RAGLangchain(api_key, folder_path)."""
        with patch("rag_orchestrator.DocumentManager") as mock_dm_cls, \
             patch("rag_orchestrator.QueryProcessor"):

            mock_dm = mock_dm_cls.return_value
            mock_dm.folder_path = Path("/tmp/PDFs")
            mock_dm.setup_retriever.return_value = MagicMock()

            from rag_orchestrator import RAGOrchestrator
            # Should accept same args as RAGLangchain
            rag = RAGOrchestrator("google_key")
            rag2 = RAGOrchestrator("google_key", folder_path="CustomDocs")

            assert rag.folder_path is not None
            assert rag2.folder_path is not None

    def test_preguntar_signature_matches_old(self):
        """GIVEN RAGOrchestrator WHEN preguntar() called THEN accepts same kwargs as RAGLangchain."""
        with patch("rag_orchestrator.DocumentManager") as mock_dm_cls, \
             patch("rag_orchestrator.QueryProcessor") as mock_qp_cls:

            mock_dm = mock_dm_cls.return_value
            mock_dm.folder_path = Path("/tmp/PDFs")
            mock_dm.setup_retriever.return_value = MagicMock()
            mock_qp = mock_qp_cls.return_value
            mock_qp.procesar = AsyncMock(return_value=("t", "r"))

            from rag_orchestrator import RAGOrchestrator
            rag = RAGOrchestrator("key")

            # Should accept same kwargs
            import asyncio
            result = asyncio.run(rag.preguntar(
                query_text="test",
                audio_bytes=None,
                remitente="user",
                session_manager=None
            ))
            assert isinstance(result, tuple)

    def test_line_count_under_30(self):
        """GIVEN the orchestrator implementation WHEN lines counted THEN ≤30 implementation lines."""
        import inspect
        from rag_orchestrator import RAGOrchestrator

        # Count lines of actual methods (exclude imports, docstrings)
        source = inspect.getsource(RAGOrchestrator)
        lines = [l for l in source.split("\n") if l.strip() and not l.strip().startswith("#") and not l.strip().startswith('"""') and not l.strip().startswith("def ") and not l.strip().startswith("class ")]
        # Only count method body lines
        assert len(lines) <= 30, f"RAGOrchestrator has {len(lines)} implementation lines, max 30"
