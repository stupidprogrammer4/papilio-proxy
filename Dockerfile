FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./

COPY bot ./bot

COPY assets ./assets
RUN pip install --no-cache-dir .
RUN useradd --system --create-home --uid 10001 papilio \
    && chown -R papilio:papilio /app
USER papilio

CMD ["python", "-m", "bot.app"]
