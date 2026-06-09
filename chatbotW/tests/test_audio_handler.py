import pytest
from unittest.mock import AsyncMock, MagicMock

from audio_handler import AudioProcessor


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_content = AsyncMock()
    return client


@pytest.fixture
def processor(mock_client):
    return AudioProcessor(mock_client)


class TestAudioProcessorModelParam:
    """Verifica que AudioProcessor acepte y use un modelo inyectado."""

    def test_constructor_stores_model(self, mock_client):
        """AudioProcessor(client, model='gemini-2.5-pro') → processor.model == 'gemini-2.5-pro'."""
        proc = AudioProcessor(mock_client, model="gemini-2.5-pro")
        assert proc.model == "gemini-2.5-pro"

    def test_default_model_gemini_flash_lite(self, mock_client):
        """AudioProcessor(client) → processor.model == 'gemini-3.1-flash-lite'."""
        proc = AudioProcessor(mock_client)
        assert proc.model == "gemini-3.1-flash-lite"

    @pytest.mark.asyncio
    async def test_extraer_transcripcion_uses_injected_model(self, mock_client):
        """Verifica que generate_content se llama con el modelo inyectado."""
        mock_response = MagicMock()
        mock_response.text = "transcripcion"
        mock_client.aio.models.generate_content.return_value = mock_response

        proc = AudioProcessor(mock_client, model="gemini-2.5-pro")
        await proc.extraer_transcripcion_memoria(b"audio-data")

        call_kwargs = mock_client.aio.models.generate_content.call_args
        assert call_kwargs[1]["model"] == "gemini-2.5-pro"


class TestExtraerTranscripcionMemoria:

    @pytest.mark.asyncio
    async def test_transcribe_audio_successfully(self, processor, mock_client):
        """REQ-2: Transcribe audio successfully — uses client.aio.models.generate_content."""
        mock_response = MagicMock()
        mock_response.text = "Hola, quiero consultar precios"
        mock_client.aio.models.generate_content.return_value = mock_response

        audio_bytes = b"\x00\x01\x02\x03"
        texto, audio_part = await processor.extraer_transcripcion_memoria(audio_bytes)

        assert texto == "Hola, quiero consultar precios"
        assert audio_part is not None
        mock_client.aio.models.generate_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_audio_input_returns_none(self, processor, mock_client):
        """REQ-2: Empty audio input — returns (None, None) without calling API."""
        texto, audio_part = await processor.extraer_transcripcion_memoria(None)

        assert texto is None
        assert audio_part is None
        mock_client.aio.models.generate_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_bytes_returns_none(self, processor, mock_client):
        """REQ-2: Empty audio bytes — returns (None, None) without calling API."""
        texto, audio_part = await processor.extraer_transcripcion_memoria(b"")

        assert texto is None
        assert audio_part is None
        mock_client.aio.models.generate_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_async_client_not_sync(self, processor, mock_client):
        """REQ-2: Verify client.aio.models.generate_content is called, not client.models."""
        mock_response = MagicMock()
        mock_response.text = "transcription"
        mock_client.aio.models.generate_content.return_value = mock_response

        await processor.extraer_transcripcion_memoria(b"audio-data")

        mock_client.aio.models.generate_content.assert_called_once()
        mock_client.models.generate_content.assert_not_called()
