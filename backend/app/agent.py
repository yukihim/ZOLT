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

import httpx
from huggingface_hub import AsyncInferenceClient

from custom_mcp_sdk import MCPHost

from .evals import EvalTracker
from .tools import GITHUB_TOOLS
# Used by the hallucination guard to detect when the model passes
# result-shaped data (e.g. {"content": "...", "files": [...]}) as arguments.
# Multiple entries with the same name (issue_write, pull_request_read) are
# merged — they share the same parameter set anyway.
TOOL_PARAM_NAMES: dict[str, set[str]] = {}
for _t in GITHUB_TOOLS:
    _name = _t["function"]["name"]
    _props = set(_t["function"]["parameters"].get("properties", {}).keys())
    TOOL_PARAM_NAMES.setdefault(_name, set()).update(_props)

logger = logging.getLogger("zolt.agent")

# ── Provider LLM API Configuration ──────────────────────────────────
# Default to Hugging Face Space integration as per user direction
API_TOKEN = os.getenv("API_TOKEN")
MODEL = os.getenv("MODEL", "openai/gpt-oss-20b")

SYSTEM_PROMPT = """
You are ZOLT, an AI IT Operations Coordinator. You help manage system health, 
triage bug reports, and retrieve documentation.

### CORE OPERATING PRINCIPLE
You have access to real-time tools via function calling. When a user asks about 
GitHub repositories, commits, issues, or code — you MUST use the available tools.
NEVER summarize or guess if you can fetch real data.

### TOOL CALLING PROTOCOLS (CRITICAL)
- You MUST use the OpenAI-compatible `tool_calls` field for all tool invocations.
- NEVER output raw JSON blocks, markdown code blocks, or tool-calling syntax in your main text "content" field.
- If you need to call a tool, call it directly via the API side-channel.
- Your goal is to be accurate; always call the appropriate tool first.

### FILE AND CODE CONTENT — ABSOLUTE RULES
- You MUST NEVER write, generate, invent, or assume the contents of any file.
- You have NO knowledge of what any file in this repository contains.
- The ONLY valid source of file content is a successful `get_file_contents` tool call.
- If `get_file_contents` fails (Not Found, permission error, any error): STOP.
  Tell the user the file could not be retrieved. Do NOT attempt to reconstruct
  or guess what the file might contain based on its name or your training data.
- NEVER pass invented file contents as an argument to any tool call.

### WHEN TOOLS FAIL
- If a tool returns an error, report that error to the user and stop.
- Do NOT retry the same tool call with the same arguments.
- Do NOT invent a result and continue as if the tool succeeded.
- Do NOT pass a tool's error message or any fabricated data as arguments to another tool.

The user's default GitHub repository is "yukihim/ZOLT". If the user asks general \
questions like "latest commit?", "what are my issues?", or refers to "this project", \
you MUST assume they are asking about owner="yukihim" and repo="ZOLT" without asking for help."""

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
    # Issues  (issue_write covers both create+update; add_issue_comment is the correct MCP name)
    "issue_write",
    "add_issue_comment",
    # Pull requests  (pull_request_review_write is the correct MCP name)
    "create_pull_request",
    "update_pull_request",
    "merge_pull_request",
    "pull_request_review_write",
}


# ── Agent ─────────────────────────────────────────────────────────────────────────

