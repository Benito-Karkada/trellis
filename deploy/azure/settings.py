"""Azure deployment settings; local Compose settings are unchanged."""
import os
from django.core.exceptions import ImproperlyConfigured
from .settings import *  # noqa: F403


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"Required Azure setting is missing: {name}")
    return value


SECRET_KEY = required("SECRET_KEY")
if SECRET_KEY == "local-development-only":
    raise ImproperlyConfigured("Set a dedicated Azure SECRET_KEY")
DEBUG = False
ALLOW_LOCAL_LOGIN = False
ALLOW_SELF_REGISTRATION = False
# Enable only after the isolated Azure execution controller is connected.
EXECUTION_ENABLED = os.environ.get("EXECUTION_ENABLED", "0") == "1"
ALLOWED_HOSTS = [host.strip() for host in required("ALLOWED_HOSTS").split(",") if host.strip()]
if "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Azure ALLOWED_HOSTS must list explicit hostnames")
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 86400
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 8 * 60 * 60
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_REFERRER_POLICY = "same-origin"
ROOT_URLCONF = "config.azure_urls"
MIDDLEWARE = [MIDDLEWARE[0], "whitenoise.middleware.WhiteNoiseMiddleware", *MIDDLEWARE[1:]]
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
WHITENOISE_ROOT = BASE_DIR / "frontend-dist"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": os.environ.get("POSTGRES_DB", "cs1301"),
    "HOST": required("POSTGRES_HOST"),
    "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    "USER": required("POSTGRES_USER"),
    "PASSWORD": required("POSTGRES_PASSWORD"),
    "CONN_MAX_AGE": 60,
    "CONN_HEALTH_CHECKS": True,
    "OPTIONS": {"sslmode": "verify-full", "sslrootcert": "/etc/ssl/certs/ca-certificates.crt"},
}}
# Private Blob storage. Prefer managed identity for production; a container-scoped
# expiring SAS permits a POC when the team cannot create Azure role assignments.
if os.environ.get("AZURE_STORAGE_ACCOUNT"):
    storage_options = {
        "account_name": os.environ["AZURE_STORAGE_ACCOUNT"],
        "azure_container": os.environ.get("AZURE_STORAGE_CONTAINER", "private-media"),
        "overwrite_files": False,
    }
    if os.environ.get("AZURE_STORAGE_SAS_TOKEN"):
        storage_options["sas_token"] = os.environ["AZURE_STORAGE_SAS_TOKEN"].lstrip("?")
    else:
        from azure.identity import DefaultAzureCredential
        storage_options["token_credential"] = DefaultAzureCredential(
            managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID") or None
        )
    STORAGES = {
        "default": {"BACKEND": "config.azure_storage.PrivateAzureStorage", "OPTIONS": storage_options},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
else:
    # Never silently persist student work in an ephemeral container filesystem.
    STORAGES = {
        "default": {"BACKEND": "config.azure_settings.UnconfiguredMediaStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

from django.core.files.storage import Storage
class UnconfiguredMediaStorage(Storage):
    def _open(self, name, mode="rb"):
        raise ImproperlyConfigured("Configure AZURE_STORAGE_ACCOUNT before accessing course files")
    def _save(self, name, content):
        raise ImproperlyConfigured("Configure AZURE_STORAGE_ACCOUNT before saving course files")
    def exists(self, name):
        raise ImproperlyConfigured("Configure AZURE_STORAGE_ACCOUNT before saving course files")
