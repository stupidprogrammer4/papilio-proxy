"""Native Django/Celery settings shared by all isolated deployment profiles."""

import os

from kombu import Exchange, Queue

from papilio_panel import __version__

from .environment import (
    boolean,
    deployment_identity,
    positive_integer,
    postgres_database,
    required,
    transport_scheme,
)
from .queues import QueueKind

PAPILIO_ENV, PAPILIO_INSTANCE = deployment_identity()
PAPILIO_TRANSPORT_SCHEME = transport_scheme(PAPILIO_ENV)
PAPILIO_NAMESPACE = f"papilio.{PAPILIO_INSTANCE}.{PAPILIO_ENV}"
PAPILIO_BRAND_TITLE = os.environ.get("PAPILIO_BRAND_TITLE", "Papilio")
SECRET_KEY = required("PAPILIO_SECRET_KEY")
if len(SECRET_KEY) < 50:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("PAPILIO_SECRET_KEY must contain at least 50 characters.")
DEBUG = PAPILIO_ENV == "dev"
ALLOWED_HOSTS = required("PAPILIO_ALLOWED_HOSTS").split(",")
ROOT_URLCONF = "papilio_panel.config.urls"
WSGI_APPLICATION = "papilio_panel.config.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = os.environ.get("PAPILIO_TIMEZONE", "UTC")
LANGUAGE_CODE = "en-us"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
    "drf_spectacular",
    "django_celery_beat",
    "papilio_panel.modules.identity",
    "papilio_panel.modules.jobs",
    "papilio_panel.modules.nodes",
    "papilio_panel.modules.bots",
    "papilio_panel.modules.cores",
    "papilio_panel.modules.services",
    "papilio_panel.modules.customers",
    "papilio_panel.modules.wallets",
    "papilio_panel.modules.catalog",
    "papilio_panel.modules.orders",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
DATABASES = {"default": postgres_database()}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": required("PAPILIO_CACHE_URL"),
        "KEY_PREFIX": PAPILIO_NAMESPACE,
        "OPTIONS": {"socket_connect_timeout": 3, "socket_timeout": 3},
    }
}
PASSWORD_MIN_LENGTH = positive_integer("PAPILIO_PASSWORD_MIN_LENGTH", 12)
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": PASSWORD_MIN_LENGTH},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PAPILIO_SETUP_TOKEN_TTL_SECONDS = positive_integer("PAPILIO_SETUP_TOKEN_TTL_SECONDS", 300)
SESSION_COOKIE_NAME = f"papilio_{PAPILIO_INSTANCE}_{PAPILIO_ENV}_session"
CSRF_COOKIE_NAME = f"papilio_{PAPILIO_INSTANCE}_{PAPILIO_ENV}_csrf"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = boolean(
    "PAPILIO_SESSION_COOKIE_SECURE", PAPILIO_TRANSPORT_SCHEME == "https"
)
CSRF_COOKIE_SECURE = boolean("PAPILIO_CSRF_COOKIE_SECURE", PAPILIO_TRANSPORT_SCHEME == "https")
CSRF_COOKIE_HTTPONLY = True
CSRF_HEADER_NAME = "HTTP_X_CSRF_TOKEN"
SESSION_COOKIE_AGE = positive_integer("PAPILIO_SESSION_SECONDS", 86400)
CSRF_TRUSTED_ORIGINS = list(filter(None, os.environ.get("PAPILIO_TRUSTED_ORIGINS", "").split(",")))
SECURE_SSL_REDIRECT = boolean("PAPILIO_SECURE_SSL_REDIRECT", PAPILIO_TRANSPORT_SCHEME == "https")
SECURE_REDIRECT_EXEMPT = [r"^health/live$"]
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
if boolean("PAPILIO_BEHIND_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "papilio_panel.modules.identity.routers.session_authentication.AdminSessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAdminUser"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.environ.get("PAPILIO_AUTH_RATE", "30/min"),
    },
    "EXCEPTION_HANDLER": "papilio_panel.shared.http_errors.handle_exception",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Papilio API",
    "VERSION": __version__,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAdminUser"],
}

