"""Shared brute-force limits, consistent across application processes.

Counters use fixed hashed shards to bound storage even with random account names.
No forwarded client IP header is trusted. This does not replace an edge WAF.
"""
import hashlib
import hmac
import time
from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from .models import LoginThrottle


def login_allowed(email):
    now = int(time.time())
    window = now // 300
    digest = hmac.new(settings.SECRET_KEY.encode(), email.encode(), hashlib.sha256).digest()
    # At most 16,385 rows; collisions only share a short-lived limit.
    bucket = 'account:' + str(int.from_bytes(digest[:4], 'big') % 16384)
    with transaction.atomic():
        counts = []
        for key, limit in [('global', 2000), (bucket, 20)]:
            LoginThrottle.objects.get_or_create(bucket=key, defaults={'window': window})
            row = LoginThrottle.objects.select_for_update().get(bucket=key)
            if row.window != window:
                row.window, row.attempts = window, 0
            counts.append((row, limit))
        if any(row.attempts >= limit for row, limit in counts):
            return False, 300 - now % 300
        for row, _ in counts:
            row.attempts += 1
            row.save(update_fields=['window', 'attempts'])
    return True, 0


class PrivateResponseMiddleware:
    """Prevent browser/shared-cache reuse of private API and admin responses."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/admin/login/" and request.method == "POST":
            allowed, retry = login_allowed(str(request.POST.get("username", "")).strip().casefold())
            if not allowed:
                response = JsonResponse({"error": "Too many sign-in attempts. Please try again shortly."}, status=429)
                response["Retry-After"] = str(retry)
                response["Cache-Control"] = "no-store"
                return response
        response = self.get_response(request)
        if request.path.startswith(('/api/', '/admin/')):
            response['Cache-Control'] = response.get('Cache-Control', 'no-store, private')
        response['Referrer-Policy'] = 'same-origin'
        response['Permissions-Policy'] = 'geolocation=(), payment=(), usb=()'
        return response
