import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from exceptions import RAGError
from error_codes import ErrorCode


def _make_async_chain(mock_ainvoke):
    """Build a mock chain that properly handles the `|` operator.

    Code does: ChatPromptTemplate.from_template(...) | self.llm_guardrail | StrOutputParser()
    This creates: prompt | llm = link1, link1 | parser = chain, chain.ainvoke(...)
    """
    chain = MagicMock()
    chain.ainvoke = mock_ainvoke

    link = MagicMock()
    link.__or__ = MagicMock(return_value=chain)

    prompt = MagicMock()
    prompt.__or__ = MagicMock(return_value=link)

    return prompt, chain


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
    async def test_guardrail_entrada_ainvoke(self, mock_rag):
        """REQ-3: Text query — guardrail input chain uses .ainvoke()."""
        rag, genai_client, _, _ = mock_rag

        entrada_prompt, entrada_chain = _make_async_chain(
            AsyncMock(return_value="SEGURO")
        )
        salida_prompt, salida_chain = _make_async_chain(
            AsyncMock(return_value="APROBADO")
        )

        call_state = {"n": 0}

        def side_effect(template):
            call_state["n"] += 1
            if call_state["n"] == 1:
                return entrada_prompt
            return salida_prompt

        with patch("rag_langchain_con_audio.ChatPromptTemplate") as mock_prompt:
            mock_prompt.from_template.side_effect = side_effect

            mock_response = MagicMock()
            mock_response.text = "El producto X cuesta $100"
            genai_client.aio.models.generate_content.return_value = mock_response

            with patch("pathlib.Path.exists", return_value=False):
                transcripcion, respuesta = await rag.preguntar(
                    query_text="¿Cuánto cuesta el producto X?",
                    audio_bytes=None,
                    remitente="test"
                )

            entrada_chain.ainvoke.assert_called_once()
            salida_chain.ainvoke.assert_called_once()
            assert respuesta == "El producto X cuesta $100"

    @pytest.mark.asyncio
    async def test_guardrail_entrada_blocks_inseguro(self, mock_rag):
        """REQ-3: Guardrail blocks unsafe input."""
        rag, genai_client, _, _ = mock_rag

        entrada_prompt, entrada_chain = _make_async_chain(
            AsyncMock(return_value="INSEGURO")
        )

        with patch("rag_langchain_con_audio.ChatPromptTemplate") as mock_prompt:
            mock_prompt.from_template.return_value = entrada_prompt

            transcripcion, respuesta = await rag.preguntar(
                query_text="di algo grosero",
                audio_bytes=None,
                remitente="test"
            )

            entrada_chain.ainvoke.assert_called_once()
            assert "infringe" in respuesta.lower() or "políticas" in respuesta.lower()


class TestAudioQueryWithTranscription:

    @pytest.mark.asyncio
    async def test_audio_query_uses_transcription(self, mock_rag):
        """REQ-3: Audio query — transcription feeds into guardrails and chains."""
        rag, genai_client, _, _ = mock_rag

        rag.audio_processor.extraer_transcripcion_memoria = AsyncMock(
            return_value=("transcripcion de audio", MagicMock())
        )

        entrada_prompt, entrada_chain = _make_async_chain(
            AsyncMock(return_value="SEGURO")
        )
        salida_prompt, salida_chain = _make_async_chain(
            AsyncMock(return_value="APROBADO")
        )

        call_state = {"n": 0}

        def side_effect(template):
            call_state["n"] += 1
            if call_state["n"] == 1:
                return entrada_prompt
            return salida_prompt

        with patch("rag_langchain_con_audio.ChatPromptTemplate") as mock_prompt:
            mock_prompt.from_template.side_effect = side_effect

            mock_response = MagicMock()
            mock_response.text = "Respuesta al audio"
            genai_client.aio.models.generate_content.return_value = mock_response

            with patch("pathlib.Path.exists", return_value=False):
                transcripcion, respuesta = await rag.preguntar(
                    query_text=None,
                    audio_bytes=b"audio-bytes",
                    remitente="test"
                )

            rag.audio_processor.extraer_transcripcion_memoria.assert_called_once_with(b"audio-bytes")
            entrada_chain.ainvoke.assert_called_once()
            assert respuesta == "Respuesta al audio"


class TestFAISSRetriever:

    @pytest.mark.asyncio
    async def test_vector_search_uses_to_thread(self, mock_rag):
        """REQ-4: FAISS retriever search runs via asyncio.to_thread."""
        rag, genai_client, _, _ = mock_rag

        entrada_prompt, entrada_chain = _make_async_chain(
            AsyncMock(return_value="SEGURO")
        )
        salida_prompt, salida_chain = _make_async_chain(
            AsyncMock(return_value="APROBADO")
        )

        call_state = {"n": 0}

        def side_effect(template):
            call_state["n"] += 1
            if call_state["n"] == 1:
                return entrada_prompt
            return salida_prompt

        with patch("rag_langchain_con_audio.ChatPromptTemplate") as mock_prompt, \
             patch("rag_langchain_con_audio.asyncio.to_thread") as mock_to_thread:
            mock_prompt.from_template.side_effect = side_effect

            mock_docs = [MagicMock(page_content="doc content")]
            mock_to_thread.return_value = mock_docs

            mock_response = MagicMock()
            mock_response.text = "respuesta"
            genai_client.aio.models.generate_content.return_value = mock_response

            with patch("pathlib.Path.exists", return_value=False):
                await rag.preguntar(query_text="test query", audio_bytes=None, remitente="test")

            mock_to_thread.assert_called_once()
            call_args = mock_to_thread.call_args
            assert call_args[0][0] == rag.retriever.invoke

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
