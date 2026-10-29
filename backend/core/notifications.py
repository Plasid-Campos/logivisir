"""
Notificaciones: por correo a clientes cuando su pedido sale a reparto, y al
chofer (dentro de la plataforma y por correo) cuando se le asigna una ruta o
su ruta cambia.

Igual que geocoding.py: nunca debe lanzar una excepción hacia arriba. Un
correo que falla (SMTP caído, dirección inválida, etc.) no debe bloquear
el flujo de la ruta.
"""
import logging

from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .models import Notificacion

logger = logging.getLogger(__name__)

DIAS_SEMANA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def fecha_legible(fecha):
    """'jueves 29-10-2026', o 'hoy' / 'mañana' cuando corresponde."""
    hoy = timezone.localdate()
    if fecha == hoy:
        return "hoy"
    if fecha == hoy + timezone.timedelta(days=1):
        return "mañana"
    return f"el {DIAS_SEMANA[fecha.weekday()]} {fecha.strftime('%d-%m-%Y')}"


def url_ruta_chofer(ruta):
    """Link al panel del chofer abierto en la fecha de esa ruta."""
    return f"{reverse('chofer_ruta_hoy')}?fecha={ruta.fecha.isoformat()}"


def _resumen_paradas(ruta):
    n = ruta.paradas.count()
    if n == 0:
        return "Aún no tiene paradas; te avisaremos cuando se agreguen."
    return f"{n} parada{'s' if n != 1 else ''}."


def _cuerpo_correo(parada, empresa):
    cliente = parada.cliente
    return (
        f"Hola {cliente.nombre},\n\n"
        f"Tu pedido de {empresa.nombre} va en camino.\n\n"
        f"Dirección de entrega: {cliente.direccion}"
        f"{', ' + cliente.comuna if cliente.comuna else ''}"
        f"{', ' + cliente.ciudad if cliente.ciudad else ''}\n"
        f"Eres la parada #{parada.orden} de la ruta de hoy.\n\n"
        f"Cualquier duda, contáctanos.\n\n"
        f"Equipo {empresa.nombre}"
    )


def notificar_pedido_en_camino(ruta):
    """
    Envía "tu pedido va en camino" a cada cliente con email de las paradas
    pendientes de una ruta. Idempotente: si ya se notificó, no reenvía.
    """
    if ruta.notificacion_enviada:
        return {"enviado": False, "motivo": "Ya se había notificado a los clientes de esta ruta."}

    empresa = ruta.empresa
    paradas = ruta.paradas.filter(estado_entrega="PENDIENTE").select_related("cliente")
    paradas_con_email = [p for p in paradas if p.cliente.email]

    enviados = 0
    for parada in paradas_con_email:
        try:
            send_mail(
                subject=f"Tu pedido de {empresa.nombre} va en camino",
                message=_cuerpo_correo(parada, empresa),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[parada.cliente.email],
                fail_silently=False,
            )
            enviados += 1
        except Exception:
            logger.exception("Fallo al enviar correo de aviso a %s (parada %s)", parada.cliente.email, parada.id)

    ruta.notificacion_enviada = True
    ruta.save(update_fields=["notificacion_enviada"])

    return {
        "enviado": True,
        "enviados": enviados,
        "total_pendientes": len(paradas),
        "sin_email": len(paradas) - len(paradas_con_email),
    }


