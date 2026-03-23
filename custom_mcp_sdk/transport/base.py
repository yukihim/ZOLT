"""
ZOLT Custom MCP SDK — Abstract Base Transport

Defines the contract that all transports (stdio, SSE) must implement.
Each transport handles framing, serialization, and I/O for JSON-RPC messages.
"""

from __future__ import annotations

import abc
from typing import Any


class BaseTransport(abc.ABC):
    """
    Abstract base class for MCP transports.

    A transport is responsible for:
    1. Establishing a connection to an MCP server.
    2. Sending JSON-RPC 2.0 request objects.
    3. Receiving JSON-RPC 2.0 response / notification objects.
    4. Tearing down the connection cleanly.
    """

    def __init__(self, name: str = "unnamed"):
        self.name = name
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── Lifecycle ─────────────────────────────────────────────────────

    @abc.abstractmethod
    async def connect(self) -> None:
        """Establish the connection to the MCP server."""
        ...

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Tear down the connection cleanly."""
        ...

    # ── I/O ───────────────────────────────────────────────────────────

    @abc.abstractmethod
    async def send(self, message: dict[str, Any]) -> None:
        """
        Send a JSON-RPC 2.0 message to the MCP server.

        Args:
            message: A fully-formed JSON-RPC 2.0 request or notification dict.
        """
        ...

    @abc.abstractmethod
    async def receive(self) -> dict[str, Any]:
        """
        Block until a JSON-RPC 2.0 message is received from the server.

        Returns:
            A parsed JSON-RPC 2.0 response or notification dict.
        """
        ...

    # ── Helpers ───────────────────────────────────────────────────────

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        return f"<{self.__class__.__name__} name={self.name!r} {status}>"
