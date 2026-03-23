"""
ZOLT Custom MCP SDK — MCP Host (JSON-RPC 2.0 State Machine)

The MCPHost is the brain of the SDK. It manages the full MCP lifecycle:
    initialize → list tools → call tools → shutdown

It maintains a registry of connected MCP servers (each backed by a transport)
and routes tool calls to the correct server.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .exceptions import (
    InitializationError,
    MCPError,
    MethodNotFound,
    TimeoutError,
)
from .transport.base import BaseTransport

logger = logging.getLogger("zolt.host")

# MCP protocol version we advertise
_PROTOCOL_VERSION = "2024-11-05"

# Default timeout for JSON-RPC request → response (seconds)
_DEFAULT_TIMEOUT = 30.0


# ──────────────────────────────────── Data Types ─────────────────────


@dataclass
class ToolDefinition:
    """A tool advertised by an MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str  # which registered server owns this tool


@dataclass
class ServerEntry:
    """A registered MCP server."""

    name: str
    transport: BaseTransport
    initialized: bool = False
    server_info: dict[str, Any] = field(default_factory=dict)
    tools: list[ToolDefinition] = field(default_factory=list)


# ──────────────────────────────────── MCP Host ───────────────────────


class MCPHost:
    """
    MCP Host — connects to one or more MCP servers, discovers their tools,
    and routes JSON-RPC tool‑call requests.

    Usage::

        host = MCPHost()
        host.register("github", StdioTransport("npx", ["-y", "@modelcontextprotocol/server-github"]))
        await host.initialize_all()
        tools = host.get_all_tools()
        result = await host.call_tool("github", "search_repositories", {"query": "fastapi"})
        await host.shutdown_all()
    """

    def __init__(self, timeout: float = _DEFAULT_TIMEOUT):
        self._servers: dict[str, ServerEntry] = {}
        self._timeout = timeout
        self._id_counter = itertools.count(1)

    # ── Server Registration ───────────────────────────────────────────

    def register(self, name: str, transport: BaseTransport) -> None:
        """Register an MCP server with a given transport."""
        if name in self._servers:
            raise ValueError(f"Server '{name}' is already registered")
        self._servers[name] = ServerEntry(name=name, transport=transport)
        logger.info("Registered MCP server: %s (%s)", name, transport)

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def initialize_all(self) -> None:
        """Connect transports and run the MCP `initialize` handshake on all servers."""
        tasks = [self._initialize_server(entry) for entry in self._servers.values()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for entry, result in zip(self._servers.values(), results):
            if isinstance(result, Exception):
                logger.error("Failed to initialize [%s]: %s", entry.name, result)
                raise result

    async def shutdown_all(self) -> None:
        """Send shutdown notification and disconnect all transports."""
        for entry in self._servers.values():
            try:
                if entry.initialized:
                    # MCP shutdown is a notification (no response expected)
                    await self._send_notification(entry, "shutdown", {})
                await entry.transport.disconnect()
                entry.initialized = False
                logger.info("Server [%s] shut down", entry.name)
            except Exception as exc:
                logger.warning("Error shutting down [%s]: %s", entry.name, exc)

    async def _initialize_server(self, entry: ServerEntry) -> None:
        """
        Run the MCP initialize handshake for a single server:
        1. Connect the transport.
        2. Send ``initialize`` request.
        3. Send ``notifications/initialized`` notification.
        4. Send ``tools/list`` to discover available tools.
        """
        await entry.transport.connect()

        # Step 1: initialize
        init_response = await self._send_request(
            entry,
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "zolt-host", "version": "1.0.0"},
            },
        )

        if "error" in init_response:
            raise InitializationError(
                f"Server [{entry.name}] rejected initialize: {init_response['error']}"
            )

        entry.server_info = init_response.get("result", {})
        logger.info(
            "Server [%s] initialized: %s",
            entry.name,
            entry.server_info.get("serverInfo", {}),
        )

        # Step 2: Send initialized notification
        await self._send_notification(entry, "notifications/initialized", {})

        # Step 3: Discover tools
        tools_response = await self._send_request(entry, "tools/list", {})
        raw_tools = tools_response.get("result", {}).get("tools", [])
        entry.tools = [
            ToolDefinition(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
                server_name=entry.name,
            )
            for t in raw_tools
        ]
        entry.initialized = True
        logger.info(
            "Server [%s] ready — %d tools available", entry.name, len(entry.tools)
        )

    # ── Tool Discovery ────────────────────────────────────────────────

    def get_all_tools(self) -> list[ToolDefinition]:
        """Return a flat list of tools across all registered servers."""
        tools: list[ToolDefinition] = []
        for entry in self._servers.values():
            tools.extend(entry.tools)
        return tools

    def get_tools_json(self) -> list[dict[str, Any]]:
        """
        Return tools as a list of dicts suitable for sending to an LLM
        as function/tool definitions.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in self.get_all_tools()
        ]

    def find_server_for_tool(self, tool_name: str) -> ServerEntry | None:
        """Look up which server owns a given tool name."""
        for entry in self._servers.values():
            for tool in entry.tools:
                if tool.name == tool_name:
                    return entry
        return None

    # ── Tool Execution ────────────────────────────────────────────────

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Call a tool by name. The host automatically routes the call
        to the correct registered server.

        Returns:
            The ``result`` field from the JSON-RPC response.

        Raises:
            MethodNotFound: If no server owns this tool.
            MCPError: If the server returns a JSON-RPC error.
        """
        entry = self.find_server_for_tool(tool_name)
        if entry is None:
            raise MethodNotFound(f"No server owns tool '{tool_name}'")

        start = time.perf_counter()
        response = await self._send_request(
            entry,
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )
        elapsed = time.perf_counter() - start

        if "error" in response:
            err = response["error"]
            logger.error(
                "[%s] Tool '%s' failed (%.2fs): %s",
                entry.name,
                tool_name,
                elapsed,
                err,
            )
            raise MCPError(
                message=err.get("message", "Tool call failed"),
                code=err.get("code", -1),
                data=err.get("data"),
            )

        logger.info(
            "[%s] Tool '%s' succeeded (%.2fs)", entry.name, tool_name, elapsed
        )
        return response.get("result", {})

    # ── JSON-RPC I/O Primitives ───────────────────────────────────────

    async def _send_request(
        self, entry: ServerEntry, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a JSON-RPC 2.0 request and wait for the response."""
        req_id = next(self._id_counter)
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        await entry.transport.send(request)

        try:
            response = await asyncio.wait_for(
                entry.transport.receive(), timeout=self._timeout
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Request to [{entry.name}] timed out after {self._timeout}s",
                data={"method": method, "id": req_id},
            )

        return response

    async def _send_notification(
        self, entry: ServerEntry, method: str, params: dict[str, Any]
    ) -> None:
        """Send a JSON-RPC 2.0 notification (no response expected)."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        await entry.transport.send(notification)
