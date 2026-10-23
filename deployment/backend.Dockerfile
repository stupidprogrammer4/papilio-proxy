FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src DJANGO_SETTINGS_MODULE=papilio_panel.config.settings
WORKDIR /app
COPY panel/backend/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock \
    && useradd --uid 10001 --create-home papilio
COPY --chown=10001:10001 panel/backend/src ./src
COPY --chown=10001:10001 panel/backend/manage.py ./manage.py
USER 10001:10001
EXPOSE 8000
CMD ["gunicorn", "--config=python:papilio_panel.config.gunicorn", "papilio_panel.config.wsgi:application", "--bind=0.0.0.0:8000", "--access-logfile=-", "--error-logfile=-"]
