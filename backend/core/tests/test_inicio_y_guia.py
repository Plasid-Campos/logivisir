"""
Página de inicio sin datos inventados, guía de primeros pasos del panel y
guía de uso por rol (sin abrirle vistas de empresa al equipo LogiVisir).
"""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from core import primeros_pasos
from core.models import Cliente, Empresa, PerfilUsuario


class PaginaInicioTests(TestCase):
    def test_no_muestra_contactos_ni_cifras_inventadas(self):
        resp = self.client.get(reverse("home"))
        for falso in ("1234 5678", "contacto@logivisir.com", "Coffe &amp; Tea", "+60", "-25%"):
            self.assertNotContains(resp, falso)
        self.assertContains(resp, "84,5 km")
        self.assertContains(resp, "38,3 km")

    @override_settings(CONTACTO_WHATSAPP="+56 9 8765 4321", CONTACTO_EMAIL="hola@ejemplo.cl")
    def test_muestra_contacto_configurado(self):
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, "https://wa.me/56987654321")
        self.assertContains(resp, "hola@ejemplo.cl")


class PrimerosPasosTests(TestCase):
    def setUp(self):
        self.dueno = User.objects.create_user("dueno_guia", password="Segura123!")
        self.empresa = Empresa.objects.create(nombre="Guía SpA", owner=self.dueno)
        PerfilUsuario.objects.create(user=self.dueno, rol="OWNER", empresa=self.empresa)

    def test_empresa_nueva_parte_en_cero_y_avanza_sola(self):
        guia = primeros_pasos.resumen(self.empresa)
        self.assertEqual((guia["hechos"], guia["total"], guia["siguiente"]), (0, 6, 0))
        self.empresa.latitud_origen, self.empresa.longitud_origen = -33.49, -70.64
        self.empresa.save()
        Cliente.objects.create(empresa=self.empresa, nombre="Almacén", direccion="Calle 1", comuna="San Miguel")
        guia = primeros_pasos.resumen(self.empresa)
        self.assertEqual((guia["hechos"], guia["siguiente"]), (2, 2))

    def test_panel_muestra_la_guia_mientras_no_esta_completa(self):
        self.client.login(username="dueno_guia", password="Segura123!")
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, "Primeros pasos")
        self.assertContains(resp, reverse("crear_cliente"))


class GuiaDeUsoTests(TestCase):
    def setUp(self):
        self.dueno = User.objects.create_user("dueno_ayuda", password="Segura123!")
        empresa = Empresa.objects.create(nombre="Ayuda SpA", owner=self.dueno)
        PerfilUsuario.objects.create(user=self.dueno, rol="OWNER", empresa=empresa)
        User.objects.create_user("equipo_ayuda", password="Segura123!", is_staff=True)

    def test_dueno_ve_la_guia(self):
        self.client.login(username="dueno_ayuda", password="Segura123!")
        resp = self.client.get(reverse("ayuda"))
        self.assertContains(resp, "Tu primer día, en orden")
        self.assertContains(resp, reverse("configurar_empresa"))

    def test_equipo_logivisir_va_a_su_panel(self):
        self.client.login(username="equipo_ayuda", password="Segura123!")
        self.assertRedirects(self.client.get(reverse("ayuda")), reverse("staff_panel"))

    def test_requiere_sesion(self):
        resp = self.client.get(reverse("ayuda"))
        self.assertEqual(resp.status_code, 302)
