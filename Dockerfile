FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt requirements-dev.txt pyproject.toml README.md /app/
COPY src /app/src
COPY docs /app/docs
COPY data /app/data
COPY scripts /app/scripts

RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn tw_stock_ai.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
