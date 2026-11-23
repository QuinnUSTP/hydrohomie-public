from datetime import timedelta

from django import template
from django.conf import settings
from django.utils import timezone

from pages.models import HubHeartbeat, PublicAlert, PublicAnnouncement, ZoneStatus

register = template.Library()
LABELS = dict(ZoneStatus.STATES)


def _limit():
    return timedelta(minutes=getattr(settings, "LIVE_STALE_MINUTES", 10))


@register.simple_tag
def hub_status():
    beat = HubHeartbeat.objects.first()
    if beat is None:
        return {"code": "never", "last_seen": None}
    fresh = timezone.now() - beat.last_seen <= _limit()
    return {"code": "live" if fresh else "delayed", "last_seen": beat.last_seen}


@register.simple_tag
def zone_cards():
    hub_is_live = hub_status()["code"] == "live"
    cutoff = timezone.now() - _limit()
    cards = []
    for zone in ZoneStatus.objects.all():
        stale = not hub_is_live or zone.measured_at < cutoff
        if zone.state == "offline" and hub_is_live:
            state = "offline"
        else:
            state = "unknown" if stale else zone.state
        cards.append({
            "zone": zone,
            "state": state,
            "label": LABELS[state],
            "show_level": state in ("normal", "watch", "alert") and zone.level_cm is not None,
        })
    return cards


@register.simple_tag
def alert_lists():
    return {
        "active": list(PublicAlert.objects.filter(ended_at__isnull=True)),
        "recent": list(PublicAlert.objects.filter(ended_at__isnull=False)[:20]),
    }


@register.simple_tag
def announcements():
    return list(PublicAnnouncement.objects.filter(is_active=True)[:20])