import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from httpx_idle_client import IdleTimeoutClient


class TestIdleTimeoutClient:

    @pytest.mark.asyncio
    async def test_client_creates_on_first_request(self):
        """REQ-7: Client is lazily created on first request."""
        idle_client = IdleTimeoutClient()

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_async_cls:
            mock_inner = AsyncMock()
            mock_inner.request.return_value = mock_response
            mock_inner.is_closed = False
            mock_async_cls.return_value = mock_inner

            result = await idle_client.request("GET", "http://example.com")

            mock_async_cls.assert_called_once()
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_reuses_same_client_across_requests(self):
        """REQ-7: Multiple requests share the same underlying AsyncClient."""
        idle_client = IdleTimeoutClient()
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_async_cls:
            mock_inner = AsyncMock()
            mock_inner.request.return_value = mock_response
            mock_inner.is_closed = False
            mock_async_cls.return_value = mock_inner

            await idle_client.request("GET", "http://example.com/1")
            await idle_client.request("GET", "http://example.com/2")

            assert mock_async_cls.call_count == 1
            assert mock_inner.request.call_count == 2

    @pytest.mark.asyncio
    async def test_idle_timeout_sets_closed_flag(self):
        """REQ-8: Client closes after idle timeout."""
        idle_client = IdleTimeoutClient()

        with patch("httpx.AsyncClient") as mock_async_cls:
            mock_inner = AsyncMock()
            mock_inner.is_closed = False
            mock_async_cls.return_value = mock_inner

            await idle_client.request("GET", "http://example.com")

            # Simulate the timer callback firing
            idle_client._close()
            assert idle_client.is_closed is True
            assert idle_client._client is None

    @pytest.mark.asyncio
    async def test_aclose_closes_immediately(self):
        """REQ-8: aclose() closes the client immediately."""
        idle_client = IdleTimeoutClient()

        with patch("httpx.AsyncClient") as mock_async_cls:
            mock_inner = AsyncMock()
            mock_inner.is_closed = False
            mock_async_cls.return_value = mock_inner

            await idle_client.request("GET", "http://example.com")
            await idle_client.aclose()

            mock_inner.aclose.assert_called_once()
            assert idle_client.is_closed is True

    @pytest.mark.asyncio
    async def test_is_closed_initially_false(self):
        """REQ-7: New client is not closed."""
        idle_client = IdleTimeoutClient()
        assert idle_client.is_closed is False
