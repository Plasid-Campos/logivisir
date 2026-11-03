from django import template
from django.conf import settings

from core import chat_ayuda

register = template.Library()


@register.inclusion_tag("core/_chat_ayuda.html")
def chat_ayuda_widget():
    return {
        "datos_chat": chat_ayuda.datos_widget(
            getattr(settings, "CONTACTO_EMAIL", ""), getattr(settings, "CONTACTO_WHATSAPP", ""),
        ),
    }
