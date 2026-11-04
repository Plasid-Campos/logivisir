"""
LogiVisir como app instalable (PWA): manifiesto válido, service worker en la
raíz que no guarda datos, página sin conexión e ícono que abre a cada rol en
su pantalla.
"""
import json

from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from core.models import Chofer, Empresa, PerfilUsuario


class ManifiestoTests(TestCase):
    def test_manifiesto_cumple_lo_que_pide_el_navegador_para_instalar(self):
        resp = self.client.get("/manifest.webmanifest")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp["Content-Type"].startswith("application/manifest+json"))
        datos = json.loads(resp.content)
        self.assertEqual(datos["start_url"], reverse("app_inicio"))
        self.assertEqual(datos["display"], "standalone")
        self.assertTrue(datos["name"] and datos["short_name"])
        tamanos = {i["sizes"] for i in datos["icons"]}
        self.assertTrue({"192x192", "512x512"} <= tamanos)
        self.assertIn("maskable", {i["purpose"] for i in datos["icons"]})

    def test_los_iconos_existen(self):
        datos = json.loads(self.client.get("/manifest.webmanifest").content)
        for icono in datos["icons"]:
            ruta = icono["src"].split("/static/", 1)[1]
            self.assertIsNotNone(finders.find(ruta), ruta)

    def test_todas_las_paginas_enlazan_el_manifiesto(self):
        for nombre in ("home", "solicitar_cuenta"):
            self.assertContains(self.client.get(reverse(nombre)), 'rel="manifest"', msg_prefix=nombre)


class ServiceWorkerTests(TestCase):
    def test_se_sirve_desde_la_raiz_como_javascript_sin_cache(self):
        resp = self.client.get("/sw.js")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp["Content-Type"].startswith("application/javascript"))
        self.assertIn("no-cache", resp["Cache-Control"])

    def test_solo_guarda_la_pagina_sin_conexion(self):
        js = self.client.get("/sw.js").content.decode()
        self.assertIn('"/offline/"', js)
        self.assertNotIn("/chofer/", js)  # nunca deja rutas ni datos en el teléfono
        self.assertNotIn("cache.put", js)

    def test_pagina_sin_conexion_no_depende_de_internet(self):
        resp = self.client.get(reverse("pwa_offline"))
        self.assertContains(resp, "Estás sin conexión")
        self.assertNotContains(resp, "cdn.jsdelivr")
        self.assertNotContains(resp, "fonts.googleapis")


class InicioDeLaAppTests(TestCase):
    def setUp(self):
        self.dueno = User.objects.create_user("dueno_app", password="Segura123!")
        empresa = Empresa.objects.create(nombre="App SpA", owner=self.dueno)
        PerfilUsuario.objects.create(user=self.dueno, rol="OWNER", empresa=empresa)
        chofer = User.objects.create_user("chofer_app", password="Segura123!")
        perfil = PerfilUsuario.objects.create(user=chofer, rol="CHOFER", empresa=empresa)
        Chofer.objects.create(perfil=perfil)
        User.objects.create_user("equipo_app", password="Segura123!", is_staff=True)

    def test_sin_sesion_pide_entrar_y_vuelve_a_la_app(self):
        resp = self.client.get(reverse("app_inicio"))
        self.assertRedirects(resp, "/login/?next=/app/", fetch_redirect_response=False)

    def test_cada_rol_abre_su_pantalla(self):
        casos = (("chofer_app", "chofer_ruta_hoy"), ("dueno_app", "dashboard"), ("equipo_app", "staff_panel"))
        for usuario, destino in casos:
            self.client.login(username=usuario, password="Segura123!")
            resp = self.client.get(reverse("app_inicio"))
            self.assertRedirects(resp, reverse(destino), fetch_redirect_response=False, msg_prefix=usuario)
            self.client.logout()

    def test_entrar_desde_la_app_lleva_al_chofer_a_su_ruta(self):
        resp = self.client.post("/login/?next=/app/", {"username": "chofer_app", "password": "Segura123!"}, follow=True)
        self.assertEqual(resp.redirect_chain[-1][0], reverse("chofer_ruta_hoy"))

    def test_panel_del_chofer_ofrece_instalar(self):
        self.client.login(username="chofer_app", password="Segura123!")
        resp = self.client.get(reverse("chofer_ruta_hoy"))
        self.assertContains(resp, "data-instalar-app")
        self.assertContains(resp, "Instalar app")
