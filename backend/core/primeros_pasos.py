"""
Guía de primeros pasos del panel: cada paso se marca solo, mirando los datos
reales de la empresa (no hay que "cerrar" nada a mano).
"""
from django.urls import reverse

from .models import Chofer, Cliente, ParadaRuta, Pedido, Ruta


def pasos_de(empresa):
    if empresa is None:
        return []
    return [
        {
            "titulo": "Indica desde dónde salen tus repartos",
            "ayuda": "Es el punto de partida y regreso de cada ruta.",
            "hecho": empresa.latitud_origen is not None,
            "url": reverse("configurar_empresa"),
            "boton": "Poner dirección",
        },
        {
            "titulo": "Agrega tus clientes",
            "ayuda": "Escribe la dirección y LogiVisir la ubica en el mapa.",
            "hecho": Cliente.objects.filter(empresa=empresa).exists(),
            "url": reverse("crear_cliente"),
            "boton": "Agregar cliente",
        },
        {
            "titulo": "Crea a tu chofer",
            "ayuda": "Le das un usuario y entra desde su celular.",
            "hecho": Chofer.objects.filter(perfil__empresa=empresa).exists(),
            "url": reverse("crear_chofer"),
            "boton": "Crear chofer",
        },
        {
            "titulo": "Registra los pedidos del día",
            "ayuda": "Qué se le lleva a cada cliente (sin precios).",
            "hecho": Pedido.objects.filter(empresa=empresa).exists(),
            "url": reverse("crear_pedido"),
            "boton": "Nuevo pedido",
        },
        {
            "titulo": "Crea una ruta y presiona Optimizar",
            "ayuda": "LogiVisir ordena las paradas por el camino más corto.",
            "hecho": Ruta.objects.filter(empresa=empresa, optimizada_en__isnull=False).exists(),
            "url": reverse("crear_ruta"),
            "boton": "Crear ruta",
        },
        {
            "titulo": "Tu chofer registra la primera entrega",
            "ayuda": "Verás la foto o el motivo en el detalle de la ruta.",
            "hecho": ParadaRuta.objects.filter(ruta__empresa=empresa).exclude(estado_entrega="PENDIENTE").exists(),
            "url": reverse("lista_rutas"),
            "boton": "Ver rutas",
        },
    ]


def resumen(empresa):
    pasos = pasos_de(empresa)
    hechos = sum(1 for p in pasos if p["hecho"])
    siguiente = next((i for i, p in enumerate(pasos) if not p["hecho"]), None)
    return {
        "pasos": pasos,
        "hechos": hechos,
        "total": len(pasos),
        "porcentaje": round(100 * hechos / len(pasos)) if pasos else 100,
        "completo": hechos == len(pasos),
        "siguiente": siguiente,
    }
