"""
ZOLT Custom MCP SDK — JSON-RPC 2.0 Exception Hierarchy

Implements the standard JSON-RPC 2.0 error codes as typed Python exceptions,
plus MCP-specific protocol errors for lifecycle management.
"""


class MCPError(Exception):
    """Base exception for all MCP SDK errors."""

    def __init__(self, message: str, code: int = -1, data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}

    def to_jsonrpc(self) -> dict:
        """Serialize to a JSON-RPC 2.0 error object."""
        error = {"code": self.code, "message": self.message}
        if self.data:
            error["data"] = self.data
        return error


# ──────────────────────────────────── Standard JSON-RPC 2.0 Errors ────


class ParseError(MCPError):
    """Invalid JSON was received by the server (-32700)."""

    def __init__(self, message: str = "Parse error", data: dict | None = None):
        super().__init__(message, code=-32700, data=data)


class InvalidRequest(MCPError):
    """The JSON sent is not a valid Request object (-32600)."""

    def __init__(self, message: str = "Invalid request", data: dict | None = None):
        super().__init__(message, code=-32600, data=data)


class MethodNotFound(MCPError):
    """The method does not exist or is not available (-32601)."""

    def __init__(self, message: str = "Method not found", data: dict | None = None):
        super().__init__(message, code=-32601, data=data)


class InvalidParams(MCPError):
    """Invalid method parameter(s) (-32602)."""

    def __init__(self, message: str = "Invalid params", data: dict | None = None):
        super().__init__(message, code=-32602, data=data)


class InternalError(MCPError):
    """Internal JSON-RPC error (-32603)."""

    def __init__(self, message: str = "Internal error", data: dict | None = None):
        super().__init__(message, code=-32603, data=data)


# ──────────────────────────────────── MCP Protocol Errors ─────────────


class ConnectionError(MCPError):
    """Failed to connect to an MCP server."""

    def __init__(self, message: str = "Connection failed", data: dict | None = None):
        super().__init__(message, code=-32000, data=data)


class InitializationError(MCPError):
    """MCP `initialize` handshake failed."""

    def __init__(
        self, message: str = "Initialization failed", data: dict | None = None
    ):
        super().__init__(message, code=-32001, data=data)


class TransportError(MCPError):
    """Underlying transport layer failure (stdio pipe broken, SSE stream dropped)."""

    def __init__(self, message: str = "Transport error", data: dict | None = None):
        super().__init__(message, code=-32002, data=data)


class TimeoutError(MCPError):
    """A request to an MCP server timed out."""

    def __init__(self, message: str = "Request timed out", data: dict | None = None):
        super().__init__(message, code=-32003, data=data)
