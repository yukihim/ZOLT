# ⚡ ZOLT — Zero Overhead LLM Transport

**ZOLT** is an end-to-end Agentic AI platform designed to automate IT operations, codebase triaging, and documentation retrieval. It features a completely custom-built Model Context Protocol (MCP) host SDK, built from scratch in Python, to manage asynchronous JSON-RPC 2.0 tool routing.

[![CI/CD](https://github.com/yukihim/ZOLT/actions/workflows/cicd.yml/badge.svg)](https://github.com/yukihim/ZOLT/actions)

---

## 🚀 Key Features

- **Custom MCP SDK** — A proprietary Python implementation of the MCP standard, handling pure JSON-RPC 2.0 connections over stdio & SSE transports.
- **Agentic Tooling** — Integrates with GitHub (code/issue triaging) and Google Drive (runbook retrieval) via MCP servers.
- **DeepSeek-Powered Agent** — Tool-use reasoning loop backed by the DeepSeek API for unlimited inference.
- **Built-in Evaluation Engine** — Custom telemetry tracking LLM latency, token efficiency, tool-call accuracy, and context density — logged to terminal in real-time.
- **Full Observability** — Integrated Prometheus + Grafana stack for real-time server health monitoring.
- **Cloud-Native Architecture** — Containerized microservices orchestrated with Kubernetes (K3s) on Oracle Cloud Free Tier.

## 🏗️ System Architecture

```
User → React Dashboard → FastAPI Backend → DeepSeek API
                                ↓
                        Custom MCP SDK (JSON-RPC 2.0)
                       ↙              ↘
              GitHub MCP          Google Drive MCP
              (stdio)                (SSE)
```

| Layer           | Technology                                         |
| --------------- | -------------------------------------------------- |
| **Frontend**    | React 18, Bootstrap 5, Chart.js                   |
| **Backend**     | FastAPI, Uvicorn, SQLite (aiosqlite)               |
| **AI / Router** | Custom Python MCP SDK, DeepSeek API                |
| **Infra**       | Docker, K3s (Kubernetes), GitHub Actions CI/CD     |
| **Monitoring**  | Prometheus, Grafana                                |
| **Hosting**     | Oracle Cloud Always Free Tier (ARM Ampere A1)      |

## 📁 Project Structure

```
ZOLT/
├── .github/workflows/cicd.yml          # GitHub Actions pipeline
├── custom_mcp_sdk/                     # Custom MCP Host SDK
│   ├── __init__.py                     # Public API surface
│   ├── host.py                         # JSON-RPC 2.0 state machine
│   ├── exceptions.py                   # Error hierarchy
│   └── transport/                      # Stdio & SSE transports
│       ├── base.py
│       ├── stdio.py
│       └── sse.py
├── backend/                            # FastAPI application
│   ├── app/
│   │   ├── main.py                     # API gateway & endpoints
│   │   ├── agent.py                    # DeepSeek tool-use loop
│   │   ├── evals.py                    # Evaluation metrics engine
│   │   └── database.py                 # SQLite persistence
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                           # React dashboard
│   ├── src/
│   │   ├── App.js / App.css
│   │   └── components/
│   │       ├── ChatPanel.js
│   │       ├── MetricsChart.js
│   │       └── ServerStatus.js
│   ├── Dockerfile
│   └── package.json
├── k8s/                                # Kubernetes manifests
│   ├── backend-deployment.yaml
│   ├── frontend-deployment.yaml
│   ├── prometheus-config.yaml
│   └── ingress.yaml
├── docker-compose.yml                  # Local dev orchestration
└── .env.example                        # API key template
```

## ⚙️ Getting Started (Local Development)

### Prerequisites

- Docker & Docker Compose
- Python 3.11+
- Node.js 20+
- DeepSeek API Key
- GitHub Personal Access Token (optional)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yukihim/ZOLT.git
   cd ZOLT
   ```

2. **Set up environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env and add your API keys
   ```

3. **Start everything:**
   ```bash
   docker-compose up --build
   ```

4. **Access the services:**

   | Service     | URL                        |
   | ----------- | -------------------------- |
   | Frontend    | http://localhost:3000       |
   | Backend API | http://localhost:8000       |
   | Prometheus  | http://localhost:9090       |
   | Grafana     | http://localhost:3001       |

## 📊 Evaluation Metrics

The platform tracks custom metrics per agent turn (logged to terminal):

| Metric               | Description                                                               |
| -------------------- | ------------------------------------------------------------------------- |
| **T_lat**            | Time from prompt submission to final tool-augmented response              |
| **TSR**              | Tool Success Rate — % of JSON-RPC calls returning success vs error        |
| **Context Density**  | Ratio of relevant extracted tool data to total prompt tokens              |
| **Token Usage**      | Prompt, completion, and total token counts per turn                       |

Aggregate stats available at `GET /api/evals/summary`. Full logs at `GET /api/evals`.

## ☁️ Free Cloud Deployment (Oracle Cloud + K3s)

The entire platform runs for **$0/month** on Oracle Cloud Always Free Tier:

- **4 ARM cores**, **24 GB RAM**, **200 GB storage** — permanently free
- **K3s** lightweight Kubernetes — production-ready
- **Auto-deploy** via GitHub Actions on every push to `main`

👉 **[Full Deployment Guide →](docs/DEPLOYMENT.md)** — step-by-step from account creation to live HTTPS site.

## 🔄 CI/CD Pipeline

On every push to `main`, GitHub Actions automatically:

1. **Lint** — `ruff` for Python, build check for React
2. **Test** — `pytest` for the custom SDK
3. **Build** — Docker images for backend & frontend
4. **Push** — Tagged images to Docker Hub
5. **Deploy** — `kubectl apply` to remote K3s cluster

## 📜 License

MIT License — see [LICENSE](LICENSE) for details.
