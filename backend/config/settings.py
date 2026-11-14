import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("SECRET_KEY", "local-development-only")
DEBUG = os.environ.get("DEBUG", "0") == "1"
ALLOW_LOCAL_LOGIN = os.environ.get("ALLOW_LOCAL_LOGIN", "0") == "1"
RUNNER_TOKEN = os.environ.get("RUNNER_TOKEN","")
FRONTEND_PORT = os.environ.get("TRELLIS_FRONTEND_PORT", "5173")
CSRF_TRUSTED_ORIGINS = [f"http://localhost:{FRONTEND_PORT}", f"http://127.0.0.1:{FRONTEND_PORT}"] if DEBUG else []
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "backend", "testserver"]
INSTALLED_APPS = ["django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles", "core"]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "django.middleware.gzip.GZipMiddleware", "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware", "core.security.PrivateResponseMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware"]
DATA_UPLOAD_MAX_MEMORY_SIZE = 2_500_000
FILE_UPLOAD_MAX_MEMORY_SIZE = 2_000_000
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True, "OPTIONS": {"context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]}}]
DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": "cs1301", "USER": "cs1301", "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "local-only"), "HOST": "postgres"}} if os.environ.get("USE_POSTGRES") == "1" else {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "dev.sqlite3"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
STATIC_URL = "static/"
MEDIA_ROOT = BASE_DIR / "private-media"  # Never served through a public media route.
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
