FROM python:3.13-slim

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml .
COPY README.md .
COPY src/ src/

# Install production dependencies
RUN uv pip install --system --no-cache ".[dev]" || uv pip install --system --no-cache .

# Create data directory for JSON stores and token files
RUN mkdir -p /app/data

# The token file path can be overridden via SCHWAB_TRADER_TOKEN_PATH env var.
# On Railway, set SCHWAB_TOKEN_JSON to the full token JSON contents — the
# startup script writes it to disk at /app/data/schwab_token.json.

EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn schwab_trader.server.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
