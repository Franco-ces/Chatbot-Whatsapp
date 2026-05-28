import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path


class TestConstruirContexto:

    @pytest.mark.asyncio
    async def test_combines_docs_and_prices(self):
        """Context includes both manuals and prices sections."""
        from context_builder import construir_contexto

        mock_retriever = MagicMock()
        mock_retriever.invoke = MagicMock(return_value=[
            MagicMock(page_content="Manual: producto X"),
        ])

        with patch("context_builder.asyncio.to_thread", new_callable=AsyncMock, return_value=mock_retriever.invoke.return_value), \
             patch("context_builder.buscar_precios", return_value="\nPrecios: Widget $100"):
            contexto = await construir_contexto(
                mock_retriever, "Widget", Path("/fake")
            )

        assert "--- MANUALES TÉCNICOS Y DETALLES ---" in contexto
        assert "--- INFORMACIÓN COMERCIAL (PRECIOS Y STOCK) ---" in contexto
        assert "Manual: producto X" in contexto
        assert "Precios: Widget $100" in contexto

    @pytest.mark.asyncio
    async def test_empty_retrieval(self):
        """Empty retriever still produces valid context structure."""
        from context_builder import construir_contexto

        mock_retriever = MagicMock()

        with patch("context_builder.asyncio.to_thread", new_callable=AsyncMock, return_value=[]), \
             patch("context_builder.buscar_precios", return_value=""):
            contexto = await construir_contexto(
                mock_retriever, "test", Path("/fake")
            )

        assert "--- MANUALES TÉCNICOS Y DETALLES ---" in contexto
        assert "--- INFORMACIÓN COMERCIAL (PRECIOS Y STOCK) ---" in contexto

    @pytest.mark.asyncio
    async def test_uses_to_thread_for_retriever(self):
        """FAISS retriever is called via asyncio.to_thread."""
        from context_builder import construir_contexto

        mock_retriever = MagicMock()

        with patch("context_builder.asyncio.to_thread", new_callable=AsyncMock, return_value=[]) as mock_to_thread, \
             patch("context_builder.buscar_precios", return_value=""):
            await construir_contexto(
                mock_retriever, "test query", Path("/fake")
            )

        mock_to_thread.assert_called_once_with(mock_retriever.invoke, "test query")

    @pytest.mark.asyncio
    async def test_empty_query_defaults_to_productos(self):
        """Empty search query defaults to 'productos' for RAG retrieval."""
        from context_builder import construir_contexto

        mock_retriever = MagicMock()

        with patch("context_builder.asyncio.to_thread", new_callable=AsyncMock, return_value=[]) as mock_to_thread, \
             patch("context_builder.buscar_precios", return_value=""):
            await construir_contexto(
                mock_retriever, "", Path("/fake")
            )

        mock_to_thread.assert_called_once_with(mock_retriever.invoke, "productos")

    @pytest.mark.asyncio
    async def test_no_prices_returns_empty_price_section(self):
        """No precios.json returns empty price section."""
        from context_builder import construir_contexto

        mock_retriever = MagicMock()

        with patch("context_builder.asyncio.to_thread", new_callable=AsyncMock, return_value=[]), \
             patch("context_builder.buscar_precios", return_value=""):
            contexto = await construir_contexto(
                mock_retriever, "test", Path("/fake")
            )

        # Price section header should still be present but empty
        assert "--- INFORMACIÓN COMERCIAL (PRECIOS Y STOCK) ---\n" in contexto
