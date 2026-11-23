import hmac
import json
import re

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import HubHeartbeat, PublicAlert, PublicAnnouncement, ZoneStatus

MAX_BODY_BYTES = 64_000
LIMITS = {"zones": 50, "alerts": 200, "announcements": 50}
ZONE_STATES = {code for code, _ in ZoneStatus.STATES}
SEVERITIES = {code for code, _ in PublicAlert.SEVERITIES}
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
IDENT = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
REPLACEABLE = ("zones", "announcements")


class Invalid(Exception):
    pass


def _reply(payload, status=200):
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "no-store"
    response["X-Robots-Tag"] = "noindex"
    return response


def _text(obj, key, max_len, required=True):
    value = obj.get(key)
    if value is None or value == "":
        if required:
            raise Invalid(f"{key} is required")
        return ""
    if not isinstance(value, str) or len(value) > max_len:
        raise Invalid(f"{key} must be text of at most {max_len} characters")
    return value.strip()


def _slug(obj, key):
    value = obj.get(key)
    if not isinstance(value, str) or len(value) > 40 or not SLUG.match(value):
        raise Invalid(f"{key} must be a lowercase slug such as zone-1")
    return value


def _ident(obj, key):
    value = obj.get(key)
    if not isinstance(value, str) or not IDENT.match(value):
        raise Invalid(f"{key} must be 1-64 letters, digits or . _ : -")
    return value


def _when(obj, key, required=True):
    value = obj.get(key)
    if value is None or value == "":
        if required:
            raise Invalid(f"{key} is required")
        return None
    try:
        parsed = parse_datetime(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or timezone.is_naive(parsed):
        raise Invalid(f"{key} must be an ISO 8601 time with a timezone")
    return parsed


def _level(obj):
    value = obj.get("level_cm")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1000:
        raise Invalid("level_cm must be a number from 0 to 1000")
    return round(float(value), 1)


def _apply(data):
    counts = {}
    replace = data.get("replace", [])
    if not isinstance(replace, list) or any(item not in REPLACEABLE for item in replace):
        raise Invalid("replace may only list zones and announcements")
    for name, limit in LIMITS.items():
        items = data.get(name, [])
        if not isinstance(items, list) or len(items) > limit:
            raise Invalid(f"{name} must be a list of at most {limit} items")
        if not all(isinstance(item, dict) for item in items):
            raise Invalid(f"every item in {name} must be an object")
        counts[name] = len(items)

    zone_keys, note_ids = [], []

    for z in data.get("zones", []):
        state = z.get("state")
        if state not in ZONE_STATES:
            raise Invalid("zone state is not recognised")
        key = _slug(z, "key")
        zone_keys.append(key)
        ZoneStatus.objects.update_or_create(
            key=key,
            defaults={"name": _text(z, "name", 80), "state": state,
                      "level_cm": _level(z), "measured_at": _when(z, "measured_at")},
        )

    for a in data.get("alerts", []):
        severity = a.get("severity")
        if severity not in SEVERITIES:
            raise Invalid("alert severity is not recognised")
        PublicAlert.objects.update_or_create(
            external_id=_ident(a, "id"),
            defaults={"zone_key": _slug(a, "zone_key"), "zone_name": _text(a, "zone_name", 80),
                      "severity": severity, "started_at": _when(a, "started_at"),
                      "ended_at": _when(a, "ended_at", required=False),
                      "summary": _text(a, "summary", 300, required=False)},
        )

    for n in data.get("announcements", []):
        active = n.get("active", True)
        if not isinstance(active, bool):
            raise Invalid("active must be true or false")
        ident = _ident(n, "id")
        note_ids.append(ident)
        PublicAnnouncement.objects.update_or_create(
            external_id=ident,
            defaults={"title": _text(n, "title", 120), "body": _text(n, "body", 2000),
                      "published_at": _when(n, "published_at"), "is_active": active},
        )

    if "zones" in replace:
        ZoneStatus.objects.exclude(key__in=zone_keys).delete()
    if "announcements" in replace:
        PublicAnnouncement.objects.exclude(external_id__in=note_ids).update(is_active=False)

    HubHeartbeat.objects.update_or_create(
        pk=1,
        defaults={"last_seen": timezone.now(), "hub_sent_at": _when(data, "sent_at", required=False)},
    )
    return counts


@csrf_exempt
@require_POST
def ingest(request):
    expected = getattr(settings, "INGEST_TOKEN", "")
    if not expected:
        return _reply({"ok": False, "error": "ingest is not enabled"}, 403)

    header = request.headers.get("Authorization", "")
    supplied = header[7:] if header.startswith("Bearer ") else ""
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        response = _reply({"ok": False, "error": "unauthorized"}, 401)
        response["WWW-Authenticate"] = "Bearer"
        return response

    try:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        declared = 0
    if declared > MAX_BODY_BYTES:
        return _reply({"ok": False, "error": "payload too large"}, 413)

    try:
        data = json.loads(request.body)
    except ValueError:
        return _reply({"ok": False, "error": "body must be JSON"}, 400)
    if not isinstance(data, dict) or data.get("schema") != 1:
        return _reply({"ok": False, "error": "body must be a JSON object with schema 1"}, 400)

    try:
        with transaction.atomic():
            counts = _apply(data)
    except Invalid as error:
        return _reply({"ok": False, "error": str(error)}, 400)
    return _reply({"ok": True, "received": counts})