def notificar_chofer_ruta_asignada(ruta, request=None):
    """
    Avisa por correo al chofer de una ruta recién creada, con un link
    directo a su panel. Si el chofer no tiene correo registrado (es
    opcional al crear su usuario), no hace nada.
    """
    chofer = ruta.chofer
    email = chofer.perfil.user.email
    if not email:
        return {"enviado": False, "motivo": "El chofer no tiene un correo registrado."}

    ruta_path = url_ruta_chofer(ruta)
    link = request.build_absolute_uri(ruta_path) if request is not None else ruta_path

    nombre_chofer = chofer.perfil.user.first_name or chofer.perfil.user.username
    cuerpo = (
        f"Hola {nombre_chofer},\n\n"
        f"Se te asignó una nueva ruta: {ruta.nombre}, para {fecha_legible(ruta.fecha)}.\n\n"
        f"Puedes revisar el detalle y las paradas en tu panel:\n{link}\n\n"
        f"Equipo {ruta.empresa.nombre}"
    )

    try:
        send_mail(
            subject=f"Nueva ruta asignada: {ruta.nombre} ({ruta.fecha.strftime('%d-%m-%Y')})",
            message=cuerpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        return {"enviado": True}
    except Exception:
        logger.exception("Fallo al enviar correo de ruta asignada a %s (ruta %s)", email, ruta.id)
        return {"enviado": False, "motivo": "Error al enviar el correo."}


# ---------------------------------------------------------------------------
# Avisos dentro de la plataforma (campana del menu)
# ---------------------------------------------------------------------------

def avisar_ruta_asignada(ruta, request=None):
    """
    Al crear una ruta: aviso en la campana del chofer y correo (si tiene).
    Devuelve el resultado del correo para que la vista pueda informarlo.
    """
    Notificacion.objects.create(
        usuario=ruta.chofer.perfil.user,
        tipo="RUTA_ASIGNADA",
        titulo=f"Nueva ruta: {ruta.nombre}",
        mensaje=f"Para {fecha_legible(ruta.fecha)}. {_resumen_paradas(ruta)}",
        url=url_ruta_chofer(ruta),
        ruta=ruta,
    )
    return notificar_chofer_ruta_asignada(ruta, request)


def avisar_ruta_actualizada(ruta, cambio):
    """
    Cuando la ruta cambia despues de asignada (paradas agregadas, quitadas o
    reordenadas). Si el chofer aun no leyo un aviso de esta ruta, se
    actualiza ese mismo aviso en vez de crear otro: armar una ruta parada
    por parada no debe llenarle la campana de mensajes.

    Las rutas de dias pasados no generan avisos.
    """
    if ruta.chofer_id is None or ruta.fecha < timezone.localdate():
        return

    usuario = ruta.chofer.perfil.user
    mensaje = f"Para {fecha_legible(ruta.fecha)}. {_resumen_paradas(ruta)} Último cambio: {cambio}"

    # Si cambio la fecha, los avisos viejos de esta ruta deben llevar al dia nuevo
    Notificacion.objects.filter(usuario=usuario, ruta=ruta).exclude(tipo="RUTA_QUITADA").update(
        url=url_ruta_chofer(ruta),
    )

    pendiente = Notificacion.objects.filter(
        usuario=usuario, ruta=ruta, leida=False,
    ).exclude(tipo="RUTA_QUITADA").first()
    if pendiente:
        pendiente.mensaje = mensaje[:300]
        pendiente.save(update_fields=["mensaje", "actualizada_en"])
        return

    Notificacion.objects.create(
        usuario=usuario,
        tipo="RUTA_ACTUALIZADA",
        titulo=f"Ruta actualizada: {ruta.nombre}",
        mensaje=mensaje[:300],
        url=url_ruta_chofer(ruta),
        ruta=ruta,
    )


def avisar_ruta_quitada(ruta, chofer_anterior):
    """
    Cuando la ruta pasa a otro chofer: el anterior debe saberlo para no salir
    a repartir. Sus avisos pendientes de esa ruta se dan por leidos (ya no
    llevan a nada suyo) y recibe un aviso nuevo, tambien por correo.
    """
    usuario = chofer_anterior.perfil.user
    Notificacion.objects.filter(usuario=usuario, ruta=ruta, leida=False).update(leida=True)
    Notificacion.objects.create(
        usuario=usuario,
        tipo="RUTA_QUITADA",
        titulo=f"Ya no tienes la ruta {ruta.nombre}",
        mensaje=f"La ruta de {fecha_legible(ruta.fecha)} se asignó a otro chofer.",
        url=reverse("chofer_mis_rutas"),
        ruta=ruta,
    )

    if not usuario.email:
        return
    nombre = usuario.first_name or usuario.username
    try:
        send_mail(
            subject=f"Ruta reasignada: {ruta.nombre} ({ruta.fecha.strftime('%d-%m-%Y')})",
            message=(
                f"Hola {nombre},\n\n"
                f"La ruta {ruta.nombre} de {fecha_legible(ruta.fecha)} se asignó a otro chofer, "
                "así que ya no está a tu cargo.\n\n"
                f"Equipo {ruta.empresa.nombre}"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[usuario.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Fallo al avisar ruta reasignada a %s (ruta %s)", usuario.email, ruta.id)
