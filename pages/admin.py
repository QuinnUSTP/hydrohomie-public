from django.contrib import admin
from .models import HubHeartbeat, PublicAlert, PublicAnnouncement, ZoneStatus

admin.site.register(ZoneStatus, list_display=("name", "state", "level_cm", "measured_at", "received_at"))
admin.site.register(PublicAlert, list_display=("zone_name", "severity", "started_at", "ended_at"))
admin.site.register(PublicAnnouncement, list_display=("title", "published_at", "is_active"))
admin.site.register(HubHeartbeat, list_display=("last_seen", "hub_sent_at"))