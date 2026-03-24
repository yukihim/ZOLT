# ── Stage 1: Build Frontend ───────────────────────────────────────────
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# Set REACT_APP_API_URL to empty so it uses relative paths by default
ENV REACT_APP_API_URL=""
RUN npm run build

# ── Stage 2: Build Backend ────────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (needed for npx in the MCP host)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy backend requirements and install
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy the backend code
COPY backend/ ./backend/

# Copy custom_mcp_sdk (needed by the backend)
COPY custom_mcp_sdk/ ./custom_mcp_sdk/

# Copy the built frontend from Stage 1 into the backend's static directory
# main.py is configured to serve from 'backend/static'
COPY --from=frontend-builder /app/frontend/build ./backend/static

# Expose the port FastAPI will run on
EXPOSE 8080

# Run the backend
# We use 'python -m backend.app.main' or similar, but let's check the structure
# The project root is /app, so we need to set PYTHONPATH
ENV PYTHONPATH=/app
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8080"]

