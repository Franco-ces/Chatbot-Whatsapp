"""IdleTimeoutClient — httpx.AsyncClient wrapper with idle timeout.

Creates the underlying client on first request, resets a 5-minute idle
timer after each call, and auto-closes when idle.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx


class IdleTimeoutClient:
    """Wrapper around httpx.AsyncClient that auto-closes after idle time."""

    IDLE_TIMEOUT_SECONDS = 300  # 5 minutes

    def __init__(self, timeout: httpx.Timeout | None = None, **client_kwargs: Any):
        self._client: httpx.AsyncClient | None = None
        self._client_kwargs = client_kwargs
        self._timeout = timeout or httpx.Timeout(30.0)
        self._timer: asyncio.TimerHandle | None = None
        self._closed = False

    @property
    def is_closed(self) -> bool:
        return self._closed

    def _schedule_close(self) -> None:
        """Schedule (or reschedule) the idle-close timer."""
        loop = asyncio.get_running_loop()
        if self._timer is not None:
            self._timer.cancel()
        self._timer = loop.call_later(self.IDLE_TIMEOUT_SECONDS, self._close)

    def _close(self) -> None:
        """Called by the timer — sets closed flag; actual cleanup is deferred."""
        self._client = None
        self._closed = True

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Create the underlying AsyncClient on first use."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout, **self._client_kwargs
            )
            self._closed = False
        return self._client

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Proxy an HTTP request through the managed client."""
        client = await self._ensure_client()
        self._schedule_close()
        response = await client.request(method, url, **kwargs)
        self._schedule_close()  # reschedule after response
        return response

    async def aclose(self) -> None:
        """Close the underlying client immediately."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        self._closed = True
