# jobs/templatetags/__init__.py
# Bu dosyayı boş bırakın

# jobs/templatetags/form_tags.py
from django import template

register = template.Library()

@register.filter(name='add_class')
def add_class(field, css_class):
    """Form field'a CSS class ekler"""
    if hasattr(field, 'as_widget'):
        return field.as_widget(attrs={'class': css_class})
    return field

@register.filter(name='add_attrs')
def add_attrs(field, attrs):
    """Form field'a birden fazla attribute ekler"""
    if hasattr(field, 'as_widget'):
        attrs_dict = {}
        for attr in attrs.split(','):
            key, value = attr.split(':')
            attrs_dict[key.strip()] = value.strip()
        return field.as_widget(attrs=attrs_dict)
    return field