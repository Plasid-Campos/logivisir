"""
Analitica de ventas: ingresos, ranking de clientes/comunas y segmentacion
RFM (Recency/Frequency/Monetary) via KMeans. Todo se calcula al vuelo desde
Pedido/PedidoItem/Cliente -- no hay modelos nuevos. Cada funcion recibe
`empresa` explicitamente (mismo patron que tenancy.py) para que las vistas
sigan siendo las unicas responsables de resolver get_empresa(request).
"""
from decimal import Decimal

from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import Cliente, Pedido

ESTADO_INGRESO = "ENTREGADO"  # unico estado que cuenta como venta realizada
ESTADOS_PENDIENTES = ("PENDIENTE", "ASIGNADO")

RFM_MIN_CLIENTES = 4  # minimo de clientes con pedidos para que KMeans tenga sentido
N_CLUSTERS = 4
# Orden de mejor a peor: usado tanto para nombrar clusters como para
# inicializar el conteo en la vista aunque un segmento quede en 0.
SEGMENTOS_ORDEN = ("VIP", "Frecuente", "Ocasional", "En riesgo")


def ingresos_resumen(empresa):
    pedidos_ok = Pedido.objects.filter(empresa=empresa, estado=ESTADO_INGRESO)
    agregado = pedidos_ok.aggregate(total=Sum("total"), cantidad=Count("id"))
    ingresos_totales = agregado["total"] or Decimal("0")
    cantidad_pedidos = agregado["cantidad"] or 0

    ticket_promedio = (
        ingresos_totales / cantidad_pedidos if cantidad_pedidos else Decimal("0")
    )

    clientes_con_compras = (
        Cliente.objects.filter(empresa=empresa, pedidos__estado=ESTADO_INGRESO)
        .distinct()
        .count()
    )

    ingresos_pendientes = Pedido.objects.filter(
        empresa=empresa, estado__in=ESTADOS_PENDIENTES
    ).aggregate(total=Sum("total"))["total"] or Decimal("0")

    return {
        "ingresos_totales": ingresos_totales,
        "cantidad_pedidos": cantidad_pedidos,
        "ticket_promedio": ticket_promedio,
        "clientes_con_compras": clientes_con_compras,
        "ingresos_pendientes": ingresos_pendientes,
    }


def ingresos_por_mes(empresa, meses=12):
    hoy = timezone.localdate()
    # primer dia del mes, `meses` meses atras (aproximado por dias, suficiente
    # como corte de "ultimos N meses" para un reporte)
    cutoff = hoy.replace(day=1) - timezone.timedelta(days=31 * (meses - 1))
    cutoff = cutoff.replace(day=1)

    filas = (
        Pedido.objects.filter(
            empresa=empresa, estado=ESTADO_INGRESO, creado_en__date__gte=cutoff
        )
        .annotate(mes=TruncMonth("creado_en"))
        .values("mes")
        .annotate(ingresos=Sum("total"), pedidos=Count("id"))
        .order_by("mes")
    )
    return list(filas)


def ingresos_por_comuna(empresa):
    filas = (
        Pedido.objects.filter(empresa=empresa, estado=ESTADO_INGRESO)
        .values("cliente__comuna")
        .annotate(
            ingresos=Sum("total"),
            clientes=Count("cliente", distinct=True),
            pedidos=Count("id"),
        )
        .order_by("-ingresos")
    )
    resultado = []
    for fila in filas:
        resultado.append(
            {
                "comuna": fila["cliente__comuna"] or "Sin comuna",
                "ingresos": fila["ingresos"] or Decimal("0"),
                "clientes": fila["clientes"],
                "pedidos": fila["pedidos"],
            }
        )
    return resultado


