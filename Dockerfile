FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml ./
COPY server.py http_main.py ./
COPY knowledge/ knowledge/
COPY schemas/ schemas/

RUN pip install --upgrade pip && pip install -e ".[http]"

EXPOSE 8200

CMD ["uvicorn", "http_main:app", "--host", "0.0.0.0", "--port", "8200"]
