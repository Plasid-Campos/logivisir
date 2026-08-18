"""
Notificaciones por correo a clientes cuando su pedido sale a reparto.

Igual que geocoding.py: nunca debe lanzar una excepción hacia arriba. Un
correo que falla (SMTP caído, dirección inválida, etc.) no debe bloquear
el flujo de la ruta.
"""
import logging

from django.core.mail import send_mail
from django.conf import settings

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
