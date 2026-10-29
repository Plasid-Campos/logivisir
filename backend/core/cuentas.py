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


def acusar_recibo_solicitud(solicitud):
    cuerpo = (
        f"Hola {solicitud.nombre_contacto},\n\n"
        f"Recibimos tu solicitud para contratar LogiVisir (plan {solicitud.get_plan_solicitado_display()}) "
        f"para {solicitud.nombre_empresa}.\n\n"
        f"Código de referencia: {solicitud.codigo_referencia}\n\n"
        "Nuestro equipo la revisará y te contactará para validar el pago. Cuando esté listo, "
        "te enviaremos a este correo los datos para ingresar a la plataforma."
    )
    return _enviar(
        f"Recibimos tu solicitud {solicitud.codigo_referencia} - LogiVisir Solutions",
        cuerpo,
        solicitud.email_contacto,
    )
