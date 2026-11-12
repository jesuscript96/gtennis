"""Django settings for G Tenis backend.

Runs on SQLite out of the box (instant local start). Set DATABASE_URL to use
Postgres (local Docker or Render in the EU). Everything that touches personal /
health data lives here, so production MUST run in an EU region (GDPR Art. 9).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(key, default=False):
    return os.environ.get(key, str(default)).lower() in ("1", "true", "yes", "on")


SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-key-change-me")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "users",
    "academy",
    "scheduling",
    "engine",
    "integrations",
    "torneos",
    "evaluaciones",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    from urllib.parse import urlparse

    u = urlparse(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": u.path.lstrip("/"),
            "USER": u.username,
            "PASSWORD": u.password,
            "HOST": u.hostname,
            "PORT": u.port or 5432,
            # Cierra conexiones por petición y comprueba que estén vivas: evita
            # 500 por "server closed the connection" tras reposo/arranque en frío.
            "CONN_MAX_AGE": 0,
            "CONN_HEALTH_CHECKS": True,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "users.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "es-es"
TIME_ZONE = "Europe/Madrid"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 100,
}

CORS_ALLOWED_ORIGINS = [
    o for o in os.environ.get(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001",
    ).split(",") if o.strip()
]

# Permite cualquier despliegue del proyecto en Vercel (producción y previews).
CORS_ALLOWED_ORIGIN_REGEXES = [r"^https://gtennis-.*\.vercel\.app$"]

# En desarrollo, permite cualquier origen local (puertos de preview, etc.).
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True

CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TIMEZONE = TIME_ZONE

# Sésame HR integration (coach availability). Manual fallback used if unset.
SESAME_API_BASE = os.environ.get("SESAME_API_BASE", "")
SESAME_API_TOKEN = os.environ.get("SESAME_API_TOKEN", "")

# El front lee el nombre del PDF descargado de esta cabecera (viene de otro dominio).
CORS_EXPOSE_HEADERS = ["Content-Disposition"]

# Clave de la API de Claude (cuenta del club en console.anthropic.com). Sin ella
# las evaluaciones funcionan igual, pero los comentarios se guardan tal cual y
# las fortalezas y mejoras las escribe el entrenador.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# Modelo de Claude para las evaluaciones. Se cambia con un secreto en Fly, sin desplegar.
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")

# Google Drive (Workspace del club): cuenta de servicio con acceso de «Gestor de
# contenido» a la unidad compartida de informes. La clave va en JSON, tal cual o
# en base64. Sin ella los informes se descargan pero no se suben.
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
DRIVE_INFORMES_ID = os.environ.get("DRIVE_INFORMES_ID", "")
# Informes de Competición de tardes (02/11/2026): en «Mi unidad» de esta cuenta
# del club, en dos carpetas dentro de DRIVE_CT_RUTA (tramos separados por « › »).
# La cuenta de servicio entra en su nombre (delegación en todo el dominio).
DRIVE_CT_USUARIO = os.environ.get("DRIVE_CT_USUARIO", "")
DRIVE_CT_RUTA = os.environ.get(
    "DRIVE_CT_RUTA",
    "GTENNIS 2.0 - OPERACIONES › Gestion deportiva › Competicion tardes › 26/27 › Seguimiento y evaluaciones")
# Informes de Alto rendimiento (12/11/2026): igual, en su carpeta. Hasta
# «Alto rendimiento» ya existe; lo de después lo crea la app.
DRIVE_AR_RUTA = os.environ.get(
    "DRIVE_AR_RUTA",
    "GTENNIS 2.0 - OPERACIONES › Gestion deportiva › Alto rendimiento › 26/27 › Seguimiento y evaluaciones")

# --- Correo a las familias (10/11/2026, decisión 13) -------------------------
# Con EMAIL_HOST se envía por SMTP (p. ej. la cuenta gestion@ del club). Sin él,
# en desarrollo se escribe en la consola del servidor y en producción el envío
# dice que no está configurado.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "gestion@gtennis.com")
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
elif DEBUG:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
