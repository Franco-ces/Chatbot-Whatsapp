import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

# Mock price_lookup before importing query_processor (pre-existing missing module)
sys.modules.setdefault("price_lookup", MagicMock())


class TestQueryProcessorConstructor:
    """Tests for QueryProcessor.__init__ initialization."""

    def test_constructor_initializes_components(self):
        """GIVEN api_key='test-key' WHEN constructed THEN all components initialized."""
        with patch("query_processor.genai.Client") as mock_genai_cls, \
             patch("query_processor.AudioProcessor") as mock_audio_cls, \
             patch("query_processor.ChatGoogleGenerativeAI") as mock_llm_cls, \
             patch("query_processor.ConfigManager") as mock_cfg_cls:

            # ConfigManager returns config with gemini_model key
            cfg_instance = mock_cfg_cls.return_value
            cfg_instance.config = {
                "email": "test@test.com",
                "telefono": "123",
                "gemini_model": "gemini-2.5-pro",
            }

            from query_processor import QueryProcessor
            qp = QueryProcessor("test-key")

            mock_genai_cls.assert_called_once_with(api_key="test-key")
            mock_audio_cls.assert_called_once_with(
                mock_genai_cls.return_value, model="gemini-2.5-pro"
            )
            mock_llm_cls.assert_called_once_with(model="gemini-3.1-flash-lite", google_api_key="test-key")
            assert qp.prompt_template is not None


