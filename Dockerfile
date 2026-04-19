FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir --upgrade pip && \
    if [ -f /app/app_bundle.zip ]; then \
        python -c "import zipfile; zipfile.ZipFile('/app/app_bundle.zip').extractall('/app')"; \
    fi && \
    if ls /app/*.whl >/dev/null 2>&1; then \
        pip install --no-cache-dir /app/*.whl; \
    else \
        test -f /app/requirements.txt || (echo "requirements.txt missing and no wheel provided" >&2; exit 1); \
        test -f /app/pyproject.toml || (echo "pyproject.toml missing and no wheel provided" >&2; exit 1); \
        test -d /app/src || (echo "src directory missing and no wheel provided" >&2; exit 1); \
        pip install --no-cache-dir -r requirements.txt && \
        pip install --no-cache-dir -e .; \
    fi && \
    python -c "import tw_stock_ai; import tw_stock_ai.main; import tw_stock_ai.adapters; import tw_stock_ai.worker"

EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn tw_stock_ai.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
