from django import template
from pages.evacuation_data import EVACUATION_CENTERS

register = template.Library()


@register.simple_tag
def evacuation_centers():
    return EVACUATION_CENTERS