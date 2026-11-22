import json

from django.conf import settings


def home_intro():
    return (
        f"{settings.SITE_NAME} tracks flood water levels in the barangay "
        "and sends alerts to residents."
    )


def dumps(data):
    text = json.dumps(data, ensure_ascii=False, indent=2)
    return (
        text.replace("<", "\\u003C")
        .replace(">", "\\u003E")
        .replace("&", "\\u0026")
    )


def home_graph():
    base = settings.SITE_URL
    org_id = f"{base}/#organization"
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": org_id,
                "name": settings.SITE_NAME,
                "url": f"{base}/",
                "description": home_intro(),
                "email": settings.CONTACT_EMAIL,
            },
            {
                "@type": "WebSite",
                "@id": f"{base}/#website",
                "name": settings.SITE_NAME,
                "url": f"{base}/",
                "publisher": {"@id": org_id},
            },
        ],
    }