# ── Multi-stage build for trade-system ─────────────────────────────────
# Docker image with the full uv workspace; entry point is the `trade-system` CLI.
#
# Build:
#   docker build -t trade-system .
#
# Run backtest:
#   docker run -v $(pwd)/configs/rsi_backtest.yaml:/etc/trade-system/config.yaml trade-system backtest /etc/trade-system/config.yaml
#
# Run live:
#   docker run -v $(pwd)/configs/live.yaml:/etc/trade-system/config.yaml trade-system live /etc/trade-system/config.yaml
#
# Run live (dry-run / paper trading):
#   docker run -v $(pwd)/configs/live.yaml:/etc/trade-system/config.yaml trade-system live /etc/trade-system/config.yaml --dry-run
#

# ── Stage 1: build ──────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy workspace definition first for layer caching
COPY pyproject.toml uv.lock justfile ./
COPY packages/ packages/

# Sync all workspace packages
RUN uv sync --all-packages --all-groups --frozen

# ── Stage 2: runtime ───────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Make sure venv is on PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV NAUTILUS_PATH="/app"

# Default config location (override with -v mount)
ENV TRADE_SYSTEM_CONFIG="/etc/trade-system/config.yaml"

ENTRYPOINT ["trade-system"]
CMD ["run", "/etc/trade-system/config.yaml"]
