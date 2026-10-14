from datetime import date, datetime

from django import template
from django.utils import timezone
from django.utils.safestring import mark_safe

from talent.dates import jalali_datetime, jalali_label, persian_digits
from talent.html_text import sanitize_html

register = template.Library()


def _local_moment(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            return timezone.localtime(value)
        return value
    if isinstance(value, date):
        return value
    return None


@register.simple_tag(takes_context=True)
def absolute_url(context, path):
    return context["request"].build_absolute_uri(path)


@register.filter
def persian(value):
    return persian_digits(value)


@register.filter
def jalali(value):
    moment = _local_moment(value)
    if moment is None:
        return ""
    if isinstance(moment, datetime):
        return jalali_label(moment.date())
    return jalali_label(moment)


@register.filter
def jalali_dt(value):
    moment = _local_moment(value)
    if moment is None:
        return ""
    return jalali_datetime(moment)


@register.filter
def rich(value):
    return mark_safe(sanitize_html(value))
