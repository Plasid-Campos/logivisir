from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.maps import MAX_WAYPOINTS, armar_tramos
from core.models import Chofer, Cliente, Empresa, ParadaRuta, PerfilUsuario, Ruta

PANADERIA = "Avenida Salesianos 768, San Miguel, Santiago, Chile"


def params(url):
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def pendientes(n, desde=1):
    return [(i, f"Calle {i}, Santiago, Chile") for i in range(desde, desde + n)]


class ArmarTramosTests(TestCase):
    def test_ruta_sin_empezar_sale_y_vuelve_a_la_panaderia(self):
        tramos = armar_tramos(pendientes(3), origen_empresa=PANADERIA, desde_origen=True)
        self.assertEqual(len(tramos), 1)
        p = params(tramos[0].url)
        self.assertEqual(p["origin"], PANADERIA)
        self.assertEqual(p["destination"], PANADERIA)
        self.assertEqual(p["waypoints"].split("|"), [d for _, d in pendientes(3)])
        self.assertEqual(tramos[0].paradas, [1, 2, 3])
        self.assertTrue(tramos[0].vuelve_a_origen)

    def test_ruta_empezada_sale_desde_la_ubicacion_del_chofer(self):
        tramos = armar_tramos(pendientes(2, desde=4), origen_empresa=PANADERIA, desde_origen=False)
        p = params(tramos[0].url)
        self.assertNotIn("origin", p)  # Google usa "Tu ubicación"
        self.assertEqual(p["waypoints"].split("|")[0], "Calle 4, Santiago, Chile")
        self.assertEqual(p["destination"], PANADERIA)
        self.assertEqual(tramos[0].sale_de, "ubicacion")

    def test_ningun_enlace_pasa_el_limite_de_google_y_no_se_pierden_paradas(self):
        lista = pendientes(25)
        tramos = armar_tramos(lista, origen_empresa=PANADERIA, desde_origen=True)

        visitadas = []
        for tramo in tramos:
            p = params(tramo.url)
            intermedias = p["waypoints"].split("|") if "waypoints" in p else []
            self.assertLessEqual(len(intermedias), MAX_WAYPOINTS)
            visitadas += intermedias + [p["destination"]]

        # todas las paradas, en orden, y al final el regreso a la panadería
        self.assertEqual(visitadas, [d for _, d in lista] + [PANADERIA])

    def test_cada_tramo_parte_donde_termino_el_anterior(self):
        tramos = armar_tramos(pendientes(15), origen_empresa=PANADERIA, desde_origen=True)
        self.assertEqual(len(tramos), 2)
        fin_primero = params(tramos[0].url)["destination"]
        self.assertEqual(params(tramos[1].url)["origin"], fin_primero)
        self.assertEqual(tramos[1].sale_de, "parada")
        self.assertEqual(tramos[0].paradas, list(range(1, 11)))
        self.assertEqual(tramos[1].paradas, list(range(11, 16)))

    def test_sin_pendientes_solo_queda_volver_a_la_panaderia(self):
        tramos = armar_tramos([], origen_empresa=PANADERIA, desde_origen=False)
        self.assertEqual(len(tramos), 1)
        self.assertEqual(tramos[0].cantidad_paradas, 0)
        self.assertEqual(params(tramos[0].url)["destination"], PANADERIA)

    def test_empresa_sin_direccion_no_inventa_un_origen(self):
        tramos = armar_tramos(pendientes(2), origen_empresa=None, desde_origen=True)
        p = params(tramos[0].url)
        self.assertNotIn("origin", p)
        self.assertEqual(p["destination"], "Calle 2, Santiago, Chile")
        self.assertFalse(tramos[0].vuelve_a_origen)


class PanelChoferNavegacionTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user(username="owner_nav", password="Segura123!")
        self.empresa = Empresa.objects.create(
            nombre="Panadería Nav", owner=owner,
            direccion_origen="Avenida Salesianos 768", comuna_origen="San Miguel", ciudad_origen="Santiago",
        )
        PerfilUsuario.objects.create(user=owner, rol="OWNER", empresa=self.empresa)
        chofer_user = User.objects.create_user(username="chofer_nav", password="Segura123!")
        perfil = PerfilUsuario.objects.create(user=chofer_user, rol="CHOFER", empresa=self.empresa)
        self.chofer = Chofer.objects.create(perfil=perfil, rut="3-3")
        self.ruta = Ruta.objects.create(
            empresa=self.empresa, nombre="Hoy", fecha=timezone.localdate(), chofer=self.chofer,
        )

    def _crear_paradas(self, n):
        paradas = []
        for i in range(1, n + 1):
            cliente = Cliente.objects.create(
                empresa=self.empresa, nombre=f"Cliente {i}", direccion=f"Calle {i}", comuna="San Miguel",
            )
            paradas.append(ParadaRuta.objects.create(ruta=self.ruta, cliente=cliente, orden=i))
        return paradas

    def _tramos(self):
        self.client.login(username="chofer_nav", password="Segura123!")
        return self.client.get(reverse("chofer_ruta_hoy")).context["maps_tramos"]

    def test_antes_de_salir_la_ruta_parte_en_la_panaderia(self):
        self._crear_paradas(3)
        tramos = self._tramos()
        p = params(tramos[0].url)
        self.assertIn("Salesianos 768", p["origin"])
        self.assertIn("Salesianos 768", p["destination"])

    def test_con_entregas_hechas_solo_navega_lo_que_falta(self):
        paradas = self._crear_paradas(10)
        for parada in paradas[:3]:
            parada.estado_entrega = "ENTREGADO"
            parada.save()

        tramos = self._tramos()
        p = params(tramos[0].url)
        self.assertNotIn("origin", p)
        self.assertNotIn("Calle 1,", p.get("waypoints", ""))
        self.assertTrue(p["waypoints"].startswith("Calle 4,"))
        self.assertEqual(tramos[0].paradas, [4, 5, 6, 7, 8, 9, 10])
        self.assertIn("Salesianos 768", p["destination"])

    def test_no_entregada_tampoco_se_vuelve_a_navegar(self):
        paradas = self._crear_paradas(3)
        paradas[0].estado_entrega = "NO_ENTREGADO"
        paradas[0].save()
        self.assertEqual(self._tramos()[0].paradas, [2, 3])

    def test_ruta_larga_se_divide_en_tramos(self):
        self._crear_paradas(12)
        tramos = self._tramos()
        self.assertEqual(len(tramos), 2)
        self.assertEqual(tramos[0].paradas, list(range(1, 11)))
        self.assertEqual(tramos[1].paradas, [11, 12])
