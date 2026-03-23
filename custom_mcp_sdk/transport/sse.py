"""
ZOLT Custom MCP SDK — SSE (Server-Sent Events) Transport

Connects to a remote MCP server over HTTP. Uses SSE for receiving 
server → client messages, and standard HTTP POST for client → server requests.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from ..exceptions import ConnectionError, TransportError
from .base import BaseTransport

logger = logging.getLogger("zolt.transport.sse")


class SSETransport(BaseTransport):
    """
    SSE transport — connects to an MCP server exposed over HTTP.

    The server publishes a SSE stream on ``GET /sse`` which provides
    an ``endpoint`` event containing the URL for posting JSON-RPC requests.

    Args:
        url: Base URL of the SSE MCP server (e.g. ``"http://localhost:3001"``).
        headers: Optional HTTP headers (e.g. auth tokens).
        name: Human-readable name for logging.
    """

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        name: str = "sse",
    ):
        super().__init__(name=name)
        self.url = url.rstrip("/")
        self.headers = headers or {}
        self._client: httpx.AsyncClient | None = None
        self._post_endpoint: str | None = None
        self._message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._sse_task: asyncio.Task | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Open an SSE stream to the server and discover the POST endpoint."""
        if self._connected:
            logger.warning("Already connected to %s", self.name)
            return

        self._client = httpx.AsyncClient(headers=self.headers, timeout=30.0)

        try:
            # Start SSE listener in background
            self._sse_task = asyncio.create_task(self._listen_sse())

            # Wait for the endpoint event (with timeout)
            wait_start = asyncio.get_event_loop().time()
            while self._post_endpoint is None:
                await asyncio.sleep(0.1)
                if asyncio.get_event_loop().time() - wait_start > 10.0:
                    raise ConnectionError(
                        f"Timed out waiting for SSE endpoint from [{self.name}]"
                    )

            self._connected = True
            logger.info(
                "SSE transport [%s] connected → POST endpoint: %s",
                self.name,
                self._post_endpoint,
            )
        except httpx.HTTPError as exc:
            await self._cleanup()
            raise ConnectionError(
                f"HTTP error connecting to [{self.name}]: {exc}"
            ) from exc

    async def disconnect(self) -> None:
        """Cancel the SSE listener and close the HTTP client."""
        await self._cleanup()
        logger.info("SSE transport [%s] disconnected", self.name)

    async def _cleanup(self) -> None:
        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False
        self._post_endpoint = None

    # ── SSE Listener ──────────────────────────────────────────────────

    async def _listen_sse(self) -> None:
        """Background task that reads SSE events from the server."""
        sse_url = f"{self.url}/sse"
        try:
            async with self._client.stream("GET", sse_url) as response:
                response.raise_for_status()
                event_type = ""
                data_buffer = ""

                async for line_bytes in response.aiter_lines():
                    line = line_bytes.strip()

                    if line.startswith("event:"):
                        event_type = line[len("event:") :].strip()
                    elif line.startswith("data:"):
                        data_buffer = line[len("data:") :].strip()
                    elif line == "":
                        # End of event
                        if event_type == "endpoint" and data_buffer:
                            # The server tells us where to POST requests
                            self._post_endpoint = (
                                data_buffer
                                if data_buffer.startswith("http")
                                else f"{self.url}{data_buffer}"
                            )
                        elif event_type == "message" and data_buffer:
                            try:
                                msg = json.loads(data_buffer)
                                await self._message_queue.put(msg)
                                logger.debug("[%s] ← SSE: %s", self.name, msg)
                            except json.JSONDecodeError:
                                logger.warning(
                                    "[%s] Invalid JSON in SSE data: %s",
                                    self.name,
                                    data_buffer,
                                )
                        event_type = ""
                        data_buffer = ""
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("[%s] SSE stream error: %s", self.name, exc)
            self._connected = False

    # ── I/O ───────────────────────────────────────────────────────────

    async def send(self, message: dict[str, Any]) -> None:
        """POST a JSON-RPC request to the server's endpoint."""
        if not self._connected or self._post_endpoint is None or self._client is None:
            raise TransportError("SSE transport is not connected")

        try:
            response = await self._client.post(
                self._post_endpoint,
                json=message,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            logger.debug("[%s] → POST %s", self.name, message)
        except httpx.HTTPError as exc:
            raise TransportError(
                f"POST failed on [{self.name}]: {exc}"
            ) from exc

    async def receive(self) -> dict[str, Any]:
        """Dequeue the next JSON-RPC message from the SSE stream."""
        if not self._connected:
            raise TransportError("SSE transport is not connected")

        try:
            return await self._message_queue.get()
        except asyncio.CancelledError:
            raise
