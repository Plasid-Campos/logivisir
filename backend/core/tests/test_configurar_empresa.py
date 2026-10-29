from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Chofer, Empresa, PerfilUsuario

UBICACION_SALESIANOS = (-33.494197, -70.644544)


class ConfigurarEmpresaTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="duena_cfg", password="Segura123!")
        # Empresa recién creada por el equipo LogiVisir: sin dirección de salida
        self.empresa = Empresa.objects.create(nombre="Panadería Nueva", owner=self.owner)
        PerfilUsuario.objects.create(user=self.owner, rol="OWNER", empresa=self.empresa)
        self.client.login(username="duena_cfg", password="Segura123!")

    def _guardar(self, **extra):
        datos = {"direccion_origen": "Avenida Salesianos 768", "comuna_origen": "San Miguel", "ciudad_origen": "Santiago"}
        datos.update(extra)
        return self.client.post(reverse("configurar_empresa"), datos, follow=True)

    def test_panel_avisa_que_falta_la_direccion_de_salida(self):
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, "Falta la dirección de salida")
        self.assertContains(resp, reverse("configurar_empresa"))

    @patch("core.views.geocodificar_direccion", return_value=UBICACION_SALESIANOS)
    def test_guardar_direccion_la_ubica_en_el_mapa(self, geocodificar):
        resp = self._guardar()
        geocodificar.assert_called_once_with("Avenida Salesianos 768", "San Miguel", "Santiago")

        self.empresa.refresh_from_db()
        self.assertEqual((self.empresa.latitud_origen, self.empresa.longitud_origen), UBICACION_SALESIANOS)
        self.assertContains(resp, "-33.494197, -70.644544")  # con punto, no coma decimal
        self.assertContains(resp, "openstreetmap.org/export/embed.html")
        self.assertNotContains(self.client.get(reverse("dashboard")), "Falta la dirección de salida")

    @patch("core.views.geocodificar_direccion")
    def test_coordenadas_pegadas_desde_google_maps_tienen_prioridad(self, geocodificar):
        self._guardar(coordenadas="-33.4950, -70.6450")
        geocodificar.assert_not_called()
        self.empresa.refresh_from_db()
        self.assertAlmostEqual(self.empresa.latitud_origen, -33.4950)
        self.assertAlmostEqual(self.empresa.longitud_origen, -70.6450)

    @patch("core.views.geocodificar_direccion")
    def test_coordenadas_fuera_de_chile_o_invertidas_se_rechazan(self, geocodificar):
        for texto in ("-70.6450, -33.4950", "40.4, -3.7", "hola", "-33.49"):
            resp = self._guardar(coordenadas=texto)
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "alert-danger")
        self.empresa.refresh_from_db()
        self.assertIsNone(self.empresa.latitud_origen)
        self.assertIsNone(self.empresa.direccion_origen)

    @patch("core.views.geocodificar_direccion", return_value=None)
    def test_direccion_que_no_se_encuentra_se_guarda_pero_avisa(self, _):
        resp = self._guardar(direccion_origen="Calle Inventada 99999")
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.direccion_origen, "Calle Inventada 99999")
        self.assertIsNone(self.empresa.latitud_origen)
        self.assertContains(resp, "no pudimos ubicarla")

    @patch("core.views.geocodificar_direccion", return_value=UBICACION_SALESIANOS)
    def test_guardar_sin_cambios_no_vuelve_a_buscar_la_direccion(self, geocodificar):
        self._guardar()
        self._guardar()
        self.assertEqual(geocodificar.call_count, 1)

    def test_direccion_y_comuna_son_obligatorias(self):
        resp = self._guardar(direccion_origen="", comuna_origen="")
        self.assertContains(resp, "obligatorias")

    @patch("core.views.geocodificar_direccion", return_value=UBICACION_SALESIANOS)
    def test_administrador_tambien_puede_configurarla(self, _):
        admin = User.objects.create_user(username="admin_cfg", password="Segura123!")
        PerfilUsuario.objects.create(user=admin, rol="ADMIN", empresa=self.empresa)
        self.client.login(username="admin_cfg", password="Segura123!")
        self._guardar()
        self.empresa.refresh_from_db()
        self.assertIsNotNone(self.empresa.latitud_origen)

    def test_chofer_no_puede_entrar(self):
        user = User.objects.create_user(username="chofer_cfg", password="Segura123!")
        perfil = PerfilUsuario.objects.create(user=user, rol="CHOFER", empresa=self.empresa)
        Chofer.objects.create(perfil=perfil, rut="9-9")
        self.client.login(username="chofer_cfg", password="Segura123!")
        self.assertEqual(self.client.get(reverse("configurar_empresa")).status_code, 302)

    @patch("core.views.geocodificar_direccion", return_value=UBICACION_SALESIANOS)
    def test_solo_cambia_la_empresa_propia(self, _):
        otro = User.objects.create_user(username="otro_cfg", password="Segura123!")
        otra = Empresa.objects.create(nombre="Otra", owner=otro, direccion_origen="Original 1")
        self._guardar()
        otra.refresh_from_db()
        self.assertEqual(otra.direccion_origen, "Original 1")
        self.assertIsNone(otra.latitud_origen)
