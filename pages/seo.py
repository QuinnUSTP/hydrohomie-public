from xml.sax.saxutils import escape

from django.conf import settings
from django.http import HttpResponse
from django.urls import reverse

from .content import LASTMOD, PAGES


def sitemap_xml(request):
    entries = [(reverse("home"), None)]
    for page in PAGES:
        path = reverse("info", kwargs={"slug": page["slug"]})
        entries.append((path, LASTMOD.get(page["slug"])))

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>\n',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n',
    ]
    for path, modified in entries:
        parts.append("  <url>\n")
        parts.append(f"    <loc>{escape(settings.SITE_URL + path)}</loc>\n")
        if modified:
            parts.append(f"    <lastmod>{modified.isoformat()}</lastmod>\n")
        parts.append("  </url>\n")
    parts.append("</urlset>\n")

    return HttpResponse("".join(parts), content_type="application/xml; charset=utf-8")

def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        "",
        f"Sitemap: {settings.SITE_URL}/sitemap.xml",
        "",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")