def top_clientes(empresa, limite=10):
    clientes = (
        Cliente.objects.filter(empresa=empresa)
        .annotate(
            gastado=Sum("pedidos__total", filter=Q(pedidos__estado=ESTADO_INGRESO)),
            num_pedidos=Count(
                "pedidos", filter=Q(pedidos__estado=ESTADO_INGRESO), distinct=True
            ),
        )
        .filter(num_pedidos__gt=0)
        .order_by("-gastado")[:limite]
    )

    resultado = []
    for c in clientes:
        resultado.append(
            {
                "cliente_id": c.id,
                "nombre": c.nombre,
                "comuna": c.comuna or "Sin comuna",
                "gastado": c.gastado or Decimal("0"),
                "num_pedidos": c.num_pedidos,
                "ticket_promedio": (c.gastado / c.num_pedidos) if c.num_pedidos else Decimal("0"),
            }
        )
    return resultado


def calcular_rfm(empresa, hoy=None):
    hoy = hoy or timezone.localdate()

    clientes = (
        Cliente.objects.filter(empresa=empresa)
        .annotate(
            frecuencia=Count(
                "pedidos", filter=Q(pedidos__estado=ESTADO_INGRESO), distinct=True
            ),
            monetario=Sum("pedidos__total", filter=Q(pedidos__estado=ESTADO_INGRESO)),
            ultima_compra=Max(
                "pedidos__creado_en", filter=Q(pedidos__estado=ESTADO_INGRESO)
            ),
        )
        .filter(frecuencia__gt=0)
    )

    resultado = []
    for c in clientes:
        ultima_local = timezone.localtime(c.ultima_compra).date()
        resultado.append(
            {
                "cliente_id": c.id,
                "nombre": c.nombre,
                "comuna": c.comuna or "Sin comuna",
                "recencia_dias": (hoy - ultima_local).days,
                "frecuencia": c.frecuencia,
                "monetario": c.monetario or Decimal("0"),
            }
        )
    return resultado


def segmentar_clientes(empresa, hoy=None):
    """
    Segmentacion RFM via KMeans (aprendizaje no supervisado real, no una
    regla ad-hoc): agrupa clientes por Recencia/Frecuencia/Monetario y
    nombra cada cluster segun un score de sus centroides, para que "VIP"
    siempre sea el grupo con mejor combinacion real de RFM y no dependa del
    indice arbitrario que KMeans le haya asignado en esta corrida.
    """
    rfm = calcular_rfm(empresa, hoy=hoy)

    if len(rfm) < RFM_MIN_CLIENTES:
        for r in rfm:
            r["cluster_id"] = None
            r["segmento"] = None
        return {
            "clientes": rfm,
            "clustering_aplicado": False,
            "motivo": (
                f"Se requieren al menos {RFM_MIN_CLIENTES} clientes con pedidos "
                f"entregados para segmentar (hay {len(rfm)})."
            ),
        }

    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    X = np.array(
        [[r["recencia_dias"], r["frecuencia"], float(r["monetario"])] for r in rfm],
        dtype=float,
    )
    X_scaled = StandardScaler().fit_transform(X)

    kmeans = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init=10)
    labels = kmeans.fit_predict(X_scaled)

    # Score por centroide en el mismo espacio estandarizado usado para el
    # ajuste: menor recencia es mejor (se resta), mayor frecuencia/monetario
    # es mejor (se suman).
    centros = kmeans.cluster_centers_
    score_por_cluster = -centros[:, 0] + centros[:, 1] + centros[:, 2]
    orden_clusters = np.argsort(-score_por_cluster)  # de mejor a peor
    etiqueta_por_cluster = {
        int(cluster_idx): SEGMENTOS_ORDEN[rank]
        for rank, cluster_idx in enumerate(orden_clusters)
    }

    for r, cluster_idx in zip(rfm, labels):
        r["cluster_id"] = int(cluster_idx)
        r["segmento"] = etiqueta_por_cluster[int(cluster_idx)]

    return {"clientes": rfm, "clustering_aplicado": True, "motivo": None}
