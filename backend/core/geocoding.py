"""
Geocodificación de direcciones de clientes a lat/lon, usada por el
optimizador de rutas (core/optimizer.py). Provider por defecto: Nominatim
(OpenStreetMap, gratis, sin API key) — intercambiable via settings.GEOCODING_PROVIDER
sin tocar el resto del código.

Nunca debe lanzar una excepción hacia arriba: si falla (typo en la
dirección, sin internet, rate limit, etc.) simplemente devuelve None y quien
llama decide qué mostrarle al usuario. Un cliente mal geocodificado no debe
bloquear nunca su creación/edición.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
TIMEOUT_SEGUNDOS = 5


def _formatear_direccion(direccion, comuna=None, ciudad=None):
    partes = [direccion, comuna, ciudad, "Chile"]
    return ", ".join([p for p in partes if p])


def _geocodificar_nominatim(consulta):
    headers = {"User-Agent": "LogivisirSolutions/1.0 (proyecto de titulo universitario)"}
    params = {"q": consulta, "format": "json", "limit": 1, "countrycodes": "cl"}
    resp = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=TIMEOUT_SEGUNDOS)
    resp.raise_for_status()
    resultados = resp.json()
    if not resultados:
        return None
    return float(resultados[0]["lat"]), float(resultados[0]["lon"])


def geocodificar_direccion(direccion, comuna=None, ciudad=None):
    """Devuelve (lat, lon) o None si no se pudo ubicar la dirección."""
    consulta = _formatear_direccion(direccion, comuna, ciudad)
    if not consulta.strip():
        return None

    provider = getattr(settings, "GEOCODING_PROVIDER", "nominatim")
    try:
        if provider == "nominatim":
            return _geocodificar_nominatim(consulta)
        logger.warning("Proveedor de geocodificación desconocido: %s", provider)
        return None
    except Exception:
        logger.exception("Fallo al geocodificar dirección: %s", consulta)
        return None


def geocodificar_cliente(cliente):
    """
    Geocodifica un Cliente y guarda latitud/longitud/geocodificado en el
    mismo objeto. Devuelve True si se pudo ubicar, False si no.
    """
    resultado = geocodificar_direccion(cliente.direccion, cliente.comuna, cliente.ciudad)
    if resultado is None:
        cliente.latitud = None
        cliente.longitud = None
        cliente.geocodificado = False
        cliente.save(update_fields=["latitud", "longitud", "geocodificado"])
        return False

    cliente.latitud, cliente.longitud = resultado
    cliente.geocodificado = True
    cliente.save(update_fields=["latitud", "longitud", "geocodificado"])
    return True


def geocodificar_empresa(empresa):
    """Igual que geocodificar_cliente pero para el origen de una Empresa."""
    resultado = geocodificar_direccion(
        empresa.direccion_origen, empresa.comuna_origen, empresa.ciudad_origen
    )
    if resultado is None:
        return False
    empresa.latitud_origen, empresa.longitud_origen = resultado
    empresa.save(update_fields=["latitud_origen", "longitud_origen"])
    return True
