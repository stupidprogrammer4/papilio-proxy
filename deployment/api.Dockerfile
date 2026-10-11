ARG PYTHON_IMAGE=python:3.13-slim-bookworm
FROM ${PYTHON_IMAGE}
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 USER=papilio
WORKDIR /app
COPY panel/backend/pyproject.toml ./
COPY panel/backend/src ./src
RUN python -m pip install .
COPY panel/backend/migrations ./migrations
COPY panel/backend/alembic.ini ./alembic.ini
COPY panel/backend/scripts ./scripts
COPY panel/backend/config.yml.sample /opt/deployment/config.yml.sample
COPY bot/.env.example /opt/deployment/bot.env.example
COPY deployment/configure.py deployment/bootstrap.py deployment/check_gateway.py /opt/deployment/
RUN chmod -R a+rX /app/src /app/migrations /app/scripts /opt/deployment \
    && chmod a+r /app/alembic.ini /app/pyproject.toml \
    && mkdir -p media tmp && chown -R 10001:10001 /app
USER 10001:10001
CMD ["python", "-m", "uvicorn", "src.apps.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
