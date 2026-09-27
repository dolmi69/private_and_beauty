"""Русские формы слов для карточек врачей."""
from django import template

register = template.Library()


@register.filter
def ru_years(value):
    """1 год, 2 года, 5 лет; исключение для чисел от 11 до 14."""
    years = abs(int(value))
    if 11 <= years % 100 <= 14:
        return "лет"
    if years % 10 == 1:
        return "год"
    if years % 10 in (2, 3, 4):
        return "года"
    return "лет"
