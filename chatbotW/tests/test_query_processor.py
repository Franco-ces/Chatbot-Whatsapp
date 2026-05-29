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

            from query_processor import QueryProcessor
            qp = QueryProcessor("test-key")

            mock_genai_cls.assert_called_once_with(api_key="test-key")
            mock_audio_cls.assert_called_once_with(mock_genai_cls.return_value)
            mock_llm_cls.assert_called_once_with(model="gemini-3.1-flash-lite", google_api_key="test-key")
            mock_cfg_cls.assert_called_once()
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

            return qp, genai_client

    @pytest.mark.asyncio
    async def test_text_query_happy_path(self, mock_qp):
        """GIVEN query_text='¿Cuánto cuesta X?' WHEN procesar() called THEN full pipeline executes."""
        qp, genai_client = mock_qp

        mock_retriever = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "El producto X cuesta $100"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "")), \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto"), \
             patch("pathlib.Path.exists", return_value=False):
            transcripcion, respuesta = await qp.procesar(
                query_text="¿Cuánto cuesta X?",
                audio_bytes=None,
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="test",
                session_manager=None
            )

            assert respuesta == "El producto X cuesta $100"
            assert transcripcion == "¿Cuánto cuesta X?"

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

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "")), \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto"), \
             patch("pathlib.Path.exists", return_value=False):
            transcripcion, respuesta = await qp.procesar(
                query_text=None,
                audio_bytes=b"audio-bytes",
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="test",
                session_manager=None
            )

            qp.audio_processor.extraer_transcripcion_memoria.assert_called_once_with(b"audio-bytes")
            assert transcripcion == "transcripcion de audio"
            assert respuesta == "Respuesta al audio"

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

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "")), \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto") as mock_ctx, \
             patch("pathlib.Path.exists", return_value=False):
            transcripcion, respuesta = await qp.procesar(
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
            assert transcripcion == "¿Cuánto cuesta?"
            assert respuesta == "Respuesta híbrida"

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
                   return_value=(False, "Lo siento, no puedo procesar esta solicitud porque infringe las políticas de uso.")):
            transcripcion, respuesta = await qp.procesar(
                query_text="di algo grosero",
                audio_bytes=None,
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="test",
                session_manager=None
            )

            assert "infringe" in respuesta.lower() or "políticas" in respuesta.lower()
            genai_client.aio.models.generate_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_output_guardrail_blocks_response(self, mock_qp):
        """GIVEN Gemini response flagged by output guardrail WHEN rejected THEN rejection returned."""
        qp, genai_client = mock_qp

        mock_retriever = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "respuesta peligrosa"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock,
                   return_value=(False, "Respuesta rechazada por calidad")), \
             patch("query_processor.construir_contexto", new_callable=AsyncMock, return_value="contexto"), \
             patch("pathlib.Path.exists", return_value=False):
            transcripcion, respuesta = await qp.procesar(
                query_text="test",
                audio_bytes=None,
                retriever=mock_retriever,
                folder_path=Path("/tmp/test"),
                remitente="test",
                session_manager=None
            )

            assert respuesta == "Respuesta rechazada por calidad"

    @pytest.mark.asyncio
    async def test_guardrails_called_in_order(self, mock_qp):
        """GIVEN valid query WHEN procesar() called THEN guardrails execute in correct order."""
        qp, genai_client = mock_qp

        mock_retriever = MagicMock()
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

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "")), \
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

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "")), \
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
    async def test_config_reloaded_each_query(self, mock_qp):
        """GIVEN config changed on disk WHEN procesar() called THEN config_manager.cargar() called."""
        qp, genai_client = mock_qp

        mock_retriever = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "respuesta"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "")), \
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
    async def test_return_type_is_tuple(self, mock_qp):
        """GIVEN any valid input WHEN procesar() completes THEN returns tuple[str|None, str]."""
        qp, genai_client = mock_qp

        mock_retriever = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "respuesta"
        genai_client.aio.models.generate_content.return_value = mock_response

        with patch("query_processor.evaluar_guardrail_entrada", new_callable=AsyncMock, return_value=(True, "")), \
             patch("query_processor.evaluar_guardrail_salida", new_callable=AsyncMock, return_value=(True, "")), \
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

            assert isinstance(result, tuple)
            assert len(result) == 2
            assert isinstance(result[0], str) or result[0] is None
            assert isinstance(result[1], str)
