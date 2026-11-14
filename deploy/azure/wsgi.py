import os
from django.core.wsgi import get_wsgi_application
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.azure_settings")


class MaintenanceGate:
    """Pause student/staff writes while the isolated worker drains existing jobs."""
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "/")
        if os.environ.get("TRELLIS_MAINTENANCE_MODE") != "1" or path in {
            "/health/", "/healthz/", "/healthz", "/api/runner/claim/",
        } or path.startswith("/api/runner/complete/"):
            return self.app(environ, start_response)
        if path.startswith("/api/"):
            payload = b'{"error":"Trellis is undergoing maintenance. Your saved work is safe. Please try again shortly."}'
            content_type = "application/json"
        else:
            payload = ("<!doctype html><html><meta name='viewport' content='width=device-width,initial-scale=1'>"
                       "<title>Trellis | Maintenance</title><body style='margin:0;background:#f5f7f8;color:#243746;"
                       "font:18px/1.6 system-ui;display:grid;place-items:center;min-height:100vh'>"
                       "<main style='max-width:560px;padding:32px'><strong>Trellis</strong>"
                       "<h1>We'll be back shortly.</h1><p>Trellis is undergoing maintenance. "
                       "Your saved work is safe. Please try again shortly.</p></main></body></html>").encode()
            content_type = "text/html; charset=utf-8"
        start_response("503 Service Unavailable", [("Content-Type", content_type),
                       ("Content-Length", str(len(payload))), ("Retry-After", "120"),
                       ("Cache-Control", "no-store")])
        return [payload]


application = MaintenanceGate(get_wsgi_application())
