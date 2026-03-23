"""
ZOLT Backend — LLM Agent Reasoning Loop (OpenRouter)

Implements a tool-use agent loop:
1. Send user prompt + tool definitions to OpenRouter API
2. If the LLM returns tool calls → route them through MCPHost
3. Feed tool results back to LLM
4. Repeat until LLM returns a final text response

Telemetry is logged to terminal via EvalTracker (not returned in chat).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any

from .tools import GITHUB_TOOLS

import httpx

from custom_mcp_sdk import MCPHost

from .evals import EvalTracker, TurnMetrics

logger = logging.getLogger("zolt.agent")

# ── Provider-Agnostic LLM API Configuration ──────────────────────────
API_BASE_URL = os.getenv("API_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
API_KEY = os.getenv("API_KEY", os.getenv("OPENROUTER_API_KEY", ""))
MODEL = os.getenv("MODEL", os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-r1:free"))

SYSTEM_PROMPT = """\
You are ZOLT, an AI IT Operations Coordinator. You help manage system health, \
triage bug reports, and retrieve documentation.

### CORE OPERATING PRINCIPLE
You have access to real-time tools via function calling. When a user asks about \
GitHub repositories, commits, issues, or code — you MUST use the available tools.
NEVER summarize or guess if you can fetch real data.

### TOOL CALLING PROTOCOLS (CRITICAL)
- You MUST use the OpenAI-compatible `tool_calls` field for all tool invocations.
- NEVER output raw JSON blocks, markdown code blocks, or tool-calling syntax in your main text "content" field.
- If you need to call a tool, call it directly via the API side-channel.
- Your goal is to be accurate; always call the appropriate tool first.

The user's default GitHub repository is "yukihim/ZOLT". If the user asks general \
questions like "latest commit?", "what are my issues?", or refers to "this project", \
you MUST assume they are asking about owner="yukihim" and repo="ZOLT" without asking for help.

