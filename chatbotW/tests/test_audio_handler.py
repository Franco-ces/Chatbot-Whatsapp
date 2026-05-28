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
