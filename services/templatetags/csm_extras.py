from decimal import Decimal

from django import template
from django.utils.html import format_html

register = template.Library()

BADGES = {
    'Pending': 'bg-amber-100 text-amber-800', 'In Progress': 'bg-sky-100 text-sky-800',
    'Completed': 'bg-emerald-100 text-emerald-800', 'Cancelled': 'bg-rose-100 text-rose-800',
    'Paid': 'bg-emerald-100 text-emerald-800', 'Partial': 'bg-amber-100 text-amber-800',
    'Unpaid': 'bg-rose-100 text-rose-800', 'In stock': 'bg-emerald-100 text-emerald-800',
    'Low stock': 'bg-amber-100 text-amber-800', 'Out of stock': 'bg-rose-100 text-rose-800',
    'Confirmed': 'bg-emerald-100 text-emerald-800', 'Rejected': 'bg-rose-100 text-rose-800',
    'Verifying': 'bg-sky-100 text-sky-800',
    'Active': 'bg-emerald-100 text-emerald-800', 'Inactive': 'bg-slate-200 text-slate-600',
}


@register.filter
def cell(obj, path):
    """Resolve 'customer.name'-style paths (calling methods/properties as needed)."""
    for part in path.split('.'):
        if obj is None:
            return ''
        obj = getattr(obj, part, '')
        if callable(obj):
            obj = obj()
    return obj


@register.filter
def pretty(value):
    """Booleans -> Active/Inactive, badge-able strings -> coloured pill, numbers untouched."""
    if value is None or value == '':
        return '-'
    if isinstance(value, bool):
        value = 'Active' if value else 'Inactive'
    if isinstance(value, str) and value in BADGES:
        return format_html('<span class="inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold {}">{}</span>',
                           BADGES[value], value)
    if isinstance(value, Decimal):
        return f"Rs {value:,.0f}"
    return value


@register.filter
def inr(value):
    try:
        return f"Rs {float(value):,.0f}"
    except (TypeError, ValueError):
        return value


@register.filter
def stars(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return ''
    return '★' * n + '☆' * (5 - n)


@register.filter
def pct(value, total):
    try:
        return round(float(value) * 100 / float(total))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0
