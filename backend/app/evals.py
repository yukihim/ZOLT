"""
ZOLT Backend — Evaluation Metrics Engine

Tracks per-turn telemetry:
  - T_lat  (turn latency)
  - TSR    (tool success rate)
  - Token usage
  - Context density

All metrics are logged to the terminal and persisted to SQLite.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger("zolt.evals")


@dataclass
class TurnMetrics:
    """Telemetry collected during a single agent turn."""

    turn_id: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tool_calls_total: int = 0
    tool_calls_success: int = 0
    tool_calls_failed: int = 0
    latency_seconds: float = 0.0
    context_density: float = 0.0  # relevant_tokens / total_tokens

    @property
    def tool_success_rate(self) -> float:
        """Percentage of tool calls that succeeded."""
        if self.tool_calls_total == 0:
            return 1.0
        return self.tool_calls_success / self.tool_calls_total

    def to_dict(self) -> dict:
        return {
            "turn_id": self.turn_id,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "tool_calls_total": self.tool_calls_total,
            "tool_calls_success": self.tool_calls_success,
            "tool_calls_failed": self.tool_calls_failed,
            "tool_success_rate": round(self.tool_success_rate, 4),
            "latency_seconds": round(self.latency_seconds, 4),
            "context_density": round(self.context_density, 4),
        }


class EvalTracker:
    """
    Tracks evaluation metrics for agent turns.
    Logs every turn to the terminal and provides data for persistence.
    """

    def __init__(self):
        self._current: TurnMetrics | None = None
        self._start_time: float = 0.0

    def start_turn(self, turn_id: str) -> None:
        """Begin tracking a new agent turn."""
        self._current = TurnMetrics(turn_id=turn_id)
        self._start_time = time.perf_counter()
        logger.info("━━━ Turn [%s] started ━━━", turn_id)

    def record_llm_usage(
        self, prompt_tokens: int, completion_tokens: int, total_tokens: int
    ) -> None:
        """Record token usage from an LLM response."""
        if self._current is None:
            return
        self._current.prompt_tokens += prompt_tokens
        self._current.completion_tokens += completion_tokens
        self._current.total_tokens += total_tokens

    def record_tool_call(self, tool_name: str, success: bool) -> None:
        """Record the result of a single tool call."""
        if self._current is None:
            return
        self._current.tool_calls_total += 1
        if success:
            self._current.tool_calls_success += 1
            logger.info("  ✓ Tool '%s' succeeded", tool_name)
        else:
            self._current.tool_calls_failed += 1
            logger.warning("  ✗ Tool '%s' failed", tool_name)

    def set_context_density(self, relevant_tokens: int) -> None:
        """Set context density as relevant_tokens / total_tokens."""
        if self._current is None or self._current.total_tokens == 0:
            return
        self._current.context_density = relevant_tokens / self._current.total_tokens

    def end_turn(self) -> TurnMetrics:
        """Finalize the turn and log summary to terminal."""
        if self._current is None:
            return TurnMetrics()

        self._current.latency_seconds = time.perf_counter() - self._start_time
        metrics = self._current
        self._current = None

        # ── Terminal telemetry log ────────────────────────────────────
        logger.info("━━━ Turn [%s] complete ━━━", metrics.turn_id)
        logger.info("  T_lat         : %.3fs", metrics.latency_seconds)
        logger.info(
            "  Tokens        : %d prompt / %d completion / %d total",
            metrics.prompt_tokens,
            metrics.completion_tokens,
            metrics.total_tokens,
        )
        logger.info(
            "  TSR           : %.1f%% (%d/%d)",
            metrics.tool_success_rate * 100,
            metrics.tool_calls_success,
            metrics.tool_calls_total,
        )
        logger.info("  Context Density: %.4f", metrics.context_density)
        logger.info("━" * 40)

        return metrics
