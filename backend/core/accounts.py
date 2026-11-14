"""Email/password account endpoints for provisioned and self-enrolled users."""
import json
from django.conf import settings

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .studio import json_body


def normalize_email(value):
    email = str(value or "").strip().casefold()
    validate_email(email)
    return email


@require_POST
@json_body
def sign_in(request):
    try:
        email = normalize_email(request.payload.get("email"))
    except ValidationError:
        return JsonResponse({"error": "Enter a valid email address."}, status=400)
    from .security import login_allowed
    allowed, retry = login_allowed(email)
    if not allowed:
        response = JsonResponse({"error": "Too many sign-in attempts. Please wait a few minutes and try again."}, status=429)
        response["Retry-After"] = str(retry)
        return response
    user = authenticate(request, username=email, password=request.payload.get("password", ""))
    if user is None or not user.is_active:
        return JsonResponse({"error": "Email or password is incorrect."}, status=400)
    login(request, user)
    return JsonResponse({"ok": True})


@require_POST
@json_body
@transaction.atomic
def register(request):
    if not getattr(settings, "ALLOW_SELF_REGISTRATION", True):
        return JsonResponse({"error": "Account registration is not open. Contact your course staff for access."}, status=403)
    try:
        email = normalize_email(request.payload.get("email"))
        password = str(request.payload.get("password", ""))
        first_name = str(request.payload.get("first_name", "")).strip()[:150]
        last_name = str(request.payload.get("last_name", "")).strip()[:150]
        validate_password(password)
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)
    users = get_user_model().objects.select_for_update()
    user = users.filter(username__iexact=email).first() or users.filter(email__iexact=email).first()
    if user is not None and user.has_usable_password():
        return JsonResponse({"error": "An account with this email already exists."}, status=409)
    if user is None:
        user = get_user_model()(username=email, email=email)
    user.username = email
    user.email = email
    user.first_name = first_name
    user.last_name = last_name
    user.set_password(password)
    user.save()
    login(request, user)
    return JsonResponse({"ok": True})


@require_POST
def sign_out(request):
    logout(request)
    return JsonResponse({"ok": True})
