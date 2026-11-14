"""Same-origin frontend; API and admin routes retain Django authentication."""
from django.http import FileResponse, Http404
from django.conf import settings
from django.urls import re_path
from .urls import urlpatterns as api_patterns


def frontend(request, path=""):
    if path.startswith(("api/", "admin/", "static/", "assets/")) or "." in path.rsplit("/", 1)[-1]:
        raise Http404
    return FileResponse((settings.BASE_DIR / "frontend-dist" / "index.html").open("rb"), content_type="text/html")


urlpatterns = [*api_patterns, re_path(r"^(?P<path>.*)$", frontend)]