class TestQueryProcessorProcesar:
    """Tests for procesar() pipeline behavior."""

    @pytest.fixture
    def mock_qp(self):
        """Create a QueryProcessor with all external deps mocked."""
        with patch("query_processor.genai.Client") as mock_genai_cls, \
             patch("query_processor.AudioProcessor") as mock_audio_cls, \
             patch("query_processor.ChatGoogleGenerativeAI"), \
             patch("query_processor.ConfigManager") as mock_cfg_cls:

            genai_client = mock_genai_cls.return_value
            genai_client.aio = MagicMock()
            genai_client.aio.models = MagicMock()
            genai_client.aio.models.generate_content = AsyncMock()

            cfg_instance = mock_cfg_cls.return_value
            cfg_instance.config = {"email": "test@test.com", "telefono": "123"}

            from query_processor import QueryProcessor
            from prompts import PROMPT_ASISTENTE_VIRTUAL

            qp = QueryProcessor.__new__(QueryProcessor)
            qp.api_key = "test-key"
            qp.client = genai_client
            qp.audio_processor = mock_audio_cls.return_value
            qp.llm_guardrail = MagicMock()
            qp.prompt_template = PROMPT_ASISTENTE_VIRTUAL
            qp.config_manager = cfg_instance
            qp.faq_matcher = None  # default; las pruebas FAQ lo sobreescriben

            return qp, genai_client

    @pytest.mark.asyncio
    async def test_text_query_happy_path(self, mock_qp):
        """GIVEN query_text='¿Cuánto cuesta X?' WHEN procesar() called THEN full pipeline executes."""
        qp, genai_client = mock_qp

        mock_retriever = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "El producto X cuesta $100"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto"), \
             patch("pathlib.Path.exists", return_value=False):
            result = await qp.procesar(
                query_text="¿Cuánto cuesta X?",
                audio_bytes=None,
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="test",
                session_manager=None
            )

            assert result.respuesta == "El producto X cuesta $100"
            assert result.transcripcion == "¿Cuánto cuesta X?"

    @pytest.mark.asyncio
    async def test_audio_query_uses_transcription(self, mock_qp):
        """GIVEN audio_bytes=b'audio-data' WHEN procesar() called THEN transcription feeds pipeline."""
        qp, genai_client = mock_qp

        mock_retriever = MagicMock()
        mock_audio_part = MagicMock()
        qp.audio_processor.extraer_transcripcion_memoria = AsyncMock(
            return_value=("transcripcion de audio", mock_audio_part)
        )

        mock_response = MagicMock()
        mock_response.text = "Respuesta al audio"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto"), \
             patch("pathlib.Path.exists", return_value=False):
            result = await qp.procesar(
                query_text=None,
                audio_bytes=b"audio-bytes",
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="test",
                session_manager=None
            )

            qp.audio_processor.extraer_transcripcion_memoria.assert_called_once_with(b"audio-bytes")
            assert result.transcripcion == "transcripcion de audio"
            assert result.respuesta == "Respuesta al audio"

    @pytest.mark.asyncio
    async def test_hybrid_query_text_plus_audio(self, mock_qp):
        """GIVEN query_text AND audio_bytes WHEN procesar() called THEN text used for search, audio part sent to Gemini."""
        qp, genai_client = mock_qp

        mock_retriever = MagicMock()
        mock_audio_part = MagicMock()
        qp.audio_processor.extraer_transcripcion_memoria = AsyncMock(
            return_value=("transcripcion del audio", mock_audio_part)
        )

        mock_response = MagicMock()
        mock_response.text = "Respuesta híbrida"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto") as mock_ctx, \
             patch("pathlib.Path.exists", return_value=False):
            result = await qp.procesar(
                query_text="¿Cuánto cuesta?",
                audio_bytes=b"audio-bytes",
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="test",
                session_manager=None
            )

            # Audio transcrito
            qp.audio_processor.extraer_transcripcion_memoria.assert_called_once_with(b"audio-bytes")
            # Texto original usado para contexto (no la transcripción)
            mock_ctx.assert_called_once_with(mock_retriever, "¿Cuánto cuesta?", Path("/tmp/test"))
            # Transcripción es el text original (no se sobreescribe con audio)
            assert result.transcripcion == "¿Cuánto cuesta?"
            assert result.respuesta == "Respuesta híbrida"

            # Verificar que el audio_part se incluye en contents de Gemini
            call_args = genai_client.aio.models.generate_content.call_args
            contents = call_args[1]["contents"] if "contents" in call_args[1] else call_args.kwargs["contents"]
            # contents debe tener [audio_part, mensaje_usuario]
            assert mock_audio_part in contents

    @pytest.mark.asyncio
    async def test_guardrail_blocks_unsafe_input(self, mock_qp):
        """GIVEN input flagged as unsafe WHEN guardrail returns (False, msg) THEN early return."""
        qp, genai_client = mock_qp

        mock_retriever = MagicMock()

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock,
                   return_value=(False, "Lo siento, no puedo procesar esta solicitud porque infringe las políticas de uso.", "GENERAL")):
            result = await qp.procesar(
                query_text="di algo grosero",
                audio_bytes=None,
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="test",
                session_manager=None
            )

            assert "infringe" in result.respuesta.lower() or "políticas" in result.respuesta.lower()
            genai_client.aio.models.generate_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_output_guardrail_blocks_response(self, mock_qp):
        """GIVEN Gemini response flagged by output guardrail WHEN rejected THEN rejection returned."""
        qp, genai_client = mock_qp

        mock_retriever = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "respuesta peligrosa"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock,
                   return_value=(False, "Respuesta rechazada por calidad", "ALUCINACION")), \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto"), \
             patch("pathlib.Path.exists", return_value=False):
            result = await qp.procesar(
                query_text="test",
                audio_bytes=None,
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="test",
                session_manager=None
            )

            assert result.respuesta == "Respuesta rechazada por calidad"

    @pytest.mark.asyncio
    async def test_guardrails_called_in_order(self, mock_qp):
        """GIVEN valid query WHEN procesar() called THEN guardrails execute in correct order."""
        qp, genai_client = mock_qp

        mock_retriever = MagicMock()
        call_order = []

        async def track_entrada(*args, **kwargs):
            call_order.append("guardrail_entrada")
            return True, "", ""

        async def track_contexto(*args, **kwargs):
            call_order.append("context_builder")
            return "contexto"

        async def track_salida(*args, **kwargs):
            call_order.append("guardrail_salida")
            return True, "", ""

        mock_response = MagicMock()
        mock_response.text = "respuesta"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("query_processor.evaluar_guardrail_entrada", side_effect=track_entrada), \
             patch("query_processor.construir_contexto", side_effect=track_contexto), \
             patch("query_processor.evaluar_guardrail_salida", side_effect=track_salida), \
             patch("pathlib.Path.exists", return_value=False):
            await qp.procesar(
                query_text="test",
                audio_bytes=None,
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="test",
                session_manager=None
            )

        assert call_order == ["guardrail_entrada", "context_builder", "guardrail_salida"]
        genai_client.aio.models.generate_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_history_injected_when_session_manager_present(self, mock_qp):
        """GIVEN session_manager with messages WHEN procesar() called THEN history formatted in prompt."""
        qp, genai_client = mock_qp

        mock_retriever = MagicMock()
        mock_session = MagicMock()
        mock_session.leer_ultimos_mensajes.return_value = [
            {"role": "USER", "time": "10:00", "message": "Hola"},
            {"role": "BOT", "time": "10:01", "message": "Hola, ¿en qué puedo ayudarte?"}
        ]

        mock_response = MagicMock()
        mock_response.text = "respuesta"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto"), \
             patch("pathlib.Path.exists", return_value=False):
            await qp.procesar(
                query_text="test",
                audio_bytes=None,
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="user123",
                session_manager=mock_session
            )

            mock_session.leer_ultimos_mensajes.assert_called_once_with("user123", cantidad=10)

    @pytest.mark.asyncio
    async def test_no_session_manager_uses_default_history(self, mock_qp):
        """GIVEN session_manager=None WHEN procesar() called THEN history='Sin historial previo.'"""
        qp, genai_client = mock_qp

        mock_retriever = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "respuesta"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto"), \
             patch("pathlib.Path.exists", return_value=False):
            # Verificar que el prompt contiene el texto por defecto
            await qp.procesar(
                query_text="test",
                audio_bytes=None,
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="test",
                session_manager=None
            )

            # El prompt formateado debería contener "Sin historial previo."
            call_args = genai_client.aio.models.generate_content.call_args
            config = call_args[1].get("config") or call_args.kwargs.get("config")
            assert "Sin historial previo." in config.system_instruction

    @pytest.mark.asyncio
    async def test_procesar_uses_config_model_for_generate_content(self, mock_qp):
        """Config con gemini_model='gemini-2.5-pro' → generate_content llamado con ese modelo."""
        qp, genai_client = mock_qp
        # Setear el modelo en config
        qp.config_manager.config["gemini_model"] = "gemini-2.5-pro"

        mock_retriever = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "respuesta"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto"), \
             patch("pathlib.Path.exists", return_value=False):
            await qp.procesar(
                query_text="test",
                audio_bytes=None,
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="test",
                session_manager=None
            )

            call_kwargs = genai_client.aio.models.generate_content.call_args
            model_used = call_kwargs[1]["model"] if "model" in call_kwargs[1] else call_kwargs.kwargs.get("model")
            assert model_used == "gemini-2.5-pro"

    @pytest.mark.asyncio
    async def test_config_reloaded_each_query(self, mock_qp):
        """GIVEN config changed on disk WHEN procesar() called THEN config_manager.cargar() called."""
        qp, genai_client = mock_qp

        mock_retriever = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "respuesta"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto"), \
             patch("pathlib.Path.exists", return_value=False):
            await qp.procesar(
                query_text="test",
                audio_bytes=None,
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="test",
                session_manager=None
            )

            qp.config_manager.cargar.assert_called()

    @pytest.mark.asyncio
    async def test_return_type_is_queryresult(self, mock_qp):
        """GIVEN any valid input WHEN procesar() completes THEN returns QueryResult dataclass."""
        from query_processor import QueryResult
        qp, genai_client = mock_qp

        mock_retriever = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "respuesta"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto"), \
             patch("pathlib.Path.exists", return_value=False):
            result = await qp.procesar(
                query_text="test",
                audio_bytes=None,
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="test",
                session_manager=None
            )

            assert isinstance(result, QueryResult)
            assert result.transcripcion == "test"
            assert result.respuesta == "respuesta"
            # Happy path: respuesta de Gemini con contexto y guardrail aprobado → cacheable
            assert result.cacheable is True


