ARG PYTHON_IMAGE=python:3.13-slim-bookworm
FROM mysql:8.4.10 AS mysql-client

FROM ${PYTHON_IMAGE} AS api-runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 USER=papilio
WORKDIR /app
COPY --from=mysql-client /usr/bin/mysql /usr/bin/mysqldump /usr/bin/
COPY --from=mysql-client /lib64/libncurses.so.6.2 /lib/x86_64-linux-gnu/libncurses.so.6.2
RUN ln -s libncurses.so.6.2 /lib/x86_64-linux-gnu/libncurses.so.6
RUN mysql --no-defaults --help >/dev/null \
    && mysqldump --no-defaults --help | grep -q -- --set-gtid-purged

FROM api-runtime AS api
COPY panel/backend/pyproject.toml ./
COPY panel/backend/src ./src
RUN python -m pip install .
COPY panel/backend/migrations ./migrations
COPY panel/backend/alembic.ini ./alembic.ini
COPY panel/backend/scripts ./scripts
COPY panel/backend/recovery.yml.sample /opt/deployment/recovery.yml
COPY panel/backend/config.yml.sample /opt/deployment/config.yml.sample
COPY bot/.env.example /opt/deployment/bot.env.example
COPY deployment/configure.py deployment/bootstrap.py deployment/check_gateway.py /opt/deployment/
RUN chmod -R a+rX /app/src /app/migrations /app/scripts /opt/deployment \
    && chmod a+r /app/alembic.ini /app/pyproject.toml \
    && mkdir -p media tmp && chown -R 10001:10001 /app
USER 10001:10001
CMD ["python", "-m", "uvicorn", "src.apps.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