class Agent:
    """
    Tool-use agent backed by OpenRouter and the ZOLT MCP Host.
    """

    def __init__(self, mcp_host: MCPHost):
        self.mcp_host = mcp_host
        self.tracker = EvalTracker()
        self._http = httpx.AsyncClient(timeout=60.0)
        self.inference = AsyncInferenceClient(model=MODEL, token=API_TOKEN)
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
        # Track (tool_name, args_json) pairs we've already executed this turn
        # to prevent the model from looping on the same failing call.
        seen_calls: set[str] = set()
        approval_counter = 0  # unique ID per sensitive tool call within this turn

        for iteration in range(MAX_ITERATIONS):
            logger.info("Agent iteration %d/%d", iteration + 1, MAX_ITERATIONS)

            message: dict[str, Any] = {"role": "assistant", "content": None, "tool_calls": []}
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

                # Text streaming — accumulate into content (upgrade None → str on first token)
                if delta.get("content"):
                    text = delta["content"]
                    if message["content"] is None:
                        message["content"] = text
                    else:
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

            # Append assistant message to history.
            # HuggingFace (and most OpenAI-compatible APIs) reject content="" or
            # content=None when tool_calls are present — drop the key entirely
            # if there was no text, and drop tool_calls if empty.
            if not message["tool_calls"]:
                del message["tool_calls"]
            if message["content"] is None or message["content"] == "":
                # Only keep content if it has actual text
                if message.get("tool_calls"):
                    # Pure tool-call turn: content must be absent or null, never ""
                    del message["content"]
                else:
                    # Pure text turn with nothing: keep null so role is still valid
                    message["content"] = None
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

            # ── Execute tool calls ─────────────────────────────────────────────────
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                try:
                    arguments = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    arguments = {}

                # ── HITL: Check for Sensitive Tools ───────────────────────────────
                if tool_name in SENSITIVE_TOOLS:
                    approval_id = f"{turn_id}_{approval_counter}"
                    approval_counter += 1
                    logger.info("Sensitive tool detected: %s [approval_id=%s]. Waiting for approval...", tool_name, approval_id)
                    yield {
                        "type": "approval_required",
                        "turn_id": turn_id,
                        "approval_id": approval_id,
                        "tool": tool_name,
                        "args": arguments
                    }
                    
                    # Wait for the API to satisfy the future
                    loop = asyncio.get_running_loop()
                    self.pending_approvals[approval_id] = loop.create_future()
                    
                    try:
                        approved = await self.pending_approvals[approval_id]
                    finally:
                        self.pending_approvals.pop(approval_id, None)
                    
                    if not approved:
                        logger.warning("Tool '%s' rejected by user.", tool_name)
                        tool_content = json.dumps({"error": "Action rejected by user."})
                        yield {"type": "tool_end", "tool": tool_name, "preview": "Rejected by user", "is_error": True}
                        # Append rejection to history so LLM knows it wasn't a technical failure
                        messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": tool_content})
                        continue

                logger.info("Calling tool: %s(%s)", tool_name, arguments)
                yield {"type": "tool_start", "tool": tool_name, "args": arguments}

                # ── Hallucination guard ───────────────────────────────
                # The model sometimes fabricates a tool *result* and passes it
                # back as the *arguments* of the next call, e.g.:
                #   get_file_contents({"content": "# agent.py..."})
                #   get_repository_tree({"files": [...]})
                #   list_branches({"branches": [...]})
                # Detect this by checking whether any argument key falls
                # outside the tool's declared parameter schema.
                valid_params = TOOL_PARAM_NAMES.get(tool_name)
                if valid_params is None:
                    # The model called a tool that doesn't exist at all.
                    logger.warning("Unknown tool '%s' called — rejecting.", tool_name)
                    tool_content = json.dumps({
                        "error": f"'{tool_name}' is not a recognised tool. Do NOT invent tool names. Stop and explain to the user what you were trying to do.",
                    })
                    yield {"type": "tool_end", "tool": tool_name, "preview": "Unknown tool — rejected", "is_error": True}
                    messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": tool_content})
                    continue

                unknown_keys = set(arguments.keys()) - valid_params
                if unknown_keys:
                    logger.warning(
                        "Hallucination detected: tool '%s' called with unrecognised arg keys %s (valid: %s)",
                        tool_name, unknown_keys, valid_params,
                    )
                    tool_content = json.dumps({
                        "error": (
                            f"Invalid arguments for '{tool_name}': unrecognised keys {sorted(unknown_keys)}. "
                            f"Valid parameters are: {sorted(valid_params)}. "
                            "You appear to have passed a previous tool result as arguments. "
                            "Do NOT retry. Summarise what you know and respond to the user."
                        )
                    })
                    yield {"type": "tool_end", "tool": tool_name, "preview": f"Hallucination detected — unrecognised keys {unknown_keys}", "is_error": True}
                    messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": tool_content})
                    continue

                # ── Dedup guard ───────────────────────────────────────
                # Prevent infinite retry loops on an identical failing call.
                call_fingerprint = f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"
                if call_fingerprint in seen_calls:
                    logger.warning("Duplicate tool call detected: %s — skipping.", call_fingerprint)
                    tool_content = json.dumps({
                        "error": f"This exact call to '{tool_name}' was already made and failed this turn. Do NOT retry it. Explain the failure to the user instead."
                    })
                    yield {"type": "tool_end", "tool": tool_name, "preview": "Duplicate call — skipped", "is_error": True}
                    messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": tool_content})
                    continue
                seen_calls.add(call_fingerprint)

                try:
                    result = await self.mcp_host.call_tool(tool_name, arguments)
                    self.tracker.record_tool_call(tool_name, success=True)
                    tool_content = json.dumps(result, indent=2, default=str)
                    yield {"type": "tool_end", "tool": tool_name, "preview": tool_content}
                except Exception as exc:
                    self.tracker.record_tool_call(tool_name, success=False)
                    error_msg = str(exc)

                    # For file-fetch tools, add a hard reinforcement so the model
                    # does not fall back to synthesising content from training data.
                    if tool_name in {"get_file_contents", "get_repository_tree"}:
                        extra = (
                            " CRITICAL: Do NOT generate, guess, or reconstruct the file or "
                            "directory contents from your training data. You have no knowledge "
                            "of what this file contains. Tell the user the fetch failed and stop."
                        )
                    else:
                        extra = (
                            " Do NOT call this tool again with the same arguments. "
                            "Do NOT pass this error as arguments to another tool."
                        )

                    tool_content = json.dumps({
                        "error": error_msg,
                        "instruction": (
                            "This tool call failed." + extra
                        )
                    })
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
        """Make a streaming call to the HF Inference API via AsyncInferenceClient."""

        # Build kwargs for HF chat_completion
        kwargs: dict[str, Any] = {
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 4096,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        logger.info("Calling HF Inference API [model=%s]", MODEL)

        stream = await self.inference.chat_completion(**kwargs)

        async for chunk in stream:
            # chunk is a ChatCompletionStreamOutput object — convert to dict
            # so the existing agent loop can consume it unchanged.
            choices_out = []
            for ch_choice in (chunk.choices or []):
                delta_dict: dict[str, Any] = {}
                if ch_choice.delta:
                    if ch_choice.delta.content:
                        delta_dict["content"] = ch_choice.delta.content
                    if ch_choice.delta.tool_calls:
                        tc_list = []
                        for tc in ch_choice.delta.tool_calls:
                            tc_dict: dict[str, Any] = {"index": tc.index}
                            if tc.id:
                                tc_dict["id"] = tc.id
                            if tc.function:
                                func: dict[str, str] = {}
                                if tc.function.name:
                                    func["name"] = tc.function.name
                                if tc.function.arguments:
                                    func["arguments"] = tc.function.arguments
                                tc_dict["function"] = func
                            tc_list.append(tc_dict)
                        delta_dict["tool_calls"] = tc_list

                choices_out.append({
                    "delta": delta_dict,
                    "finish_reason": ch_choice.finish_reason,
                })

            yield {
                "choices": choices_out,
                "model": MODEL,
                "usage": getattr(chunk, "usage", None),
            }