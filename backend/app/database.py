"""
ZOLT Backend — SQLite Database for Evaluation Logs

Async SQLite via aiosqlite. Auto-creates tables on startup.
"""

from __future__ import annotations

import aiosqlite
import logging
import os
from typing import Any

logger = logging.getLogger("zolt.database")

DB_PATH = os.getenv("ZOLT_DB_PATH", "data/zolt_evals.db")


async def init_db() -> None:
    """Create the evals table if it doesn't exist."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_logs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                turn_id         TEXT NOT NULL,
                timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP,
                prompt_tokens   INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens    INTEGER DEFAULT 0,
                tool_calls_total INTEGER DEFAULT 0,
                tool_calls_success INTEGER DEFAULT 0,
                tool_calls_failed INTEGER DEFAULT 0,
                tool_success_rate REAL DEFAULT 1.0,
                latency_seconds REAL DEFAULT 0.0,
                context_density REAL DEFAULT 0.0
            )
            """
        )
        await db.commit()
    logger.info("Database initialized at %s", DB_PATH)


async def insert_eval(metrics: dict[str, Any]) -> None:
    """Insert a single turn's metrics into the database."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO eval_logs (
                turn_id, prompt_tokens, completion_tokens, total_tokens,
                tool_calls_total, tool_calls_success, tool_calls_failed,
                tool_success_rate, latency_seconds, context_density
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metrics["turn_id"],
                metrics["prompt_tokens"],
                metrics["completion_tokens"],
                metrics["total_tokens"],
                metrics["tool_calls_total"],
                metrics["tool_calls_success"],
                metrics["tool_calls_failed"],
                metrics["tool_success_rate"],
                metrics["latency_seconds"],
                metrics["context_density"],
            ),
        )
        await db.commit()


async def get_all_evals(limit: int = 100) -> list[dict[str, Any]]:
    """Retrieve the most recent eval logs."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM eval_logs ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_eval_summary() -> dict[str, Any]:
    """Return aggregate statistics across all logged turns."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT
                COUNT(*)            AS total_turns,
                AVG(latency_seconds) AS avg_latency,
                AVG(tool_success_rate) AS avg_tsr,
                SUM(total_tokens)   AS total_tokens_used,
                AVG(context_density) AS avg_context_density
            FROM eval_logs
            """
        )
        row = await cursor.fetchone()
        if row is None:
            return {}
        return {
            "total_turns": row[0],
            "avg_latency": round(row[1] or 0, 4),
            "avg_tsr": round(row[2] or 0, 4),
            "total_tokens_used": row[3] or 0,
            "avg_context_density": round(row[4] or 0, 4),
        }
