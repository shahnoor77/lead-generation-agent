# Use the Playwright image as the sole stage to avoid version mismatches
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# 1. Install Poetry directly in this image
ENV POETRY_VERSION=1.7.1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONPATH=/app

RUN pip install --no-cache-dir poetry==$POETRY_VERSION

# 2. Copy only dependency files first (to leverage Docker caching)
COPY pyproject.toml poetry.lock* ./

# 3. Install ALL dependencies directly into the system python
# Since POETRY_VIRTUALENVS_CREATE=false, it installs to system site-packages
RUN poetry install --no-interaction --no-ansi

# 4. Copy application code
COPY app ./app
COPY .env* ./

# 5. Handle user permissions
# The Playwright image already has 'pwuser' (UID 1000)
RUN chown -R pwuser:pwuser /app
USER pwuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

EXPOSE 8000

# Run migrations + start API
CMD ["sh", "-c", "python -c 'import asyncio; from app.storage.database import init_db; asyncio.run(init_db())' && uvicorn app.main:app --host 0.0.0.0 --port 8000"]