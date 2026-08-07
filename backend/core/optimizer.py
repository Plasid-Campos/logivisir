"""
Motor de optimización de rutas de Logivisir.

Implementación propia (sin librerías de optimización externas) de:
  1. Heurística de construcción "vecino más cercano" (nearest neighbor).
  2. Mejora local 2-opt sobre el ciclo cerrado origen -> paradas -> origen.

El problema de encontrar el circuito de menor distancia que visita un
conjunto de puntos y vuelve al origen es el Problema del Viajante (TSP),
NP-difícil: no existe (que se conozca) un algoritmo que lo resuelva de forma
exacta en tiempo razonable más allá de unas ~15-20 paradas. Para el tamaño
de rutas real de una pyme (decenas de paradas por reparto), una heurística
de construcción + una mejora local es el approach estándar en la práctica:
da resultados cercanos al óptimo en tiempo polinomial (O(n^2) por pasada),
en vez de intentar una solución exacta que no escalaría.

Complejidad:
  - Vecino más cercano: O(n^2) — en cada paso busca el punto no visitado
    más cercano al último visitado.
  - 2-opt: cada pasada es O(n^2) (revisa todos los pares de aristas);
    se repite hasta que una pasada completa no logra ninguna mejora.
"""
from math import radians, sin, cos, sqrt, atan2

RADIO_TIERRA_KM = 6371.0


def haversine(lat1, lon1, lat2, lon2):
    """Distancia en línea recta (km) entre dos puntos lat/lon."""
    lat1_r, lon1_r, lat2_r, lon2_r = map(radians, (lat1, lon1, lat2, lon2))
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = sin(dlat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return RADIO_TIERRA_KM * c


def _distancia_total(origen, puntos, orden):
    """Distancia del ciclo cerrado origen -> puntos[orden] -> origen."""
    if not orden:
        return 0.0
    coords = {p[0]: (p[1], p[2]) for p in puntos}
    total = 0.0
    anterior = origen
    for pid in orden:
        actual = coords[pid]
        total += haversine(anterior[0], anterior[1], actual[0], actual[1])
        anterior = actual
    total += haversine(anterior[0], anterior[1], origen[0], origen[1])
    return total


def construir_vecino_mas_cercano(origen, puntos):
    """
    origen: (lat, lon)
    puntos: lista de (id, lat, lon)
    Devuelve la lista de ids en el orden construido.
    """
    restantes = list(puntos)
    orden = []
    actual = origen

    while restantes:
        mas_cercano = min(
            restantes,
            key=lambda p: haversine(actual[0], actual[1], p[1], p[2]),
        )
        orden.append(mas_cercano[0])
        actual = (mas_cercano[1], mas_cercano[2])
        restantes.remove(mas_cercano)

    return orden


def mejorar_2opt(origen, puntos, orden_inicial):
    """
    2-opt: mientras exista un intercambio de dos aristas del ciclo que
    reduzca la distancia total, se aplica. Termina cuando una pasada
    completa no encuentra ninguna mejora (óptimo local).
    """
    if len(orden_inicial) < 4:
        return orden_inicial

    coords = {p[0]: (p[1], p[2]) for p in puntos}
    mejor_orden = orden_inicial[:]
    mejorado = True

    while mejorado:
        mejorado = False
        n = len(mejor_orden)
        for i in range(n - 1):
            for j in range(i + 1, n):
                nuevo_orden = mejor_orden[:i] + mejor_orden[i:j + 1][::-1] + mejor_orden[j + 1:]
                if _distancia_total(origen, puntos, nuevo_orden) < _distancia_total(origen, puntos, mejor_orden) - 1e-9:
                    mejor_orden = nuevo_orden
                    mejorado = True

    return mejor_orden


def optimizar_ruta(origen, puntos):
    """
    origen: (lat, lon) del punto de partida/retorno.
    puntos: lista de (id, lat, lon) a visitar.
    Devuelve la lista de ids en el orden de visita optimizado (ciclo cerrado).
    """
    if not puntos:
        return []
    if len(puntos) == 1:
        return [puntos[0][0]]

    orden_inicial = construir_vecino_mas_cercano(origen, puntos)
    return mejorar_2opt(origen, puntos, orden_inicial)


def optimizar_paradas(ruta):
    """
    Punto de entrada usado por las vistas: recibe una instancia de Ruta,
    optimiza el orden de sus ParadaRuta según lat/lon del cliente y el
    origen de la empresa, y guarda el nuevo `orden` en cada parada.

    Los clientes sin coordenadas geocodificadas quedan al final, en el
    orden que ya tenían, para no descartarlos de la ruta.
    """
    empresa = ruta.empresa
    if empresa.latitud_origen is None or empresa.longitud_origen is None:
        return {
            "optimizado": False,
            "motivo": "La empresa no tiene una dirección de origen geocodificada.",
        }

    origen = (empresa.latitud_origen, empresa.longitud_origen)

    paradas = list(ruta.paradas.select_related("cliente").order_by("orden"))
    con_coordenadas = [p for p in paradas if p.cliente.latitud is not None and p.cliente.longitud is not None]
    sin_coordenadas = [p for p in paradas if p not in con_coordenadas]

    if not con_coordenadas:
        return {
            "optimizado": False,
            "motivo": "Ninguna parada tiene coordenadas geocodificadas todavía.",
        }

    puntos = [(p.id, p.cliente.latitud, p.cliente.longitud) for p in con_coordenadas]
    orden_optimizado = optimizar_ruta(origen, puntos)

    paradas_por_id = {p.id: p for p in con_coordenadas}
    secuencia_final = [paradas_por_id[pid] for pid in orden_optimizado] + sin_coordenadas

    # `orden` tiene unique_together=(ruta, orden): reasignar directo a 1..n
    # puede chocar contra valores todavia no actualizados de otras paradas
    # de la misma ruta. Se pasa primero por un rango temporal fuera de
    # cualquier valor real para evitar la colision.
    OFFSET_TEMPORAL = 1_000_000
    for i, parada in enumerate(secuencia_final):
        parada.orden = OFFSET_TEMPORAL + i
        parada.save(update_fields=["orden"])

    for i, parada in enumerate(secuencia_final):
        parada.orden = i + 1
        parada.save(update_fields=["orden"])

    return {
        "optimizado": True,
        "cantidad": len(con_coordenadas),
        "sin_coordenadas": [p.cliente.nombre for p in sin_coordenadas],
    }
