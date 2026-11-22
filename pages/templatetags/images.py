import json
from functools import lru_cache
from pathlib import Path

from django import template
from django.conf import settings
from django.templatetags.static import static
from django.utils.html import format_html, format_html_join
from django.utils.html import escape, format_html, format_html_join

register = template.Library()


@lru_cache(maxsize=8)
def _read(path, mtime):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _manifest():
    path = Path(settings.OPTIMIZED_IMAGE_DIR) / "manifest.json"
    if not path.exists():
        raise ValueError(f"Image manifest not found: {path}. Run: python manage.py optimize_images")
    return _read(str(path), path.stat().st_mtime)


@register.simple_tag
def responsive_image(name, alt, sizes, eager=False, css_class=""):
    entry = _manifest().get(name)
    if entry is None:
        raise ValueError(f"Unknown image '{name}'. Run: python manage.py optimize_images")
    variants = entry["variants"]
    default = variants[len(variants) // 2]
    srcset = ", ".join(f"{static(v['file'])} {v['width']}w" for v in variants)
    extras = [("fetchpriority", "high")] if eager else [("loading", "lazy"), ("decoding", "async")]
    class_attr = format_html(' class="{}"', escape(css_class)) if css_class else ""
    return format_html(
        '<img src="{}" srcset="{}" sizes="{}" width="{}" height="{}" alt="{}"{}{}>',
        static(default["file"]), srcset, escape(sizes), default["width"], default["height"],
        escape(alt), class_attr, format_html_join("", ' {}="{}"', extras),
    )