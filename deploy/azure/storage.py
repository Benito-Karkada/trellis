"""Keep Blob credentials and hidden course files behind authenticated API views."""
from django.core.exceptions import ImproperlyConfigured
from storages.backends.azure_storage import AzureStorage


class PrivateAzureStorage(AzureStorage):
    def url(self, name, *args, **kwargs):
        # AzureStorage.url() can expose the container's SAS. Serve files through
        # permission-checked FileResponse endpoints instead of handing out URLs.
        raise ImproperlyConfigured("Private files require an authenticated application endpoint")
