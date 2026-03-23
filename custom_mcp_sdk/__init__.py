"""
ZOLT Custom MCP SDK
───────────────────
Zero Overhead LLM Transport — a from-scratch Python implementation
of a Model Context Protocol (MCP) Host using JSON-RPC 2.0.

Public API:
    MCPHost          — The main host / state machine
    StdioTransport   — Subprocess-based transport (stdin/stdout)
    SSETransport     — HTTP SSE-based transport
    Exceptions       — Full JSON-RPC 2.0 error hierarchy
"""

from .exceptions import (
    ConnectionError,
    InitializationError,
    InternalError,
    InvalidParams,
    InvalidRequest,
    MCPError,
    MethodNotFound,
    ParseError,
    TimeoutError,
    TransportError,
)
from .host import MCPHost, ToolDefinition
from .transport import SSETransport, StdioTransport

__all__ = [
    # Host
    "MCPHost",
    "ToolDefinition",
    # Transports
    "StdioTransport",
    "SSETransport",
    # Exceptions
    "MCPError",
    "ParseError",
    "InvalidRequest",
    "MethodNotFound",
    "InvalidParams",
    "InternalError",
    "ConnectionError",
    "InitializationError",
    "TransportError",
    "TimeoutError",
]

__version__ = "1.0.0"
