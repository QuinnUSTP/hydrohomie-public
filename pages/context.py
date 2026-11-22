from django.conf import settings
from django.conf.urls import static
from .content import PRIMARY_NAV, FOOTER_NAV
from urllib.parse import quote
from django.templatetags.static import static
from django.conf import settings

from .content import PRIMARY_NAV, FOOTER_NAV

def site(request):
    return {
        "SITE_URL": settings.SITE_URL,
        "SITE_NAME": settings.SITE_NAME,
        "CONTACT_EMAIL": settings.CONTACT_EMAIL,
        "PRIMARY_NAV": PRIMARY_NAV,
        "FOOTER_NAV": FOOTER_NAV,
        "CANONICAL_URL": settings.SITE_URL + quote(request.path),
        "OG_IMAGE_URL": settings.SITE_URL + static("img/og-default.png"),
        "OG_IMAGE_ALT": f"{settings.SITE_NAME} logo with the words: Flood monitoring and alerts for Barangay Kauswagan",
        "GOOGLE_SITE_VERIFICATION": settings.GOOGLE_SITE_VERIFICATION,
    }