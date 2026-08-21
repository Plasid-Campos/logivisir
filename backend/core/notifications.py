"""
Notificaciones por correo: a clientes cuando su pedido sale a reparto, y a
choferes cuando se les asigna una ruta nueva.

Igual que geocoding.py: nunca debe lanzar una excepción hacia arriba. Un
correo que falla (SMTP caído, dirección inválida, etc.) no debe bloquear
el flujo de la ruta.
"""
import logging

from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)


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

    ruta_path = reverse("chofer_ruta_hoy")
    link = request.build_absolute_uri(ruta_path) if request is not None else ruta_path

    nombre_chofer = chofer.perfil.user.first_name or chofer.perfil.user.username
    cuerpo = (
        f"Hola {nombre_chofer},\n\n"
        f"Se te asignó una nueva ruta: {ruta.nombre}, para el "
        f"{ruta.fecha.strftime('%d-%m-%Y')}.\n\n"
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
