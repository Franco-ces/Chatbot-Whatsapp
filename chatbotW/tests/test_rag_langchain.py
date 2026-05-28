import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from exceptions import RAGError
from error_codes import ErrorCode


@pytest.fixture
def mock_retriever():
    retriever = MagicMock()
    retriever.invoke = MagicMock(return_value=[
        MagicMock(page_content="Manual: el producto X cuesta $100"),
        MagicMock(page_content="Manual: stock disponible 50 unidades"),
    ])
    return retriever


@pytest.fixture
def mock_vectorstore(mock_retriever):
    vs = MagicMock()
    vs.as_retriever.return_value = mock_retriever
    return vs


@pytest.fixture
def mock_rag(mock_vectorstore):
    """Create an RAGLangchain instance with all external deps mocked."""
    with patch("rag_langchain_con_audio.genai.Client") as mock_genai_cls, \
         patch("rag_langchain_con_audio.GoogleGenerativeAIEmbeddings") as mock_emb_cls, \
         patch("rag_langchain_con_audio.AudioProcessor") as mock_audio_cls, \
         patch("rag_langchain_con_audio.VectorStoreManager") as mock_vs_mgr, \
         patch("rag_langchain_con_audio.ConfigManager") as mock_cfg_cls, \
         patch("rag_langchain_con_audio.ChatGoogleGenerativeAI") as mock_llm_cls, \
         patch("rag_langchain_con_audio.EmbeddingCache") as mock_cache_cls:

        mock_vs_mgr.cargar.return_value = mock_vectorstore

        cfg_instance = mock_cfg_cls.return_value
        cfg_instance.config = {"email": "test@test.com", "telefono": "123"}

        genai_client = mock_genai_cls.return_value
        genai_client.aio = MagicMock()
        genai_client.aio.models = MagicMock()
        genai_client.aio.models.generate_content = AsyncMock()

        from rag_langchain_con_audio import RAGLangchain
        from prompts import PROMPT_ASISTENTE_VIRTUAL

        rag = RAGLangchain.__new__(RAGLangchain)
        rag.api_key = "fake-key"
        rag.folder_path = Path("/tmp/test-pdfs")
        rag.cache = mock_cache_cls.return_value
        rag.config_manager = cfg_instance
        rag.client = genai_client
        rag.embeddings_model = mock_emb_cls.return_value
        rag.audio_processor = mock_audio_cls.return_value
        rag.retriever = mock_vectorstore.as_retriever()
        rag.llm_guardrail = mock_llm_cls.return_value
        rag.prompt_template = PROMPT_ASISTENTE_VIRTUAL

        return rag, genai_client, mock_vs_mgr, cfg_instance


class TestTextQueryWithGuardrails:

    @pytest.mark.asyncio
    async def test_guardrail_entrada_calls_module(self, mock_rag):
        """REQ-3: Text query — guardrail delegates to guardrails module."""
        rag, genai_client, _, _ = mock_rag

        mock_response = MagicMock()
        mock_response.text = "El producto X cuesta $100"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("rag_langchain_con_audio.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "")), \
             patch("rag_langchain_con_audio.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "")), \
             patch("rag_langchain_con_audio.construir_contexto", new_callable=AsyncMock, return_value="contexto"), \
             patch("pathlib.Path.exists", return_value=False):
            transcripcion, respuesta = await rag.preguntar(
                query_text="¿Cuánto cuesta el producto X?",
                audio_bytes=None,
                remitente="test"
            )

            assert respuesta == "El producto X cuesta $100"

    @pytest.mark.asyncio
    async def test_guardrail_entrada_blocks_inseguro(self, mock_rag):
        """REQ-3: Guardrail blocks unsafe input via module."""
        rag, genai_client, _, _ = mock_rag

        with patch("rag_langchain_con_audio.evaluar_guardrail_entrada", new_callable=AsyncMock,
                   return_value=(False, "Lo siento, no puedo procesar esta solicitud porque infringe las políticas de uso.")):
            transcripcion, respuesta = await rag.preguntar(
                query_text="di algo grosero",
                audio_bytes=None,
                remitente="test"
            )

            assert "infringe" in respuesta.lower() or "políticas" in respuesta.lower()


