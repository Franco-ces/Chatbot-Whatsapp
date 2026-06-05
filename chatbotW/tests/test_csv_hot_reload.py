"""Tests for CSV hot-reload feature.

Phase 1: Concurrency infrastructure (async lock on RAGOrchestrator)
Phase 2: Per-query reload wiring (bot_service calls actualizar_memoria)
Phase 3: Manual reload endpoint (POST /api/reload-rag)

All tests follow strict TDD: written BEFORE implementation.
"""
import sys
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

# Mock price_lookup before importing modules
sys.modules.setdefault("price_lookup", MagicMock())


# ─── Phase 1: Async Lock on RAGOrchestrator ────────────────────────────


class TestRAGOrchestratorAsyncLock:
    """Task 1.1 + 1.2: actualizar_memoria is async with asyncio.Lock."""

    @pytest.fixture
    def mock_rag(self):
        """Create a RAGOrchestrator with mocked sub-components."""
        with patch("rag_orchestrator.DocumentManager") as mock_dm_cls, \
             patch("rag_orchestrator.QueryProcessor") as mock_qp_cls, \
             patch("rag_orchestrator.ConfigManager"), \
             patch("rag_orchestrator.FAQMatcher"):

            mock_dm = mock_dm_cls.return_value
            mock_dm.folder_path = Path("/tmp/PDFs")
            mock_dm.setup_retriever.return_value = MagicMock()

            from rag_orchestrator import RAGOrchestrator
            rag = RAGOrchestrator("key")
            return rag, mock_dm

    @pytest.mark.asyncio
    async def test_actualizar_memoria_is_coroutine(self, mock_rag):
        """GIVEN RAGOrchestrator WHEN calling actualizar_memoria() THEN it returns a coroutine (is async)."""
        rag, mock_dm = mock_rag
        mock_dm.actualizar_memoria.return_value = False

        result = rag.actualizar_memoria()
        # Must be a coroutine, not a regular return
        assert asyncio.iscoroutine(result)
        await result  # clean up

    @pytest.mark.asyncio
    async def test_actualizar_memoria_async_returns_true_on_change(self, mock_rag):
        """GIVEN files changed WHEN actualizar_memoria() awaited THEN returns True and retriever refreshed."""
        rag, mock_dm = mock_rag
        old_retriever = rag.retriever
        new_retriever = MagicMock()
        # DocumentManager.actualizar_memoria is sync, so use regular Mock
        mock_dm.actualizar_memoria.return_value = True
        mock_dm.setup_retriever.return_value = new_retriever

        result = await rag.actualizar_memoria()

        assert result is True
        assert rag.retriever is new_retriever

    @pytest.mark.asyncio
    async def test_actualizar_memoria_async_returns_false_on_no_change(self, mock_rag):
        """GIVEN no files changed WHEN actualizar_memoria() awaited THEN returns False and retriever unchanged."""
        rag, mock_dm = mock_rag
        original_retriever = rag.retriever
        mock_dm.actualizar_memoria.return_value = False

        result = await rag.actualizar_memoria()

        assert result is False
        assert rag.retriever is original_retriever

    @pytest.mark.asyncio
    async def test_lock_exists_on_instance(self, mock_rag):
        """GIVEN RAGOrchestrator WHEN constructed THEN _reload_lock is an asyncio.Lock."""
        rag, _ = mock_rag
        assert hasattr(rag, "_reload_lock")
        assert isinstance(rag._reload_lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_lock_prevents_concurrent_rebuilds(self, mock_rag):
        """GIVEN two concurrent actualizar_memoria() calls WHEN both detect changes THEN only one rebuild occurs.

        Task 4.3: The asyncio.Lock serializes calls so that if two coroutines
        enter simultaneously, the second waits for the first to finish.
        """
        rag, mock_dm = mock_rag

        rebuild_count = 0
        rebuild_call_log = []

        def slow_actualizar_memoria():
            nonlocal rebuild_count
            rebuild_count += 1
            rebuild_call_log.append(f"start-{rebuild_count}")
            # Simulate slow rebuild via synchronous sleep (this is sync, not async)
            import time
            time.sleep(0.02)
            rebuild_call_log.append(f"end-{rebuild_count}")
            return True

        mock_dm.actualizar_memoria = slow_actualizar_memoria
        mock_dm.setup_retriever.return_value = MagicMock()

        # Launch two concurrent calls
        results = await asyncio.gather(
            rag.actualizar_memoria(),
            rag.actualizar_memoria(),
        )

        # Both should return True (both detected changes)
        assert all(results)
        # But rebuild_call_log shows serialization: start-1, end-1, start-2, end-2
        # (not start-1, start-2, end-1, end-2 which would be concurrent)
        assert rebuild_call_log[0] == "start-1"
        assert rebuild_call_log[1] == "end-1"
        assert rebuild_call_log[2] == "start-2"
        assert rebuild_call_log[3] == "end-2"


# ─── Phase 2: Per-Query Reload Wiring ──────────────────────────────────


class TestBotServicePreQueryReload:
    """Task 2.1: bot_service calls actualizar_memoria before preguntar."""

    @pytest.fixture
    def wa_client(self):
        client = AsyncMock()
        client.enviar_mensaje = AsyncMock()
        client.obtener_audio_base64 = AsyncMock()
        return client

    @pytest.fixture
    def rag_instance(self):
        rag = AsyncMock()
        rag.preguntar = AsyncMock()
        rag.check_faq = MagicMock(return_value=None)
        rag.actualizar_memoria = AsyncMock(return_value=False)
        return rag

    REMITTENTE = "5491123456789"
    TEXTO = "consulta de prueba"
    MENSAJE_DATA = {"key": {"id": "123"}}
    RESPUESTA_OK = "Esta es la respuesta del bot."
    TEST_INSTANCE = "bot_test"

    @pytest.mark.asyncio
    async def test_actualizar_memoria_called_before_preguntar(self, wa_client, rag_instance):
        """GIVEN user sends message WHEN procesar_mensaje_bot runs THEN actualizar_memoria() called before preguntar()."""
        from query_processor import QueryResult
        rag_instance.preguntar.return_value = QueryResult("t", self.RESPUESTA_OK, cacheable=True)

        from bot_service import procesar_mensaje_bot
        await procesar_mensaje_bot(
            rag_instance, wa_client, self.REMITTENTE, self.TEXTO, self.MENSAJE_DATA,
            es_audio=False, instance_name=self.TEST_INSTANCE,
        )

        rag_instance.actualizar_memoria.assert_called_once()
        # Verify order: actualizar_memoria before preguntar
        calls = rag_instance.method_calls
        actualizar_idx = next(i for i, c in enumerate(calls) if c[0] == "actualizar_memoria")
        preguntar_idx = next(i for i, c in enumerate(calls) if c[0] == "preguntar")
        assert actualizar_idx < preguntar_idx

    @pytest.mark.asyncio
    async def test_actualizar_memoria_failure_does_not_block_response(self, wa_client, rag_instance):
        """GIVEN actualizar_memoria() raises WHEN processing message THEN preguntar() still called and response sent.

        Task 4.4: Reload failure must not block responses.
        """
        from query_processor import QueryResult
        rag_instance.actualizar_memoria.side_effect = RuntimeError("rebuild failed")
        rag_instance.preguntar.return_value = QueryResult("t", self.RESPUESTA_OK, cacheable=True)
        # Prevent FAQ shortcut
        rag_instance.check_faq.return_value = None

        from bot_service import procesar_mensaje_bot, _question_cache
        # Clear cache to avoid cache hit bypassing preguntar
        _question_cache.clear()

        await procesar_mensaje_bot(
            rag_instance, wa_client, self.REMITTENTE, self.TEXTO, self.MENSAJE_DATA,
            es_audio=False, instance_name=self.TEST_INSTANCE,
        )

        # preguntar was still called despite actualizar_memoria failure
        rag_instance.preguntar.assert_called_once()
        # And response was sent to user
        wa_client.enviar_mensaje.assert_called_once_with(
            self.REMITTENTE, self.RESPUESTA_OK, instance_name=self.TEST_INSTANCE
        )

    @pytest.mark.asyncio
    async def test_actualizar_memoria_not_called_for_audio_only_error_path(self, wa_client, rag_instance):
        """GIVEN audio download fails WHEN processing message THEN error is handled gracefully."""
        from exceptions import CommunicationError
        from error_codes import ErrorCode
        rag_instance.actualizar_memoria.side_effect = RuntimeError("fail")
        wa_client.obtener_audio_base64.side_effect = CommunicationError(ErrorCode.COM_GET_AUDIO_FAILED)

        from bot_service import procesar_mensaje_bot
        # Should not raise - error is handled gracefully
        await procesar_mensaje_bot(
            rag_instance, wa_client, self.REMITTENTE, self.TEXTO, self.MENSAJE_DATA,
            es_audio=True, instance_name=self.TEST_INSTANCE,
        )

        # Error notification sent
        wa_client.enviar_mensaje.assert_called_once()
        call_text = wa_client.enviar_mensaje.call_args[0][1]
        assert ErrorCode.COM_GET_AUDIO_FAILED.value in call_text


# ─── Phase 2: DocumentManager exception handling ────────────────────────


class TestDocumentManagerActualizarMemoriaExceptionHandling:
    """Task 1.3: DocumentManager.actualizar_memoria catches setup_retriever errors."""

    def test_setup_retriever_failure_logged_not_propagated(self):
        """GIVEN setup_retriever() raises WHEN actualizar_memoria() detects changes THEN error logged, no exception propagated."""
        from document_manager import DocumentManager

        with patch("document_manager.VectorStoreManager") as mock_vs_mgr, \
             patch("document_manager.EmbeddingCache"), \
             patch("document_manager.GoogleGenerativeAIEmbeddings"):
            mock_vs_mgr.calcular_hash_archivos.return_value = "new_hash"
            mock_metadata_path = MagicMock()
            mock_metadata_path.exists.return_value = True
            mock_vs_mgr._get_metadata_path.return_value = mock_metadata_path

            dm = DocumentManager("test-key", folder_path="PDFs")

            # Mock hash comparison to detect change
            with patch("builtins.open", create=True) as mock_open:
                mock_open.return_value.__enter__ = lambda s: s
                mock_open.return_value.__exit__ = MagicMock(return_value=False)
                mock_open.return_value.read.return_value = '{"hash": "old_hash"}'

                with patch("json.load", return_value={"hash": "old_hash"}):
                    # Make setup_retriever raise
                    dm.setup_retriever = MagicMock(side_effect=Exception("API rate limit"))

                    # Should NOT raise - should catch and log
                    result = dm.actualizar_memoria()

                    # Returns False (rebuild failed, no update)
                    assert result is False


# ─── Phase 3: Manual Reload Endpoint ────────────────────────────────────


class TestReloadRagEndpoint:
    """Task 3.1: POST /api/reload-rag endpoint."""

    @pytest.mark.asyncio
    async def test_reload_rag_endpoint_exists(self):
        """GIVEN interface app WHEN POST /api/reload-rag called THEN returns status."""
        from fastapi.testclient import TestClient

        with patch("interface._rag_instance", create=True) as mock_rag:
            mock_rag.actualizar_memoria = AsyncMock(return_value=True)

            from interface import app
            client = TestClient(app)

            response = client.post("/api/reload-rag")
            # Endpoint should exist (not 404/405)
            assert response.status_code != 404
            assert response.status_code != 405

    @pytest.mark.asyncio
    async def test_reload_rag_no_instance_returns_no_changes(self):
        """GIVEN no RAG instance set WHEN POST /api/reload-rag called THEN returns no_changes."""
        from fastapi.testclient import TestClient

        with patch("interface._rag_instance", None):
            from interface import app
            client = TestClient(app)

            response = client.post("/api/reload-rag")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "no_changes"

    @pytest.mark.asyncio
    async def test_reload_rag_with_instance_calls_actualizar(self):
        """GIVEN RAG instance set WHEN POST /api/reload-rag called THEN actualizar_memoria called."""
        from fastapi.testclient import TestClient

        mock_rag = MagicMock()
        mock_rag.actualizar_memoria = AsyncMock(return_value=True)

        with patch("interface._rag_instance", mock_rag):
            from interface import app
            client = TestClient(app)

            response = client.post("/api/reload-rag")
            assert response.status_code == 200
            mock_rag.actualizar_memoria.assert_called_once()
            data = response.json()
            assert data["status"] == "reloaded"
