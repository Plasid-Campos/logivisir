from django import template

register = template.Library()


@register.filter
def clp(valor):
    """Monto en pesos chilenos con punto de miles: 149990 -> 149.990."""
    try:
        return f"{int(round(float(valor))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return valor