class TestAudioQueryWithTranscription:

    @pytest.mark.asyncio
    async def test_audio_query_uses_transcription(self, mock_rag):
        """REQ-3: Audio query — transcription feeds into guardrails and chains."""
        rag, genai_client, _, _ = mock_rag

        rag.audio_processor.extraer_transcripcion_memoria = AsyncMock(
            return_value=("transcripcion de audio", MagicMock())
        )

        mock_response = MagicMock()
        mock_response.text = "Respuesta al audio"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("rag_langchain_con_audio.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "")), \
             patch("rag_langchain_con_audio.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "")), \
             patch("rag_langchain_con_audio.construir_contexto", new_callable=AsyncMock, return_value="contexto"), \
             patch("pathlib.Path.exists", return_value=False):
            transcripcion, respuesta = await rag.preguntar(
                query_text=None,
                audio_bytes=b"audio-bytes",
                remitente="test"
            )

            rag.audio_processor.extraer_transcripcion_memoria.assert_called_once_with(b"audio-bytes")
            assert respuesta == "Respuesta al audio"


class TestFAISSRetriever:

    @pytest.mark.asyncio
    async def test_vector_search_uses_to_thread(self, mock_rag):
        """REQ-4: FAISS retriever search runs via asyncio.to_thread (inside context_builder)."""
        rag, genai_client, _, _ = mock_rag

        mock_response = MagicMock()
        mock_response.text = "respuesta"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("rag_langchain_con_audio.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "")), \
             patch("rag_langchain_con_audio.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "")), \
             patch("rag_langchain_con_audio.construir_contexto", new_callable=AsyncMock, return_value="contexto") as mock_ctx, \
             patch("pathlib.Path.exists", return_value=False):
            await rag.preguntar(query_text="test query", audio_bytes=None, remitente="test")

            mock_ctx.assert_called_once()
            call_args = mock_ctx.call_args
            # First positional arg is the retriever
            assert call_args[0][0] == rag.retriever

    @pytest.mark.asyncio
    async def test_faiss_index_not_available_raises_error(self):
        """REQ-4: No PDFs → RAGError with RAG_NO_PDFS."""
        from rag_langchain_con_audio import RAGLangchain

        with patch("rag_langchain_con_audio.genai.Client"), \
             patch("rag_langchain_con_audio.GoogleGenerativeAIEmbeddings"), \
             patch("rag_langchain_con_audio.AudioProcessor"), \
             patch("rag_langchain_con_audio.VectorStoreManager") as mock_vs_mgr, \
             patch("rag_langchain_con_audio.EmbeddingCache"), \
             patch("rag_langchain_con_audio.ConfigManager"), \
             patch("rag_langchain_con_audio.ChatGoogleGenerativeAI"):

            mock_vs_mgr.cargar.return_value = None

            with patch("pathlib.Path.glob", return_value=[]):
                with pytest.raises(RAGError) as exc_info:
                    RAGLangchain("fake-key", folder_path="/tmp/no-pdfs")

                assert exc_info.value.code == ErrorCode.RAG_NO_PDFS


class TestModuleDelegation:

    @pytest.mark.asyncio
    async def test_guardrails_called_in_order(self, mock_rag):
        """REQ-11: Guardrails, context_builder, and Gemini API are called in correct order."""
        rag, genai_client, _, _ = mock_rag

        call_order = []

        async def track_entrada(*args, **kwargs):
            call_order.append("guardrail_entrada")
            return True, ""

        async def track_contexto(*args, **kwargs):
            call_order.append("context_builder")
            return "contexto"

        async def track_salida(*args, **kwargs):
            call_order.append("guardrail_salida")
            return True, ""

        mock_response = MagicMock()
        mock_response.text = "respuesta"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("rag_langchain_con_audio.evaluar_guardrail_entrada", side_effect=track_entrada), \
             patch("rag_langchain_con_audio.construir_contexto", side_effect=track_contexto), \
             patch("rag_langchain_con_audio.evaluar_guardrail_salida", side_effect=track_salida), \
             patch("pathlib.Path.exists", return_value=False):
            await rag.preguntar(query_text="test", audio_bytes=None, remitente="test")

        assert call_order == ["guardrail_entrada", "context_builder", "guardrail_salida"]
        genai_client.aio.models.generate_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_interface_unchanged(self, mock_rag):
        """REQ-12: preguntar() signature and return type unchanged."""
        rag, genai_client, _, _ = mock_rag

        mock_response = MagicMock()
        mock_response.text = "respuesta"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("rag_langchain_con_audio.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "")), \
             patch("rag_langchain_con_audio.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "")), \
             patch("rag_langchain_con_audio.construir_contexto", new_callable=AsyncMock, return_value="contexto"), \
             patch("pathlib.Path.exists", return_value=False):
            result = await rag.preguntar(
                query_text="test",
                audio_bytes=None,
                remitente="user",
                session_manager=None
            )

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], str)
