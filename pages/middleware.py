from django.conf import settings
from django.http import HttpResponsePermanentRedirect

from .content import PAGES, REDIRECTS


class RobotsHeaderMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if "X-Robots-Tag" not in response:
            private = request.path.startswith("/admin/") or request.path == "/health/"
            if private or not settings.ALLOW_INDEXING:
                response["X-Robots-Tag"] = "noindex"
        return response

class SecurityHeadersMiddleware:
    CSP = "; ".join([
        "default-src 'self'",
        "img-src 'self' data:",
        "style-src 'self'",
        "script-src 'self'",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])
    PERMISSIONS = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if "Permissions-Policy" not in response:
            response["Permissions-Policy"] = self.PERMISSIONS
        skip_csp = request.path.startswith("/admin/") or settings.DEBUG
        if not skip_csp and "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = self.CSP
        return response

KNOWN_PATHS = {"/", "/sitemap.xml", "/robots.txt", "/health/"} | {f"/{p['slug']}/" for p in PAGES}


class CanonicalURLMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        target = self.redirect_target(request)
        if target:
            return HttpResponsePermanentRedirect(target)
        return self.get_response(request)

    @staticmethod
    def clean_path(path):
        if path == "/admin":
            return "/admin/"
        if path.startswith(("/admin/", "/static/")):
            return path
        lowered = path.lower()
        last = lowered.rsplit("/", 1)[-1]
        slashed = lowered if lowered.endswith("/") or "." in last else lowered + "/"
        for candidate in (lowered, slashed):
            if candidate in REDIRECTS:
                return REDIRECTS[candidate]
        if slashed in KNOWN_PATHS:
            return slashed
        return path

    def redirect_target(self, request):
        if request.method not in ("GET", "HEAD") or request.path == "/health/":
            return None
        path = request.path
        new_path = self.clean_path(path)
        host_wrong = request.get_host().lower() in settings.REDIRECT_HOSTS
        scheme_wrong = settings.FORCE_HTTPS and not request.is_secure()
        if new_path == path and not host_wrong and not scheme_wrong:
            return None
        query = request.META.get("QUERY_STRING", "")
        suffix = f"?{query}" if query else ""
        if host_wrong or scheme_wrong:
            return f"{settings.SITE_URL}{new_path}{suffix}"
        return f"{new_path}{suffix}"