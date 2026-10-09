ARG PYTHON_IMAGE=python:3.13-slim-bookworm
FROM ${PYTHON_IMAGE}
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY bot/pyproject.toml ./
COPY bot/papilio_telegram ./papilio_telegram
RUN python -m pip install .
USER 10001:10001
CMD ["python", "-m", "papilio_telegram.app"]
