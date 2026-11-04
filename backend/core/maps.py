"""
Enlaces de navegacion a Google Maps para el panel del chofer.

Google Maps acepta como maximo 9 paradas intermedias (waypoints) por enlace
cuando se abre en la app o en un computador, y solo 3 en el navegador de un
celular. Si se le mandan mas, descarta las que sobran SIN AVISAR, y el
chofer puede saltarse entregas. Por eso la ruta se parte en tramos que nunca
pasan el limite: cada tramo termina donde empieza el siguiente, y el ultimo
vuelve a la panaderia.

Ademas, el enlace solo incluye las paradas PENDIENTES y termina en la
panaderia.

Los enlaces NUNCA llevan `origin`: Google Maps solo ofrece "Iniciar" (la
navegacion paso a paso) cuando el viaje parte desde "Tu ubicacion". Con otro
punto de partida, aunque sea la panaderia donde esta el chofer, en el celular
solo muestra la vista previa. `dir_action=navigate` le pide abrir directo la
navegacion. `sale_de` queda solo para explicarle al chofer desde donde abrir
cada tramo.
"""
from dataclasses import dataclass, field
from urllib.parse import urlencode

BASE_URL = "https://www.google.com/maps/dir/?api=1"

# Paradas de clientes por enlace = 9 waypoints + el destino del tramo.
MAX_WAYPOINTS = 9


@dataclass
class Tramo:
    numero: int
    url: str
    paradas: list = field(default_factory=list)  # numeros de orden (#) de los clientes del tramo
    sale_de: str = ""        # "panaderia", "ubicacion" o "parada"
    vuelve_a_origen: bool = False

    @property
    def cantidad_paradas(self):
        return len(self.paradas)


def url_navegar(destino, intermedias=()):
    """Enlace que abre Google Maps navegando desde la ubicacion actual."""
    params = {"destination": destino, "travelmode": "driving", "dir_action": "navigate"}
    if intermedias:
        params["waypoints"] = "|".join(intermedias)
    return f"{BASE_URL}&{urlencode(params)}"


def armar_tramos(pendientes, origen_empresa=None, desde_origen=True, max_waypoints=MAX_WAYPOINTS):
    """
    pendientes: lista de (orden, direccion) de las paradas que faltan, ya
        ordenadas como las debe recorrer el chofer.
    origen_empresa: direccion de la panaderia (salida y regreso), o None si
        la empresa no la tiene configurada.
    desde_origen: True si la ruta aun no empieza (sale de la panaderia);
        False si ya hubo entregas (sale de la ubicacion actual del chofer).

    Devuelve la lista de Tramo. Cada enlace lleva a lo mas max_waypoints
    paradas intermedias, asi Google Maps nunca descarta direcciones.
    """
    puntos = [(orden, direccion) for orden, direccion in pendientes]
    if origen_empresa:
        puntos.append((None, origen_empresa))  # regreso a la panaderia
    if not puntos:
        return []

    sale_de = "panaderia" if (desde_origen and origen_empresa) else "ubicacion"

    tramos = []
    por_enlace = max_waypoints + 1  # intermedias + destino
    for inicio in range(0, len(puntos), por_enlace):
        grupo = puntos[inicio:inicio + por_enlace]
        direcciones = [d for _, d in grupo]
        tramos.append(Tramo(
            numero=len(tramos) + 1,
            url=url_navegar(direcciones[-1], direcciones[:-1]),
            paradas=[orden for orden, _ in grupo if orden is not None],
            sale_de=sale_de,
            vuelve_a_origen=grupo[-1][0] is None,
        ))
        # el siguiente tramo se abre al llegar a la ultima parada de este
        sale_de = "parada"
    return tramos
