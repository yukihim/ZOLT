"""
ZOLT Custom MCP SDK — Stdio Transport

Launches an MCP server as a subprocess and communicates over stdin/stdout
using newline-delimited JSON-RPC 2.0 messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from ..exceptions import ConnectionError, TransportError
from .base import BaseTransport

logger = logging.getLogger("zolt.transport.stdio")


class StdioTransport(BaseTransport):
    """
    Stdio transport — spawns an MCP server process and communicates
    via its stdin (write) and stdout (read).

    Args:
        command: The executable to launch (e.g. ``"npx"``).
        args: Arguments for the command (e.g. ``["@modelcontextprotocol/server-github"]``).
        env: Optional environment variables to pass to the subprocess.
        name: Human-readable name for logging.
    """

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        name: str = "stdio",
    ):
        super().__init__(name=name)
        self.command = command
        self.args = args or []
        self.env = env
        self._process: asyncio.subprocess.Process | None = None
        self._read_lock = asyncio.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Spawn the MCP server subprocess."""
        if self._connected:
            logger.warning("Already connected to %s", self.name)
            return

        try:
            self._process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env,
            )
            self._connected = True
            logger.info(
                "Stdio transport [%s] started: pid=%s", self.name, self._process.pid
            )
        except FileNotFoundError as exc:
            raise ConnectionError(
                f"Command not found: {self.command}",
                data={"command": self.command, "args": self.args},
            ) from exc
        except OSError as exc:
            raise ConnectionError(str(exc)) from exc

    async def disconnect(self) -> None:
        """Terminate the subprocess and clean up."""
        if self._process is None:
            return

        try:
            if self._process.returncode is None:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self._process.kill()
                    await self._process.wait()
                    logger.warning("Force-killed subprocess [%s]", self.name)
        finally:
            self._process = None
            self._connected = False
            logger.info("Stdio transport [%s] disconnected", self.name)

    # ── I/O ───────────────────────────────────────────────────────────

    async def send(self, message: dict[str, Any]) -> None:
        """Write a JSON-RPC message to the process's stdin."""
        if self._process is None or self._process.stdin is None:
            raise TransportError("Stdio transport is not connected")

        payload = json.dumps(message) + "\n"
        try:
            self._process.stdin.write(payload.encode("utf-8"))
            await self._process.stdin.drain()
            logger.debug("[%s] → %s", self.name, payload.rstrip())
        except (BrokenPipeError, ConnectionResetError) as exc:
            self._connected = False
            raise TransportError(f"Write failed on [{self.name}]: {exc}") from exc

    async def receive(self) -> dict[str, Any]:
        """Read a single JSON-RPC message from the process's stdout."""
        if self._process is None or self._process.stdout is None:
            raise TransportError("Stdio transport is not connected")

        async with self._read_lock:
            try:
                raw = await self._process.stdout.readline()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._connected = False
                raise TransportError(f"Read failed on [{self.name}]: {exc}") from exc

            if not raw:
                self._connected = False
                raise TransportError(
                    f"MCP server [{self.name}] closed stdout (process exited)"
                )

            line = raw.decode("utf-8").strip()
            logger.debug("[%s] ← %s", self.name, line)

            try:
                return json.loads(line)
            except json.JSONDecodeError as exc:
                raise TransportError(
                    f"Invalid JSON from [{self.name}]: {line!r}"
                ) from exc
