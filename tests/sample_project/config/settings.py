from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "Not_a_secret_key"

DEBUG = True

ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "sample_project.sampleapp",
    "sample_project.socketiotestsuiteapp",
    "channels",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "sample_project.config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.csrf",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "sample_project.config.wsgi.application"
ASGI_APPLICATION = "sample_project.config.asgi.application"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "sampleapp/sampleapp.sqlite3",
        # Override Django's default behaviour of using an in-memory database
        # in tests for SQLite, since that avoids connection.close() working.
        "TEST": {"NAME": "test_db.sqlite3"},
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# SIO
SIO_ENGINEIO_PING_INTERVAL_MS = 300
SIO_ENGINEIO_PING_TIMEOUT_MS = 200
SIO_ENGINEIO_MAX_PAYLOAD_BYTES = 1_000_000

# Turn logging on to see server logs on why tests might be failing

import logging

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose_sio": {
            "format": "%(asctime)s [%(levelname)s] %(pathname)s:%(lineno)d %(funcName)s(): %(message)s",
        },
        "verbose_sio_tests": {
            "format": "SIO: [%(levelname)s] %(pathname)s:%(lineno)d %(funcName)s(): %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
        "console_sio": {
            "class": "logging.StreamHandler",
            "formatter": "verbose_sio",
        },
        "console_sio_tests": {
            "class": "logging.StreamHandler",
            "formatter": "verbose_sio_tests",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        # "django": {"level": "INFO", "handlers": ["console"], "propagate": False},
        # "channels": {"level": "DEBUG", "handlers": ["console"], "propagate": False},
        "sio": {
            "handlers": ["console_sio_tests"],
            "level": "DEBUG",
            "propagate": False,
        },
        # "sample_project": {
        #     "level": "DEBUG",
        #     "handlers": ["console"],
        #     "propagate": False,
        # },
    },
}
