"""
ZOLT Backend — FastAPI Application

API Gateway exposing:
  POST /api/chat     — User prompt → agent response
  GET  /api/evals    — Evaluation metrics
  GET  /api/evals/summary — Aggregate eval stats
  GET  /api/health   — Health check
  GET  /metrics      — Prometheus-compatible metrics
"""

from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from prometheus_client import (
    Counter,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from fastapi.responses import StreamingResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles

# ── Bootstrap ─────────────────────────────────────────────────────────

load_dotenv()

# Add project root to path so custom_mcp_sdk is importable
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from custom_mcp_sdk import MCPHost, StdioTransport  # noqa: E402

from .agent import Agent  # noqa: E402
from .database import get_all_evals, get_eval_summary, init_db, insert_eval  # noqa: E402

# ── Logging ───────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-20s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("zolt.api")

# ── Prometheus Metrics ────────────────────────────────────────────────

REQUEST_COUNT = Counter(
    "zolt_http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"]
)
CHAT_LATENCY = Histogram(
    "zolt_chat_latency_seconds", "Chat endpoint latency in seconds"
)

# ── MCP Host Setup ────────────────────────────────────────────────────

mcp_host = MCPHost()
agent: Agent | None = None


def _register_mcp_servers() -> None:
    """Register configured MCP servers with the host."""
    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        mcp_host.register(
            "github",
            StdioTransport(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-github"],
                env={**os.environ, "GITHUB_PERSONAL_ACCESS_TOKEN": github_token},
                name="github",
            ),
        )
        logger.info("GitHub MCP server registered")
    else:
        logger.warning("GITHUB_TOKEN not set — GitHub MCP server skipped")


# ── Application Lifecycle ─────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown hooks."""
    global agent

    # Startup
    logger.info("═══ ZOLT Backend starting ═══")
    await init_db()
    _register_mcp_servers()

    try:
        await mcp_host.initialize_all()
    except Exception as exc:
        logger.warning("MCP initialization skipped: %s", exc)

    agent = Agent(mcp_host)
    logger.info("═══ ZOLT Backend ready ═══")

    yield

    # Shutdown
    logger.info("═══ ZOLT Backend shutting down ═══")
    if agent:
        await agent.close()
    await mcp_host.shutdown_all()


# ── FastAPI App ───────────────────────────────────────────────────────

app = FastAPI(
    title="ZOLT — Zero Overhead LLM Transport",
    description="Agentic IT Operations Platform API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static Files (Frontend) ───────────────────────────────────────────
# Mount the built frontend static directory
# This should match where the root Dockerfile places the 'build' folder
STATIC_DIR = os.path.join(PROJECT_ROOT, "backend", "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ── Request / Response Models ─────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    conversation_history: list[dict[str, Any]] | None = None


class ChatResponse(BaseModel):
    reply: str
    turn_id: str


class ApprovalRequest(BaseModel):
    turn_id: str
    approval_id: str
    approved: bool


# ── Endpoints ─────────────────────────────────────────────────────────


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Process a user message and stream the response via SSE."""
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    REQUEST_COUNT.labels(method="POST", endpoint="/api/chat", status="200").inc()

    async def event_stream():
        with CHAT_LATENCY.time():
            async for event in agent.stream_run(
                user_message=request.message,
                conversation_history=request.conversation_history,
            ):
                if event.get("type") == "done" and "metrics" in event:
                    try:
                        await insert_eval(event["metrics"])
                    except Exception as exc:
                        logger.error("Failed to persist eval: %s", exc)
                yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/chat/approve")
async def approve_chat(request: ApprovalRequest):
    """Provide approval or rejection for a pending tool call."""
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    if request.approval_id not in agent.pending_approvals:
        raise HTTPException(status_code=404, detail="No pending tool call found for this approval ID")

    # Set the result of the future to resume the agent loop
    future = agent.pending_approvals[request.approval_id]
    if not future.done():
        future.set_result(request.approved)
        logger.info("Approval [%s] %s by user", request.approval_id, "APPROVED" if request.approved else "REJECTED")
    
    return {"status": "ok"}


@app.get("/api/evals")
async def get_evals(limit: int = 100):
    """Return the most recent evaluation logs."""
    return await get_all_evals(limit=limit)


@app.get("/api/evals/summary")
async def evals_summary():
    """Return aggregate evaluation statistics."""
    return await get_eval_summary()


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    connected_servers = [
        name
        for name, entry in mcp_host._servers.items()
        if entry.initialized
    ]
    return {
        "status": "healthy",
        "version": "1.0.0",
        "mcp_servers": connected_servers,
    }


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus-compatible metrics endpoint."""
    REQUEST_COUNT.labels(method="GET", endpoint="/metrics", status="200").inc()
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


# ── Catch-all route for React ─────────────────────────────────────────
@app.get("/{rest_of_path:path}")
async def serve_index(rest_of_path: str):
    """Serve index.html for any unknown route (React client routing)."""
    # If the file exists in the static dir, the StaticFiles mount should have caught it.
    # Otherwise, serve index.html.
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {"error": "Frontend static files not found. Ensure the build folder exists."}
