"""
Membresías de las empresas clientes: precios por plan, registro de pagos y
renovación del vencimiento. Solo trata el dinero que las empresas le pagan a
LogiVisir; nunca las ventas de esas empresas.
"""
import calendar
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from .models import Empresa, Pago

# Precio mensual por plan en CLP (mismos valores del sitio público y del informe).
PRECIOS_PLAN = {"BASICO": 49990, "PRO": 89990, "EMPRESARIAL": 149990}
MESES_PERMITIDOS = (1, 3, 6, 12)

# Lo que la página de inicio muestra de cada plan. Todos los planes traen todas
# las funciones; cambian el tamaño de operación sugerido y el soporte.
PLANES_PUBLICOS = (
    {
        "codigo": "BASICO", "nombre": "Básico", "destacado": False,
        "para": "Para negocios que están partiendo a ordenar su reparto (1 a 2 vehículos).",
        "incluye": (
            "Todas las funciones de LogiVisir",
            "Soporte por correo",
        ),
    },
    {
        "codigo": "PRO", "nombre": "Pro", "destacado": True,
        "para": "Para operaciones con varias rutas y choferes cada día (3 a 6 vehículos).",
        "incluye": (
            "Todas las funciones de LogiVisir",
            "Carga inicial de clientes asistida",
            "Soporte prioritario",
        ),
    },
    {
        "codigo": "EMPRESARIAL", "nombre": "Empresarial", "destacado": False,
        "para": "Para distribuidoras con flota mayor o más de un local (7 vehículos o más).",
        "incluye": (
            "Todas las funciones de LogiVisir",
            "Carga inicial de clientes asistida",
            "Capacitación al equipo",
            "Soporte dedicado",
        ),
    },
)


FUNCIONES_TODOS_LOS_PLANES = (
    "Rutas optimizadas con distancias de calle reales",
    "Panel móvil del chofer con foto o motivo de no entrega",
    "Analítica y segmentación de clientes (K-Means)",
    "Avisos en la plataforma y por correo",
    "Usuarios dueño, administrador y chofer",
    "Exportación de despachos a CSV",
)


def planes_publicos():
    """Planes con su precio vigente, para no repetir montos en las plantillas."""
    return [dict(p, precio=PRECIOS_PLAN[p["codigo"]]) for p in PLANES_PUBLICOS]


def sumar_meses(fecha, meses):
    """Misma fecha N meses después; si ese día no existe, el último del mes."""
    mes = fecha.month - 1 + meses
    anio = fecha.year + mes // 12
    mes = mes % 12 + 1
    dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
    return date(anio, mes, dia)


def calcular_periodo(empresa, meses, hoy=None):
    """
    Si la membresía sigue vigente, el pago se suma a continuación del
    vencimiento actual (no se pierden días); si ya venció o no tiene fecha,
    el período parte hoy.
    """
    hoy = hoy or timezone.localdate()
    vence = empresa.suscripcion_vence
    desde = vence + timedelta(days=1) if vence and vence >= hoy else hoy
    hasta = sumar_meses(desde, meses) - timedelta(days=1)
    return desde, hasta


@transaction.atomic
def registrar_pago(empresa, *, plan, monto, fecha_pago, meses, medio, referencia="", notas="",
                   usuario=None, reactivar=False, hoy=None):
    desde, hasta = calcular_periodo(empresa, meses, hoy)
    pago = Pago.objects.create(
        empresa=empresa, plan=plan, monto=monto, fecha_pago=fecha_pago, meses=meses,
        periodo_desde=desde, periodo_hasta=hasta, medio=medio,
        referencia=referencia, notas=notas, vence_anterior=empresa.suscripcion_vence,
        registrado_por=usuario,
    )
    empresa.plan = plan
    empresa.suscripcion_vence = hasta
    campos = ["plan", "suscripcion_vence"]
    if reactivar and not empresa.activa:
        empresa.activa = True
        campos.append("activa")
    empresa.save(update_fields=campos)
    return pago


@transaction.atomic
def anular_pago(pago, *, usuario=None, motivo=""):
    """
    Marca el pago como anulado (queda en el historial). Si era el pago que
    fijó el vencimiento actual, el vencimiento vuelve al que tenía antes.
    """
    if pago.anulado:
        return False
    pago.anulado = True
    pago.anulado_en = timezone.now()
    pago.anulado_por = usuario
    pago.motivo_anulacion = motivo
    pago.save(update_fields=["anulado", "anulado_en", "anulado_por", "motivo_anulacion"])
    empresa = pago.empresa
    if empresa.suscripcion_vence == pago.periodo_hasta:
        empresa.suscripcion_vence = pago.vence_anterior
        empresa.save(update_fields=["suscripcion_vence"])
    return True


def mrr(empresas, hoy=None):
    """
    Ingreso mensual recurrente: precio mensual del plan de cada empresa activa
    con la membresía al día.
    """
    hoy = hoy or timezone.localdate()
    return sum(
        PRECIOS_PLAN.get(e.plan, 0) for e in empresas
        if e.activa and e.plan and e.suscripcion_vence and e.suscripcion_vence >= hoy
    )


def ingresos_entre(desde, hasta):
    pagos = Pago.objects.filter(anulado=False, fecha_pago__gte=desde, fecha_pago__lte=hasta)
    return sum(p.monto for p in pagos)


def ingresos_por_mes(meses=6, hoy=None):
    """Lista [(etiqueta 'mm-aaaa', total)] de los últimos N meses, del más antiguo al actual."""
    hoy = hoy or timezone.localdate()
    inicio_mes = hoy.replace(day=1)
    salida = []
    for i in range(meses - 1, -1, -1):
        desde = sumar_meses(inicio_mes, -i)
        hasta = sumar_meses(desde, 1) - timedelta(days=1)
        salida.append((desde.strftime("%m-%Y"), ingresos_entre(desde, hasta)))
    return salida
