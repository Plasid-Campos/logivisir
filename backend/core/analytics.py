"""
Analitica de despachos: volumen de entregas por mes y por comuna, ranking de
clientes por cantidad de despachos y segmentacion RF (Recencia/Frecuencia)
via KMeans.

LogiVisir optimiza el reparto; no maneja precios ni montos del negocio de la
empresa cliente. Por eso todo se mide en despachos (pedidos entregados) y en
resultados de entrega (paradas), nunca en dinero.

Cada funcion recibe `empresa` explicitamente (mismo patron que tenancy.py)
para que las vistas sigan siendo las unicas responsables de resolver
get_empresa(request).
"""
from django.db.models import Count, Max, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import Cliente, ParadaRuta, Pedido

ESTADO_DESPACHADO = "ENTREGADO"  # unico estado que cuenta como despacho realizado
ESTADOS_PENDIENTES = ("PENDIENTE", "ASIGNADO")

RF_MIN_CLIENTES = 4  # minimo de clientes con despachos para que KMeans tenga sentido
N_CLUSTERS = 4
# Orden de mejor a peor: usado tanto para nombrar clusters como para
# inicializar el conteo en la vista aunque un segmento quede en 0.
SEGMENTOS_ORDEN = ("VIP", "Frecuente", "Ocasional", "En riesgo")


def _porcentaje(parte, total):
    return round(parte * 100 / total, 1) if total else None


def resumen_despachos(empresa):
    pedidos = Pedido.objects.filter(empresa=empresa)
    despachos = pedidos.filter(estado=ESTADO_DESPACHADO).count()
    pendientes = pedidos.filter(estado__in=ESTADOS_PENDIENTES).count()

    clientes_atendidos = (
        Cliente.objects.filter(empresa=empresa, pedidos__estado=ESTADO_DESPACHADO)
        .distinct()
        .count()
    )

    # Resultado en terreno, a nivel de parada (KPI-3 y KPI-4 del informe)
    paradas = ParadaRuta.objects.filter(ruta__empresa=empresa)
    entregadas = paradas.filter(estado_entrega="ENTREGADO")
    n_entregadas = entregadas.count()
    n_fallidas = paradas.filter(estado_entrega="NO_ENTREGADO").count()
    n_con_foto = entregadas.exclude(foto_entrega="").exclude(foto_entrega__isnull=True).count()

    return {
        "despachos": despachos,
        "pedidos_pendientes": pendientes,
        "clientes_atendidos": clientes_atendidos,
        "entregas_fallidas": n_fallidas,
        "tasa_exito": _porcentaje(n_entregadas, n_entregadas + n_fallidas),
        "entregas_con_foto": _porcentaje(n_con_foto, n_entregadas),
    }


def despachos_por_mes(empresa, meses=12):
    hoy = timezone.localdate()
    # primer dia del mes, `meses` meses atras (aproximado por dias, suficiente
    # como corte de "ultimos N meses" para un reporte)
    cutoff = hoy.replace(day=1) - timezone.timedelta(days=31 * (meses - 1))
    cutoff = cutoff.replace(day=1)

    filas = (
        Pedido.objects.filter(
            empresa=empresa, estado=ESTADO_DESPACHADO, creado_en__date__gte=cutoff
        )
        .annotate(mes=TruncMonth("creado_en"))
        .values("mes")
        .annotate(despachos=Count("id"), clientes=Count("cliente", distinct=True))
        .order_by("mes")
    )
    return list(filas)


def despachos_por_comuna(empresa):
    filas = (
        Pedido.objects.filter(empresa=empresa, estado=ESTADO_DESPACHADO)
        .values("cliente__comuna")
        .annotate(despachos=Count("id"), clientes=Count("cliente", distinct=True))
        .order_by("-despachos")
    )
    return [
        {
            "comuna": fila["cliente__comuna"] or "Sin comuna",
            "despachos": fila["despachos"],
            "clientes": fila["clientes"],
        }
        for fila in filas
    ]


def top_clientes(empresa, limite=10):
    filtro = Q(pedidos__estado=ESTADO_DESPACHADO)
    clientes = (
        Cliente.objects.filter(empresa=empresa)
        .annotate(
            num_despachos=Count("pedidos", filter=filtro, distinct=True),
            ultimo_despacho=Max("pedidos__creado_en", filter=filtro),
        )
        .filter(num_despachos__gt=0)
        .order_by("-num_despachos", "nombre")[:limite]
    )
    return [
        {
            "cliente_id": c.id,
            "nombre": c.nombre,
            "comuna": c.comuna or "Sin comuna",
            "num_despachos": c.num_despachos,
            "ultimo_despacho": timezone.localtime(c.ultimo_despacho).date(),
        }
        for c in clientes
    ]


def calcular_rf(empresa, hoy=None):
    hoy = hoy or timezone.localdate()
    filtro = Q(pedidos__estado=ESTADO_DESPACHADO)

    clientes = (
        Cliente.objects.filter(empresa=empresa)
        .annotate(
            frecuencia=Count("pedidos", filter=filtro, distinct=True),
            ultimo_despacho=Max("pedidos__creado_en", filter=filtro),
        )
        .filter(frecuencia__gt=0)
    )

    resultado = []
    for c in clientes:
        ultimo_local = timezone.localtime(c.ultimo_despacho).date()
        resultado.append(
            {
                "cliente_id": c.id,
                "nombre": c.nombre,
                "comuna": c.comuna or "Sin comuna",
                "recencia_dias": (hoy - ultimo_local).days,
                "frecuencia": c.frecuencia,
            }
        )
    return resultado


def segmentar_clientes(empresa, hoy=None):
    """
    Segmentacion RF via KMeans (aprendizaje no supervisado real, no una regla
    ad-hoc): agrupa clientes por Recencia (dias desde el ultimo despacho) y
    Frecuencia (cantidad de despachos), y nombra cada cluster segun un score
    de sus centroides, para que "VIP" siempre sea el grupo con mejor
    combinacion real y no dependa del indice arbitrario que KMeans le haya
    asignado en esta corrida.
    """
    rf = calcular_rf(empresa, hoy=hoy)

    if len(rf) < RF_MIN_CLIENTES:
        for r in rf:
            r["cluster_id"] = None
            r["segmento"] = None
        return {
            "clientes": rf,
            "clustering_aplicado": False,
            "motivo": (
                f"Se requieren al menos {RF_MIN_CLIENTES} clientes con despachos "
                f"entregados para segmentar (hay {len(rf)})."
            ),
        }

    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    X = np.array([[r["recencia_dias"], r["frecuencia"]] for r in rf], dtype=float)
    X_scaled = StandardScaler().fit_transform(X)

    kmeans = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init=10)
    labels = kmeans.fit_predict(X_scaled)

    # Score por centroide en el mismo espacio estandarizado usado para el
    # ajuste: menor recencia es mejor (se resta), mayor frecuencia es mejor.
    centros = kmeans.cluster_centers_
    score_por_cluster = -centros[:, 0] + centros[:, 1]
    orden_clusters = np.argsort(-score_por_cluster)  # de mejor a peor
    etiqueta_por_cluster = {
        int(cluster_idx): SEGMENTOS_ORDEN[rank]
        for rank, cluster_idx in enumerate(orden_clusters)
    }

    for r, cluster_idx in zip(rf, labels):
        r["cluster_id"] = int(cluster_idx)
        r["segmento"] = etiqueta_por_cluster[int(cluster_idx)]

    return {"clientes": rf, "clustering_aplicado": True, "motivo": None}
