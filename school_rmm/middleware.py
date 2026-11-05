from django.conf import settings
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django_otp.plugins.otp_totp.models import TOTPDevice


class RequireMFAMiddleware:
    """Enforce the library's verified session on every application/admin view."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not settings.REQUIRE_MFA:
            return None
        match = request.resolver_match
        if match.namespace == "two_factor":
            if match.url_name == "disable":
                return HttpResponseForbidden("Drugi składnik jest wymagany. Zmiana urządzenia wymaga administratora.")
            return None
        if not match.namespace and match.url_name in ("health", "login", "logout"):
            return None
        if not request.user.is_authenticated:
            return redirect("two_factor:login")
        if not request.user.is_verified():
            if TOTPDevice.objects.filter(user=request.user, confirmed=True).exists():
                return redirect("two_factor:login")
            return redirect("two_factor:setup")
        return None