CELERY_BROKER_URL = required("CELERY_BROKER_URL")
CELERY_TASK_DEFAULT_QUEUE = f"{PAPILIO_NAMESPACE}.io"
PAPILIO_QUEUE_NAMES = {kind.value: f"{PAPILIO_NAMESPACE}.{kind.value}" for kind in QueueKind}
CELERY_TASK_QUEUES = tuple(
    Queue(name, exchange=Exchange(PAPILIO_NAMESPACE), routing_key=name)
    for name in PAPILIO_QUEUE_NAMES.values()
)
CELERY_TASK_DEFAULT_EXCHANGE = PAPILIO_NAMESPACE
CELERY_TASK_DEFAULT_ROUTING_KEY = CELERY_TASK_DEFAULT_QUEUE
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_PUBLISH_RETRY = True
CELERY_TASK_PUBLISH_RETRY_POLICY = {
    "max_retries": positive_integer("PAPILIO_PUBLISH_MAX_RETRIES", 3),
    "interval_start": 0,
    "interval_step": positive_integer("PAPILIO_PUBLISH_RETRY_SECONDS", 1),
    "interval_max": positive_integer("PAPILIO_PUBLISH_MAX_RETRY_SECONDS", 3),
}
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_WORKER_CANCEL_LONG_RUNNING_TASKS_ON_CONNECTION_LOSS = True
CELERY_CONTROL_QUEUE_DURABLE = True
CELERY_EVENT_QUEUE_EXCLUSIVE = True
CELERY_CONTROL_EXCHANGE = f"{PAPILIO_NAMESPACE}.control"
CELERY_EVENT_EXCHANGE = f"{PAPILIO_NAMESPACE}.events"
CELERY_EVENT_QUEUE_PREFIX = f"{PAPILIO_NAMESPACE}.events"
CELERY_BROKER_TRANSPORT_OPTIONS = {"confirm_publish": True}
CELERY_BROKER_CONNECTION_TIMEOUT = positive_integer("PAPILIO_BROKER_CONNECT_TIMEOUT", 5)
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULER = "papilio_panel.modules.jobs.infra.beat:EditableDatabaseScheduler"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_SOFT_TIME_LIMIT = positive_integer("PAPILIO_TASK_SOFT_TIMEOUT", 60)
CELERY_TASK_TIME_LIMIT = positive_integer("PAPILIO_TASK_HARD_TIMEOUT", 90)
PAPILIO_OPERATION_LEASE_SECONDS = CELERY_TASK_TIME_LIMIT + 30
PAPILIO_OUTBOX_BATCH_SIZE = positive_integer("PAPILIO_OUTBOX_BATCH_SIZE", 100)
PAPILIO_OUTBOX_REDELIVERY_SECONDS = positive_integer("PAPILIO_OUTBOX_REDELIVERY_SECONDS", 120)
PAPILIO_HEARTBEAT_SECONDS = positive_integer("PAPILIO_HEARTBEAT_SECONDS", 15)
PAPILIO_HEARTBEAT_MAX_AGE_SECONDS = positive_integer("PAPILIO_HEARTBEAT_MAX_AGE_SECONDS", 90)
PAPILIO_OUTBOX_INTERVAL_SECONDS = positive_integer("PAPILIO_OUTBOX_INTERVAL_SECONDS", 1)
PAPILIO_CPU_PROBE_ITERATIONS = positive_integer("PAPILIO_CPU_PROBE_ITERATIONS", 100000)
PAPILIO_IO_CONCURRENCY = positive_integer("PAPILIO_IO_CONCURRENCY", 2)
PAPILIO_CPU_CONCURRENCY = positive_integer("PAPILIO_CPU_CONCURRENCY", 1)
PAPILIO_OPERATION_MAX_ATTEMPTS = positive_integer("PAPILIO_OPERATION_MAX_ATTEMPTS", 5)
PAPILIO_MAX_PAGE_SIZE = positive_integer("PAPILIO_MAX_PAGE_SIZE", 200)
