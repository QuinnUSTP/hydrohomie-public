from django import template

from pages.evacuation_data import EVACUATION_CENTERS
from pages.reports_data import REPORTS

register = template.Library()


@register.simple_tag
def evacuation_centers():
    return EVACUATION_CENTERS


@register.simple_tag
def flood_reports():
    return REPORTS