If a tool call fails, explain the exact error clearly."""

MAX_ITERATIONS = 10  # safety limit for tool-call loops

# Tools that require explicit user approval before execution
SENSITIVE_TOOLS = {
    # File / repo mutations
    "create_repository",
    "fork_repository",
    "create_branch",
    "create_or_update_file",
    "push_files",
    "delete_file",
    # Issues
    "create_issue",
    "update_issue",
    "add_comment_to_issue",
    # Pull requests
    "create_pull_request",
    "update_pull_request",
    "merge_pull_request",
    "create_pull_request_review",
}


# ── Agent ─────────────────────────────────────────────────────────────


class Agent:
    """
    Tool-use agent backed by OpenRouter and the ZOLT MCP Host.
    """

    def __init__(self, mcp_host: MCPHost):
        self.mcp_host = mcp_host
        self.tracker = EvalTracker()
        self._http = httpx.AsyncClient(timeout=60.0)
        # Registry for pending tool approvals {turn_id: asyncio.Future}
        self.pending_approvals: dict[str, asyncio.Future[bool]] = {}

    async def close(self) -> None:
        await self._http.aclose()

    async def stream_run(
        self,
        user_message: str,
        conversation_history: list[dict[str, Any]] | None = None,
    ):
        """
        Execute the full agent loop for a user message as an async generator.

        Yields:
            JSON-serializable dictionaries representing events (type: start, tool_start, tool_end, message, done, error).
        """
        turn_id = uuid.uuid4().hex[:8]
        self.tracker.start_turn(turn_id)
        yield {"type": "start", "turn_id": turn_id}

        # Build and Sanitize Message History
        # Most local models (llama3, qwen) crash or hallucinate if roles aren't strictly alternating.
        raw_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if conversation_history:
            raw_messages.extend(conversation_history[-6:])
        raw_messages.append({"role": "user", "content": user_message})

        messages: list[dict[str, Any]] = []
        for msg in raw_messages:
            if messages and messages[-1]["role"] == msg["role"]:
                # Merge consecutive roles to maintain ChatML validity
                messages[-1]["content"] += "\n" + msg["content"]
            else:
                messages.append(msg)

        # Get available tools from MCP host
        tools = GITHUB_TOOLS

        # ── Agent loop ────────────────────────────────────────────────
        for iteration in range(MAX_ITERATIONS):
            logger.info("Agent iteration %d/%d", iteration + 1, MAX_ITERATIONS)

            message: dict[str, Any] = {"role": "assistant", "content": "", "tool_calls": []}
            finish_reason = None
            first_chunk = True

            async for chunk in self._stream_llm(messages, tools):
                if first_chunk and "model" in chunk:
                    logger.info("OpenRouter stream started [Model: %s]", chunk["model"])
                    first_chunk = False

                # Usage only arrives on the final chunk if stream_options requested it
                if "usage" in chunk and chunk["usage"]:
                    u = chunk["usage"]
                    self.tracker.record_llm_usage(
                        prompt_tokens=u.get("prompt_tokens", 0),
                        completion_tokens=u.get("completion_tokens", 0),
                        total_tokens=u.get("total_tokens", 0),
                    )

                choices = chunk.get("choices", [])
                if not choices:
                    continue
                
                choice = choices[0]
                delta = choice.get("delta", {})

                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

                # Text streaming
                if delta.get("content"):
                    text = delta["content"]
                    message["content"] += text
                    yield {"type": "token", "content": text}

                # Tool call streaming accumulation
                if delta.get("tool_calls"):
                    for tc_delta in delta["tool_calls"]:
                        idx = tc_delta.get("index", 0)
                        while len(message["tool_calls"]) <= idx:
                            message["tool_calls"].append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                        
                        tc_accum = message["tool_calls"][idx]
                        if tc_delta.get("id"):
                            tc_accum["id"] = tc_delta["id"]
                        
                        func_delta = tc_delta.get("function", {})
                        if func_delta.get("name"):
                            tc_accum["function"]["name"] += func_delta["name"]
                        if func_delta.get("arguments"):
                            tc_accum["function"]["arguments"] += func_delta["arguments"]

            # Append assistant message to history
            # Remove empty tool_calls list if no tools were called
            if not message["tool_calls"]:
                del message["tool_calls"]
            messages.append(message)

            # Check for tool calls
            tool_calls = message.get("tool_calls")

            if not tool_calls or finish_reason == "stop":
                # Final text response finished streaming
                metrics = self.tracker.end_turn()
                if not message.get("content") and iteration > 0:
                    yield {"type": "token", "content": "I've completed the tool operations, but the model did not generate a final summary."}
                yield {"type": "done", "metrics": metrics.to_dict()}
                return

            # ── Execute tool calls ────────────────────────────────────
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                try:
                    arguments = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    arguments = {}

                # ── HITL: Check for Sensitive Tools ──────────────────
                if tool_name in SENSITIVE_TOOLS:
                    logger.info("Sensitive tool detected: %s. Waiting for approval...", tool_name)
                    yield {
                        "type": "approval_required",
                        "turn_id": turn_id,
                        "tool": tool_name,
                        "args": arguments
                    }
                    
                    # Wait for the API to satisfy the future
                    loop = asyncio.get_running_loop()
                    self.pending_approvals[turn_id] = loop.create_future()
                    
                    try:
                        approved = await self.pending_approvals[turn_id]
                    finally:
                        self.pending_approvals.pop(turn_id, None)
                    
                    if not approved:
                        logger.warning("Tool '%s' rejected by user.", tool_name)
                        tool_content = json.dumps({"error": "Action rejected by user."})
                        yield {"type": "tool_end", "tool": tool_name, "preview": "Rejected by user", "is_error": True}
                        # Append rejection to history so LLM knows it wasn't a technical failure
                        messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": tool_content})
                        continue

                logger.info("Calling tool: %s(%s)", tool_name, arguments)
                yield {"type": "tool_start", "tool": tool_name, "args": arguments}

                try:
                    result = await self.mcp_host.call_tool(tool_name, arguments)
                    self.tracker.record_tool_call(tool_name, success=True)
                    tool_content = json.dumps(result, indent=2, default=str)
                    yield {"type": "tool_end", "tool": tool_name, "preview": tool_content}
                except Exception as exc:
                    self.tracker.record_tool_call(tool_name, success=False)
                    tool_content = json.dumps({"error": str(exc)})
                    logger.error("Tool '%s' error: %s", tool_name, exc)
                    yield {"type": "tool_end", "tool": tool_name, "preview": f"Error: {exc}", "is_error": True}

                # Append tool result for the LLM
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": tool_content,
                    }
                )

        # If we exhaust iterations, return what we have
        metrics = self.tracker.end_turn()
        yield {"type": "message", "content": "I've reached the maximum number of tool-call iterations. Please try rephrasing your request."}
        yield {"type": "done", "metrics": metrics.to_dict()}

    async def _stream_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ):
        """Make a streaming call to the completions API."""
        payload: dict[str, Any] = {
            "model": MODEL,
            "messages": messages,
            "temperature": 0.1,
            "stream": True,
            "stream_options": {"include_usage": True}
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/yukihim/ZOLT",
            "X-Title": "ZOLT",
        }

        async with self._http.stream(
            "POST", API_BASE_URL, json=payload, headers=headers
        ) as response:
            if not response.is_success:
                err_bytes = await response.aread()
                logger.error(
                    "LLM API error %s: %s",
                    response.status_code,
                    err_bytes.decode(errors='replace')
                )
                response.raise_for_status()

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk_data = json.loads(data_str)
                        # DEBUG: Log the raw chunk structure to catch tool-calling leaks
                        logger.debug("RAW_LLM_CHUNK: %s", data_str)
                        yield chunk_data
                    except json.JSONDecodeError:
                        pass
