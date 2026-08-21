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

Distancia usada por el algoritmo:
  Por defecto (y en todos los tests de este módulo) se usa `haversine`,
  distancia en línea recta. Sirve para geometría/tests, pero en la calle
  real puede llevar a errores groseros: dos puntos "cerca" en línea recta
  pueden estar separados por un cerro, un río o una autopista sin salida
  cercana (ej: Vitacura <-> Chicureo en Santiago), y el algoritmo termina
  metiendo una parada lejana en medio de dos cercanas porque en línea
  recta "no se ve" el rodeo real que hay que dar.

  Por eso `optimizar_paradas` (el punto de entrada real desde las vistas)
  intenta primero pedir distancias de la red vial real a OSRM (Open
  Source Routing Machine, sobre datos de OpenStreetMap) vía
  `obtener_distancia_fn_red_vial`, y si no está disponible (sin internet,
  timeout, fuera de cobertura) cae de vuelta a `haversine` — nunca debe
  bloquear la optimización de una ruta. Todas las funciones de este
  módulo aceptan un `distancia_fn(a, b)` opcional para poder intercambiar
  la fuente de distancia sin duplicar el algoritmo.
"""
import logging
from math import radians, sin, cos, sqrt, atan2

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

RADIO_TIERRA_KM = 6371.0
OSRM_URL = "https://router.project-osrm.org"
OSRM_TIMEOUT_SEGUNDOS = 8


def haversine(lat1, lon1, lat2, lon2):
    """Distancia en línea recta (km) entre dos puntos lat/lon."""
    lat1_r, lon1_r, lat2_r, lon2_r = map(radians, (lat1, lon1, lat2, lon2))
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = sin(dlat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return RADIO_TIERRA_KM * c


def _distancia_par_haversine(a, b):
    return haversine(a[0], a[1], b[0], b[1])


def _distancia_total(origen, puntos, orden, distancia_fn=None):
    """Distancia del ciclo cerrado origen -> puntos[orden] -> origen."""
    if not orden:
        return 0.0
    distancia_fn = distancia_fn or _distancia_par_haversine
    coords = {p[0]: (p[1], p[2]) for p in puntos}
    total = 0.0
    anterior = origen
    for pid in orden:
        actual = coords[pid]
        total += distancia_fn(anterior, actual)
        anterior = actual
    total += distancia_fn(anterior, origen)
    return total


def construir_vecino_mas_cercano(origen, puntos, distancia_fn=None):
    """
    origen: (lat, lon)
    puntos: lista de (id, lat, lon)
    Devuelve la lista de ids en el orden construido.
    """
    distancia_fn = distancia_fn or _distancia_par_haversine
    restantes = list(puntos)
    orden = []
    actual = origen

    while restantes:
        mas_cercano = min(
            restantes,
            key=lambda p: distancia_fn(actual, (p[1], p[2])),
        )
        orden.append(mas_cercano[0])
        actual = (mas_cercano[1], mas_cercano[2])
        restantes.remove(mas_cercano)

    return orden


def mejorar_2opt(origen, puntos, orden_inicial, distancia_fn=None):
    """
    2-opt: mientras exista un intercambio de dos aristas del ciclo que
    reduzca la distancia total, se aplica. Termina cuando una pasada
    completa no encuentra ninguna mejora (óptimo local).
    """
    if len(orden_inicial) < 4:
        return orden_inicial

    distancia_fn = distancia_fn or _distancia_par_haversine
    mejor_orden = orden_inicial[:]
    mejorado = True

    while mejorado:
        mejorado = False
        n = len(mejor_orden)
        for i in range(n - 1):
            for j in range(i + 1, n):
                nuevo_orden = mejor_orden[:i] + mejor_orden[i:j + 1][::-1] + mejor_orden[j + 1:]
                if _distancia_total(origen, puntos, nuevo_orden, distancia_fn) < _distancia_total(origen, puntos, mejor_orden, distancia_fn) - 1e-9:
                    mejor_orden = nuevo_orden
                    mejorado = True

    return mejor_orden


def optimizar_ruta(origen, puntos, distancia_fn=None):
    """
    origen: (lat, lon) del punto de partida/retorno.
    puntos: lista de (id, lat, lon) a visitar.
    distancia_fn: opcional, (a, b) -> km. Por defecto usa haversine (línea
    recta); `optimizar_paradas` le pasa distancia real de calle cuando OSRM
    está disponible.
    Devuelve la lista de ids en el orden de visita optimizado (ciclo cerrado).
    """
    if not puntos:
        return []
    if len(puntos) == 1:
        return [puntos[0][0]]

    orden_inicial = construir_vecino_mas_cercano(origen, puntos, distancia_fn)
    return mejorar_2opt(origen, puntos, orden_inicial, distancia_fn)


def obtener_distancia_fn_red_vial(origen, puntos):
    """
    Intenta construir una función de distancia (a, b) -> km basada en la
    red vial real, pidiéndole a OSRM (Open Source Routing Machine, sobre
    datos de OpenStreetMap) la matriz de distancias entre el origen y
    todos los puntos en una sola consulta.

    Usa por defecto el servidor demo público de OSRM: gratis y sin API
    key, igual que Nominatim en geocoding.py, pero con el mismo límite de
    no ser apto para uso intensivo en producción (para eso se apunta
    OSRM_URL a un servidor propio vía variable de entorno).

    Nunca lanza una excepción hacia arriba: si algo falla (sin internet,
    timeout, fuera de cobertura, servidor caído) devuelve None y quien
    llama debe seguir funcionando con `haversine` como respaldo.
    """
    if not getattr(settings, "OSRM_HABILITADO", True):
        return None
    if not puntos:
        return None

    coords_ordenadas = [origen] + [(p[1], p[2]) for p in puntos]
    coords_str = ";".join(f"{lon},{lat}" for (lat, lon) in coords_ordenadas)
    osrm_url = getattr(settings, "OSRM_URL", OSRM_URL)
    url = f"{osrm_url}/table/v1/driving/{coords_str}"

    try:
        resp = requests.get(url, params={"annotations": "distance"}, timeout=OSRM_TIMEOUT_SEGUNDOS)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "Ok":
            logger.warning("OSRM devolvió code=%s, se usará distancia en línea recta.", data.get("code"))
            return None
        distancias_m = data["distances"]
    except Exception:
        logger.warning("OSRM no disponible, se usará distancia en línea recta como respaldo.", exc_info=True)
        return None

    matriz_km = [
        [(d / 1000.0 if d is not None else float("inf")) for d in fila]
        for fila in distancias_m
    ]
    indice_por_coord = {coord: i for i, coord in enumerate(coords_ordenadas)}

    def distancia_fn(a, b):
        return matriz_km[indice_por_coord[a]][indice_por_coord[b]]

    return distancia_fn


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
    orden_original = [p.id for p in con_coordenadas]

    # Distancia real de calle (OSRM) si está disponible; si no, línea recta.
    distancia_fn = obtener_distancia_fn_red_vial(origen, puntos)
    orden_optimizado = optimizar_ruta(origen, puntos, distancia_fn)

    km_antes = _distancia_total(origen, puntos, orden_original, distancia_fn)
    km_despues = _distancia_total(origen, puntos, orden_optimizado, distancia_fn)

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

    ahorro_km = max(km_antes - km_despues, 0.0)
    ahorro_pct = (ahorro_km / km_antes * 100) if km_antes > 0 else 0.0

    return {
        "optimizado": True,
        "cantidad": len(con_coordenadas),
        "sin_coordenadas": [p.cliente.nombre for p in sin_coordenadas],
        "km_antes": round(km_antes, 1),
        "km_despues": round(km_despues, 1),
        "ahorro_km": round(ahorro_km, 1),
        "ahorro_pct": round(ahorro_pct, 1),
        "por_red_vial": distancia_fn is not None,
    }