# ────────────────────────────────────────────────────────────────────────
# FAQ integration (Task 4)
#
# Escenarios del spec `faq-matcher` que viven en el pipeline de
# QueryProcessor:
# - Hit: el matcher devuelve respuesta; no se llama construir_contexto,
#   no se llama generate_content, no se llama evaluar_guardrail_salida.
# - Miss: el matcher no devuelve nada; el flujo RAG normal corre.
# - Handoff wins: si el usuario pide humano, gana sobre el FAQ.
# ────────────────────────────────────────────────────────────────────────

class TestQueryProcessorFAQIntegration:
    """Pipeline tests for FAQMatcher wiring into procesar()."""

    @pytest.fixture
    def mock_qp_local(self):
        """Réplica local del fixture de TestQueryProcessorProcesar (no se comparte
        entre clases por scope de pytest). Devuelve (qp, genai_client)."""
        with patch("query_processor.genai.Client") as mock_genai_cls, \
             patch("query_processor.AudioProcessor") as mock_audio_cls, \
             patch("query_processor.ChatGoogleGenerativeAI"), \
             patch("query_processor.ConfigManager") as mock_cfg_cls:

            genai_client = mock_genai_cls.return_value
            genai_client.aio = MagicMock()
            genai_client.aio.models = MagicMock()
            genai_client.aio.models.generate_content = AsyncMock()

            cfg_instance = mock_cfg_cls.return_value
            cfg_instance.config = {"email": "test@test.com", "telefono": "123"}

            from query_processor import QueryProcessor
            from prompts import PROMPT_ASISTENTE_VIRTUAL

            qp = QueryProcessor.__new__(QueryProcessor)
            qp.api_key = "test-key"
            qp.client = genai_client
            qp.audio_processor = mock_audio_cls.return_value
            qp.llm_guardrail = MagicMock()
            qp.prompt_template = PROMPT_ASISTENTE_VIRTUAL
            qp.config_manager = cfg_instance

            return qp, genai_client

    @pytest.fixture
    def qp_with_faq(self, mock_qp_local):
        """Devuelve (qp, genai_client) con `qp.faq_matcher` ya inyectado como MagicMock."""
        qp, genai_client = mock_qp_local
        qp.faq_matcher = MagicMock(name="faq_matcher")
        return qp, genai_client

    @pytest.mark.asyncio
    async def test_faq_hit_short_circuits_pipeline(self, qp_with_faq):
        """GIVEN matcher returns a hit WHEN procesar() called THEN construir_contexto, generate_content y evaluar_guardrail_salida NO se llaman, y se devuelve la respuesta del FAQ."""
        from faq_matcher import FAQMatch

        qp, genai_client = qp_with_faq
        qp.faq_matcher.match.return_value = FAQMatch(
            id="p1",
            pregunta="¿Cuánto sale el Samsung A54?",
            respuesta="$520.000",
            score=0.95,
        )

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "", "")) as mock_in, \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "", "")) as mock_out, \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto") as mock_ctx, \
             patch("pathlib.Path.exists", return_value=False):
            result = await qp.procesar(
                query_text="precio del samsung a54",
                audio_bytes=None,
                retriever=MagicMock(),
                folder_path=Path("/tmp/test"),
                remitente="user-1",
                session_manager=None,
            )

        # Se devuelve la result.respuesta del FAQ tal cual.
        assert result.respuesta == "$520.000"
        assert result.transcripcion == "precio del samsung a54"
        # El input guardrail SÍ corre (la spec lo exige).
        mock_in.assert_awaited_once()
        # El matcher se llamó con la query.
        qp.faq_matcher.match.assert_called_once_with("precio del samsung a54")
        # Pero NO se construyó contexto, NO se llamó a Gemini, NO se corrió el output guardrail.
        mock_ctx.assert_not_called()
        genai_client.aio.models.generate_content.assert_not_called()
        mock_out.assert_not_called()

    @pytest.mark.asyncio
    async def test_faq_miss_falls_through_to_rag(self, qp_with_faq):
        """GIVEN matcher returns None WHEN procesar() called THEN el pipeline RAG normal corre (construir_contexto + Gemini + output guardrail)."""
        qp, genai_client = qp_with_faq
        qp.faq_matcher.match.return_value = None  # miss

        mock_retriever = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "respuesta RAG normal"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto rag") as mock_ctx, \
             patch("pathlib.Path.exists", return_value=False):
            result = await qp.procesar(
                query_text="cómo configuro outlook",
                audio_bytes=None,
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="user-2",
                session_manager=None,
            )

        # El matcher SÍ se consultó.
        qp.faq_matcher.match.assert_called_once_with("cómo configuro outlook")
        # El pipeline RAG corrió completo.
        mock_ctx.assert_awaited_once()
        genai_client.aio.models.generate_content.assert_awaited_once()
        assert result.respuesta == "respuesta RAG normal"

    @pytest.mark.asyncio
    async def test_audio_sin_transcripcion_no_consulta_faq(self, qp_with_faq):
        """Spec faq-matcher delta: Audio without transcription is not matched.

        GIVEN audio_bytes presentes pero `extraer_transcripcion_memoria` devuelve (None, audio_part)
        WHEN `QueryProcessor.procesar` corre THEN el FAQ matcher NO es consultado y el pipeline
        RAG corre normal (construir_contexto + Gemini + output guardrail).
        """
        qp, genai_client = qp_with_faq
        qp.faq_matcher = MagicMock(name="faq_matcher")
        # Simula fallo de transcripción: el audio processor devuelve (None, audio_part)
        qp.audio_processor.extraer_transcripcion_memoria = AsyncMock(
            return_value=(None, MagicMock(name="audio_part")),
        )

        mock_retriever = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "respuesta RAG sin FAQ (audio sin texto)"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto") as mock_ctx, \
             patch("pathlib.Path.exists", return_value=False):
            result = await qp.procesar(
                query_text=None,
                audio_bytes=b"audio-bytes-sin-texto",
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="user-audio-no-tx",
                session_manager=None,
            )

        # El FAQ matcher NO se consultó (no hay texto para matchear).
        qp.faq_matcher.match.assert_not_called()
        # El pipeline RAG corrió normal.
        mock_ctx.assert_awaited_once()
        genai_client.aio.models.generate_content.assert_awaited_once()
        assert result.respuesta == "respuesta RAG sin FAQ (audio sin texto)"
        # La transcripción es None (lo que devolvió el audio processor).
        assert result.transcripcion is None

    @pytest.mark.asyncio
    async def test_audio_con_transcripcion_si_consulta_faq(self, qp_with_faq):
        """Spec faq-matcher delta: Audio with transcription is matched.

        GIVEN audio_bytes presentes y transcripción exitosa devuelve un texto
        WHEN `QueryProcessor.procesar` corre THEN el FAQ matcher ES consultado con
        la transcripción y, si matchea, devuelve la respuesta del FAQ.
        """
        from faq_matcher import FAQMatch

        qp, genai_client = qp_with_faq
        qp.faq_matcher = MagicMock(name="faq_matcher")
        qp.faq_matcher.match.return_value = FAQMatch(
            id="p1",
            pregunta="A que hora abren?",
            respuesta="Lun a Vie 9-18",
            score=0.95,
        )
        # Simula transcripción exitosa.
        qp.audio_processor.extraer_transcripcion_memoria = AsyncMock(
            return_value=("A que hora abren?", MagicMock(name="audio_part")),
        )

        mock_retriever = MagicMock()

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "", "")) as mock_out, \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto") as mock_ctx, \
             patch("pathlib.Path.exists", return_value=False):
            result = await qp.procesar(
                query_text=None,
                audio_bytes=b"audio-bytes-con-texto",
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="user-audio-tx",
                session_manager=None,
            )

        # El FAQ matcher SÍ se consultó, con la transcripción.
        qp.faq_matcher.match.assert_called_once_with("A que hora abren?")
        # Devolvió la result.respuesta del FAQ (no se construyó contexto, no se llamó Gemini).
        assert result.respuesta == "Lun a Vie 9-18"
        assert result.transcripcion == "A que hora abren?"
        mock_ctx.assert_not_called()
        genai_client.aio.models.generate_content.assert_not_called()
        mock_out.assert_not_called()

    @pytest.mark.asyncio
    async def test_historial_inyectado_en_miss_faq(self, qp_with_faq):
        """Spec query-processor delta:32-36: History is preserved on miss.

        GIVEN 4 mensajes previos en session_manager AND una query que NO matchea ninguna FAQ
        WHEN `QueryProcessor.procesar` corre THEN el prompt a Gemini contiene los 4 mensajes
        previos más la query actual.
        """
        qp, genai_client = qp_with_faq
        qp.faq_matcher = MagicMock(name="faq_matcher")
        qp.faq_matcher.match.return_value = None  # miss

        prior_messages = [
            {"role": "USER", "time": "09:00", "message": "Hola"},
            {"role": "BOT", "time": "09:01", "message": "Hola, ¿en qué te ayudo?"},
            {"role": "USER", "time": "09:02", "message": "Información"},
            {"role": "BOT", "time": "09:03", "message": "Decime qué necesitás"},
        ]
        mock_session = MagicMock()
        mock_session.leer_ultimos_mensajes.return_value = prior_messages

        mock_retriever = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "respuesta con historial"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "", "")), \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto"), \
             patch("pathlib.Path.exists", return_value=False):
            await qp.procesar(
                query_text="pregunta actual",
                audio_bytes=None,
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="user-miss",
                session_manager=mock_session,
            )

        # El pipeline RAG corrió (no early return por FAQ).
        qp.faq_matcher.match.assert_called_once_with("pregunta actual")
        genai_client.aio.models.generate_content.assert_awaited_once()
        # El session_manager fue consultado por los últimos 10 mensajes.
        mock_session.leer_ultimos_mensajes.assert_called_once_with("user-miss", cantidad=10)
        # El system_instruction enviado a Gemini contiene los 4 mensajes previos.
        call_args = genai_client.aio.models.generate_content.call_args
        config = call_args[1].get("config") or call_args.kwargs.get("config")
        system_instruction = config.system_instruction
        for msg in prior_messages:
            assert msg["message"] in system_instruction, (
                f"Falta mensaje previo en el prompt: {msg['message']!r}"
            )
        # Y la query actual también.
        assert "pregunta actual" in system_instruction

    @pytest.mark.asyncio
    async def test_handoff_wins_over_faq_hit(self, qp_with_faq):
        """GIVEN el usuario pide humano Y el matcher tendría hit WHEN procesar() THEN se devuelve el mensaje de handoff y el FAQ NUNCA se muestra."""
        from faq_matcher import FAQMatch

        qp, genai_client = qp_with_faq
        # El matcher matchearía, pero el handoff debe ganar.
        qp.faq_matcher.match.return_value = FAQMatch(
            id="p1",
            pregunta="quiero hablar con un humano",
            respuesta="Respuesta del FAQ",
            score=0.99,
        )

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "", "")) as mock_in, \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "", "")) as mock_out, \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto") as mock_ctx, \
             patch("query_processor.detectar_solicitud_humano", return_value=True), \
             patch("query_processor._MSJ_HANDOFF", "Te derivo con un humano. Aguarda."), \
             patch("pathlib.Path.exists", return_value=False):
            result = await qp.procesar(
                query_text="quiero hablar con un humano",
                audio_bytes=None,
                retriever=MagicMock(),
                folder_path=Path("/tmp/test"),
                remitente="user-3",
                session_manager=None,
            )

        # Se devuelve el mensaje de handoff, NO la result.respuesta del FAQ.
        assert result.respuesta == "Te derivo con un humano. Aguarda."
        # El FAQ matcher NO debe ser consultado: el handoff corre antes.
        qp.faq_matcher.match.assert_not_called()
        # El resto del pipeline tampoco.
        mock_ctx.assert_not_called()
        genai_client.aio.models.generate_content.assert_not_called()
        mock_out.assert_not_called()
        # El input guardrail sí corrió (la spec lo exige).
        mock_in.assert_awaited_once()
