from django.db import models


class ZoneStatus(models.Model):
    STATES = [("normal", "Normal"), ("watch", "Watch"), ("alert", "Alert"),
              ("offline", "Offline"), ("unknown", "Unknown")]
    key = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    state = models.CharField(max_length=10, choices=STATES, default="unknown")
    level_cm = models.FloatField(null=True, blank=True)
    measured_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.state})"


class PublicAlert(models.Model):
    SEVERITIES = [("watch", "Watch"), ("alert", "Alert")]
    external_id = models.CharField(max_length=64, unique=True)
    zone_key = models.SlugField(max_length=40)
    zone_name = models.CharField(max_length=80)
    severity = models.CharField(max_length=10, choices=SEVERITIES)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    summary = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.zone_name} {self.severity} {self.started_at:%Y-%m-%d %H:%M}"


class PublicAnnouncement(models.Model):
    external_id = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=120)
    body = models.TextField(max_length=2000)
    published_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-published_at"]

    def __str__(self):
        return self.title


class HubHeartbeat(models.Model):
    last_seen = models.DateTimeField()
    hub_sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Last heard from the hub at {self.last_seen:%Y-%m-%d %H:%M:%S}"