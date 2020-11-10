from django import template

register = template.Library()


@register.filter(name='sum')
def sum_filter(value):
    if not value:
        return 0

    if isinstance(value, dict):
        return sum([sum_filter(v) if isinstance(v, dict) else v for v in value.values()])

    return sum(value)
