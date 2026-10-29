from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Chofer, Empresa, PerfilUsuario, Ruta


class GestionUsuariosDuenoTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="duena_us", password="Segura123!")
        self.empresa = Empresa.objects.create(nombre="Panadería Usuarios", owner=self.owner)
        PerfilUsuario.objects.create(user=self.owner, rol="OWNER", empresa=self.empresa)

        self.admin = User.objects.create_user(
            username="admin_us", password="Segura123!", email="admin_us@example.com", first_name="Pedro",
        )
        PerfilUsuario.objects.create(user=self.admin, rol="ADMIN", empresa=self.empresa)

        self.chofer_user = User.objects.create_user(
            username="chofer_us", password="Segura123!", email="chofer_us@example.com", first_name="Marco",
        )
        perfil = PerfilUsuario.objects.create(user=self.chofer_user, rol="CHOFER", empresa=self.empresa)
        self.chofer = Chofer.objects.create(perfil=perfil, rut="1-1")

        self.client.login(username="duena_us", password="Segura123!")

    def _estado(self, user):
        return self.client.post(reverse("cambiar_estado_usuario", args=[user.id]), follow=True)

    def test_dueno_ve_todos_los_usuarios_de_su_empresa(self):
        resp = self.client.get(reverse("lista_usuarios"))
        for nombre in ("admin_us", "chofer_us", "duena_us"):
            self.assertContains(resp, nombre)

    def test_desactivar_impide_ingresar_y_explica_por_que(self):
        self._estado(self.admin)
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_active)

        self.client.logout()
        resp = self.client.post(reverse("login"), {"username": "admin_us", "password": "Segura123!"})
        self.assertContains(resp, "desactivada")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_clave_incorrecta_de_cuenta_desactivada_no_revela_el_estado(self):
        self._estado(self.admin)
        self.client.logout()
        resp = self.client.post(reverse("login"), {"username": "admin_us", "password": "otra"})
        self.assertNotContains(resp, "desactivada")
        self.assertContains(resp, "incorrectos")

    def test_desactivar_corta_la_sesion_abierta(self):
        otro = self.client_class()
        otro.login(username="admin_us", password="Segura123!")
        self.assertEqual(otro.get(reverse("dashboard")).status_code, 200)

        self._estado(self.admin)
        self.assertEqual(otro.get(reverse("dashboard")).status_code, 302)  # vuelve al login

    def test_desactivar_chofer_lo_saca_de_la_creacion_de_rutas_y_avisa_rutas_pendientes(self):
        Ruta.objects.create(
            empresa=self.empresa, nombre="Reparto jueves",
            fecha=timezone.localdate() + timedelta(days=1), chofer=self.chofer,
        )
        resp = self._estado(self.chofer_user)
        self.chofer.refresh_from_db()
        self.assertFalse(self.chofer.activo)
        self.assertContains(resp, "Reparto jueves")
        self.assertContains(resp, "Reasígnalas")

    def test_reactivar_devuelve_el_acceso(self):
        self._estado(self.chofer_user)
        self._estado(self.chofer_user)
        self.chofer_user.refresh_from_db()
        self.chofer.refresh_from_db()
        self.assertTrue(self.chofer_user.is_active)
        self.assertTrue(self.chofer.activo)

    def test_restablecer_clave_genera_temporal_obliga_cambio_y_envia_correo(self):
        resp = self.client.post(reverse("restablecer_clave_usuario", args=[self.admin.id]), follow=True)
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.check_password("Segura123!"))
        self.assertTrue(PerfilUsuario.objects.get(user=self.admin).debe_cambiar_password)
        self.assertContains(resp, "Clave temporal")
        self.assertEqual(mail.outbox[0].to, ["admin_us@example.com"])

    def test_no_puede_desactivarse_ni_restablecerse_a_si_mismo(self):
        self.assertEqual(self._estado(self.owner).status_code, 404)
        resp = self.client.post(reverse("restablecer_clave_usuario", args=[self.owner.id]))
        self.assertEqual(resp.status_code, 404)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)

    def test_no_puede_tocar_usuarios_de_otra_empresa(self):
        otro_owner = User.objects.create_user(username="otro_us", password="Segura123!")
        otra = Empresa.objects.create(nombre="Otra", owner=otro_owner)
        ajeno = User.objects.create_user(username="ajeno_us", password="Segura123!")
        PerfilUsuario.objects.create(user=ajeno, rol="ADMIN", empresa=otra)

        self.assertEqual(self._estado(ajeno).status_code, 404)
        ajeno.refresh_from_db()
        self.assertTrue(ajeno.is_active)
        self.assertNotContains(self.client.get(reverse("lista_usuarios")), "ajeno_us")

    def test_solo_el_dueno_gestiona_usuarios(self):
        self.client.login(username="admin_us", password="Segura123!")
        self.assertEqual(self.client.get(reverse("lista_usuarios")).status_code, 302)
        self.client.post(reverse("cambiar_estado_usuario", args=[self.chofer_user.id]))
        self.chofer_user.refresh_from_db()
        self.assertTrue(self.chofer_user.is_active)


class EliminarChoferConRutasTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user(username="duena_el", password="Segura123!")
        self.empresa = Empresa.objects.create(nombre="Panadería Eliminar", owner=owner)
        PerfilUsuario.objects.create(user=owner, rol="OWNER", empresa=self.empresa)
        user = User.objects.create_user(username="chofer_el", password="Segura123!")
        perfil = PerfilUsuario.objects.create(user=user, rol="CHOFER", empresa=self.empresa)
        self.chofer = Chofer.objects.create(perfil=perfil, rut="2-2")
        self.client.login(username="duena_el", password="Segura123!")

    def test_chofer_con_rutas_se_desactiva_en_vez_de_fallar(self):
        Ruta.objects.create(empresa=self.empresa, nombre="R", fecha=timezone.localdate(), chofer=self.chofer)
        resp = self.client.post(reverse("eliminar_chofer", args=[self.chofer.id]))
        self.assertRedirects(resp, reverse("lista_choferes"))
        self.chofer.refresh_from_db()
        self.assertFalse(self.chofer.activo)
        self.assertFalse(self.chofer.perfil.user.is_active)
        self.assertTrue(Ruta.objects.filter(chofer=self.chofer).exists())

    def test_chofer_sin_rutas_se_elimina(self):
        self.client.post(reverse("eliminar_chofer", args=[self.chofer.id]))
        self.assertFalse(Chofer.objects.filter(id=self.chofer.id).exists())
