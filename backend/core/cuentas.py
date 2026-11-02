"""
Correos de cuenta: bienvenida al crear un usuario, aviso cuando cambia la
contraseña y acuse de recibo de una solicitud de contratación.

Igual que notifications.py: nunca lanzan una excepción hacia arriba. Un
correo que falla no debe impedir crear el usuario ni cambiar la clave.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

FIRMA = "\n\nEquipo LogiVisir Solutions\nEste es un mensaje automático; no respondas a este correo."


def _enviar(asunto, cuerpo, destinatario):
    if not destinatario:
        return False
    try:
        send_mail(
            subject=asunto,
            message=cuerpo + FIRMA,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[destinatario],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception("Fallo al enviar el correo '%s' a %s", asunto, destinatario)
        return False


def _url(request, nombre):
    ruta = reverse(nombre)
    return request.build_absolute_uri(ruta) if request is not None else ruta


def validar_email_nuevo_usuario(email):
    """
    Devuelve un mensaje de error o None. El correo es obligatorio porque es
    la única forma de recuperar la cuenta si se olvida la contraseña, y debe
    ser único para que la recuperación llegue a una sola persona.
    """
    email = (email or "").strip()
    if not email:
        return "El correo es obligatorio: es la forma de recuperar la cuenta si se olvida la contraseña."
    try:
        validate_email(email)
    except ValidationError:
        return "El correo no tiene un formato válido."
    if User.objects.filter(email__iexact=email).exists():
        return f"Ya existe un usuario con el correo {email}."
    return None


def enviar_bienvenida(usuario, empresa, request=None):
    """
    Al crear un usuario de una empresa. No incluye la contraseña: la entrega
    quien creó la cuenta, y se debe cambiar en el primer ingreso.
    """
    nombre = usuario.first_name or usuario.username
    cuerpo = (
        f"Hola {nombre},\n\n"
        f"Se creó tu cuenta en LogiVisir para {empresa.nombre}.\n\n"
        f"Usuario: {usuario.username}\n"
        f"Ingresa en: {_url(request, 'login')}\n\n"
        "Tu contraseña inicial te la entrega la persona que creó tu cuenta. "
        "Al ingresar por primera vez te pediremos cambiarla.\n\n"
        "Si no la tienes o la olvidaste, puedes crear una nueva aquí:\n"
        f"{_url(request, 'password_reset')}"
    )
    return _enviar("Bienvenido/a a LogiVisir Solutions", cuerpo, usuario.email)


def avisar_cambio_password(usuario, request=None):
    """
    Confirmación de que la contraseña cambió. Si no fue el titular, el
    correo le permite reaccionar recuperando la cuenta de inmediato.
    """
    nombre = usuario.first_name or usuario.username
    cuando = timezone.localtime().strftime("%d-%m-%Y a las %H:%M")
    cuerpo = (
        f"Hola {nombre},\n\n"
        f"La contraseña de tu cuenta de LogiVisir ({usuario.username}) se cambió el {cuando}.\n\n"
        "Si fuiste tú, no tienes que hacer nada.\n\n"
        "Si NO fuiste tú, recupera tu cuenta ahora creando una contraseña nueva:\n"
        f"{_url(request, 'password_reset')}\n"
        "y avisa al administrador de tu empresa."
    )
    return _enviar("Tu contraseña de LogiVisir fue cambiada", cuerpo, usuario.email)


# ---------------------------------------------------------------------------
# RUT chileno
# ---------------------------------------------------------------------------
def _digito_verificador(cuerpo):
    suma, factor = 0, 2
    for d in reversed(cuerpo):
        suma += int(d) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - suma % 11
    return "0" if resto == 11 else "K" if resto == 10 else str(resto)


def normalizar_rut(texto):
    """
    Devuelve el RUT con puntos y guion (77.123.456-7) si es válido, o None.
    Acepta cualquier formato: 771234567, 77123456-7, 77.123.456-7.
    """
    limpio = "".join(c for c in (texto or "").upper() if c.isdigit() or c == "K")
    if len(limpio) < 8 or not limpio[:-1].isdigit():
        return None
    cuerpo, dv = limpio[:-1], limpio[-1]
    if _digito_verificador(cuerpo) != dv:
        return None
    return f"{int(cuerpo):,}".replace(",", ".") + f"-{dv}"


# ---------------------------------------------------------------------------
# Datos para transferir el pago del plan
# ---------------------------------------------------------------------------
def datos_transferencia():
    numero = getattr(settings, "PAGO_NUMERO_CUENTA", "")
    return {
        "titular": settings.PAGO_TITULAR,
        "banco": settings.PAGO_BANCO,
        "tipo_cuenta": settings.PAGO_TIPO_CUENTA,
        "numero_cuenta": numero or "000-0-000000-0",
        "rut": settings.PAGO_RUT,
        "correo": settings.PAGO_CORREO,
        "es_demo": not numero,
    }


def acusar_recibo_solicitud(solicitud, request=None):
    from .membresias import PRECIOS_PLAN
    pago = datos_transferencia()
    monto = f"{PRECIOS_PLAN.get(solicitud.plan_solicitado, 0):,}".replace(",", ".")
    aviso_demo = (
        "IMPORTANTE: estos son datos de demostración del proyecto; no transfieras dinero.\n\n"
        if pago["es_demo"] else ""
    )
    cuerpo = (
        f"Hola {solicitud.nombre_contacto},\n\n"
        f"Recibimos tu solicitud para contratar LogiVisir (plan {solicitud.get_plan_solicitado_display()}) "
        f"para {solicitud.nombre_empresa}.\n\n"
        f"Código de referencia: {solicitud.codigo_referencia}\n\n"
        "Para activar tu cuenta, transfiere el primer mes del plan:\n"
        f"  Monto: ${monto}\n"
        f"  Titular: {pago['titular']}\n"
        f"  RUT: {pago['rut']}\n"
        f"  Banco: {pago['banco']}\n"
        f"  {pago['tipo_cuenta']}: {pago['numero_cuenta']}\n"
        f"  Glosa o comentario: {solicitud.codigo_referencia}\n\n"
        f"{aviso_demo}"
        "Después sube el comprobante aquí, con tu código y este correo:\n"
        f"  {_url(request, 'subir_comprobante')}\n"
        f"(o envíalo a {pago['correo']} indicando tu código).\n\n"
        "Cuando validemos el pago te enviaremos a este correo los datos para ingresar a la plataforma."
    )
    return _enviar(
        f"Recibimos tu solicitud {solicitud.codigo_referencia} - LogiVisir Solutions",
        cuerpo,
        solicitud.email_contacto,
    )
