# ──────────────────────────────────────────────────────────
# ZOLT Backend — Dockerfile
# Build context must be the PROJECT ROOT (not backend/)
# so we can COPY custom_mcp_sdk alongside the backend code.
# ──────────────────────────────────────────────────────────

FROM python:3.11-slim

WORKDIR /app

# Install Node.js (needed for npx MCP servers)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy SDK (from project root context)
COPY custom_mcp_sdk /app/custom_mcp_sdk

# Copy backend code
COPY backend/app /app/backend/app

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
