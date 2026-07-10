FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app
ARG INSTALL_EMBEDDING_EXTRAS=false
RUN pip install --upgrade pip \
    && if [ "$INSTALL_EMBEDDING_EXTRAS" = "true" ]; then pip install ".[embeddings]"; else pip install .; fi

COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
RUN chmod +x scripts/start.sh

EXPOSE 8000

CMD ["sh", "scripts/start.sh"]
