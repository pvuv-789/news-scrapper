FROM python:3.11-slim

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy dependency files first for better layer caching
COPY pyproject.toml ./

# Install dependencies using uv
RUN uv sync --no-dev

# Install Playwright browsers
RUN uv run playwright install chromium --with-deps

# Copy application source
COPY . .

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
