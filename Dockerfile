FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

WORKDIR /app

COPY requirements.txt requirements-dev.txt pyproject.toml README.md /app/
COPY src /app/src
COPY docs /app/docs
COPY data /app/data
COPY scripts /app/scripts
COPY src/tw_stock_ai/adapters /app/src/tw_stock_ai/adapters
COPY src/tw_stock_ai/ai_adapters /app/src/tw_stock_ai/ai_adapters
COPY src/tw_stock_ai/notifiers /app/src/tw_stock_ai/notifiers
COPY src/tw_stock_ai/prompts /app/src/tw_stock_ai/prompts
COPY src/tw_stock_ai/routers /app/src/tw_stock_ai/routers
COPY src/tw_stock_ai/services /app/src/tw_stock_ai/services
COPY src/tw_stock_ai/static /app/src/tw_stock_ai/static
COPY src/tw_stock_ai/templates /app/src/tw_stock_ai/templates

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -e . && \
    python -c "import tw_stock_ai; import tw_stock_ai.main; import tw_stock_ai.adapters; import tw_stock_ai.worker"

EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn tw_stock_ai.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
