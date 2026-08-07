from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Empresa, PerfilUsuario, SolicitudCuenta


def datos_solicitud(**overrides):
    datos = {
        "nombre_empresa": "Panadería Nueva",
        "nombre_contacto": "Juanita Pérez",
        "email_contacto": "juanita@nueva.cl",
        "telefono_contacto": "+56911112222",
        "rubro": "Panadería",
        "plan_solicitado": "PRO",
        "mensaje": "Repartimos 30 pedidos diarios.",
    }
    datos.update(overrides)
    return datos


class SolicitarCuentaPublicoTests(TestCase):
    def test_crea_solicitud_y_redirige_a_confirmacion(self):
        resp = self.client.post(reverse("solicitar_cuenta"), datos_solicitud())
        self.assertEqual(resp.status_code, 302)

        solicitud = SolicitudCuenta.objects.get(nombre_empresa="Panadería Nueva")
        self.assertEqual(solicitud.estado, "NUEVA")
        self.assertEqual(solicitud.plan_solicitado, "PRO")

        resp = self.client.get(resp.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, solicitud.codigo_referencia)

    def test_plan_invalido_no_crea_solicitud(self):
        resp = self.client.post(reverse("solicitar_cuenta"), datos_solicitud(plan_solicitado="ORO"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(SolicitudCuenta.objects.filter(nombre_empresa="Panadería Nueva").exists())

    def test_campos_obligatorios_faltantes_no_crea_solicitud(self):
        resp = self.client.post(reverse("solicitar_cuenta"), datos_solicitud(nombre_contacto=""))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(SolicitudCuenta.objects.exists())


class PanelStaffAccesoTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner_tenant", password="Segura123!")
        empresa = Empresa.objects.create(nombre="Empresa Cliente", owner=self.owner, direccion_origen="Centro")
        PerfilUsuario.objects.create(user=self.owner, rol="OWNER", empresa=empresa)

        self.staff = User.objects.create_user(username="staff_logivisir", password="Segura123!", is_staff=True)

        self.solicitud = SolicitudCuenta.objects.create(**datos_solicitud())

    def test_tenant_owner_no_puede_ver_panel_staff(self):
        self.client.login(username="owner_tenant", password="Segura123!")
        resp = self.client.get(reverse("lista_solicitudes"))
        self.assertEqual(resp.status_code, 302)  # redirigido a login, no es staff

    def test_staff_si_puede_ver_panel(self):
        self.client.login(username="staff_logivisir", password="Segura123!")
        resp = self.client.get(reverse("lista_solicitudes"))
        self.assertEqual(resp.status_code, 200)


class AprovisionarCuentaTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="staff2", password="Segura123!", is_staff=True)
        self.solicitud = SolicitudCuenta.objects.create(**datos_solicitud())
        self.client.login(username="staff2", password="Segura123!")

    def test_no_se_puede_crear_cuenta_sin_pago_validado(self):
        resp = self.client.post(reverse("crear_cuenta_solicitud", args=[self.solicitud.id]))
        self.assertEqual(resp.status_code, 302)
        self.solicitud.refresh_from_db()
        self.assertIsNone(self.solicitud.empresa_creada)

    def test_flujo_completo_validar_y_crear_cuenta(self):
        self.client.post(reverse("marcar_pago_validado", args=[self.solicitud.id]))
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, "PAGO_VALIDADO")

        self.client.post(reverse("crear_cuenta_solicitud", args=[self.solicitud.id]))
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, "CUENTA_CREADA")
        self.assertIsNotNone(self.solicitud.empresa_creada)

        empresa = self.solicitud.empresa_creada
        self.assertEqual(empresa.nombre, "Panadería Nueva")
        self.assertEqual(empresa.owner.email, "juanita@nueva.cl")

        perfil = PerfilUsuario.objects.get(empresa=empresa)
        self.assertEqual(perfil.rol, "OWNER")
        self.assertTrue(perfil.debe_cambiar_password)

    def test_crear_cuenta_es_idempotente(self):
        self.client.post(reverse("marcar_pago_validado", args=[self.solicitud.id]))
        self.client.post(reverse("crear_cuenta_solicitud", args=[self.solicitud.id]))
        self.solicitud.refresh_from_db()
        empresa_id_original = self.solicitud.empresa_creada_id
        usuarios_antes = User.objects.count()

        # Segundo click no debe crear una segunda Empresa/User
        self.client.post(reverse("crear_cuenta_solicitud", args=[self.solicitud.id]))
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.empresa_creada_id, empresa_id_original)
        self.assertEqual(User.objects.count(), usuarios_antes)

    def test_username_no_choca_con_uno_existente(self):
        User.objects.create_user(username="panaderianueva", password="x")
        self.client.post(reverse("marcar_pago_validado", args=[self.solicitud.id]))
        self.client.post(reverse("crear_cuenta_solicitud", args=[self.solicitud.id]))

        self.solicitud.refresh_from_db()
        nuevo_username = self.solicitud.empresa_creada.owner.username
        self.assertNotEqual(nuevo_username, "panaderianueva")
        self.assertTrue(User.objects.filter(username=nuevo_username).exists())


class CambioPasswordObligatorioTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="nueva_cuenta", password="TempPass123!")
        empresa = Empresa.objects.create(nombre="Empresa X", owner=self.user, direccion_origen="Centro")
        self.perfil = PerfilUsuario.objects.create(
            user=self.user, rol="OWNER", empresa=empresa, debe_cambiar_password=True,
        )

    def test_login_redirige_a_cambio_de_password(self):
        resp = self.client.post(reverse("login"), {"username": "nueva_cuenta", "password": "TempPass123!"})
        self.assertRedirects(resp, reverse("cambiar_password_obligatorio"))

    def test_cambio_exitoso_no_desloguea_y_actualiza_perfil(self):
        self.client.login(username="nueva_cuenta", password="TempPass123!")

        resp = self.client.post(reverse("cambiar_password_obligatorio"), {
            "nueva_password": "UnaClaveNuevaSegura9!",
            "confirmar_password": "UnaClaveNuevaSegura9!",
        })
        self.assertEqual(resp.status_code, 302)

        self.perfil.refresh_from_db()
        self.assertFalse(self.perfil.debe_cambiar_password)

        # La sesion debe seguir autenticada (update_session_auth_hash aplicado)
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)

    def test_passwords_no_coinciden(self):
        self.client.login(username="nueva_cuenta", password="TempPass123!")
        resp = self.client.post(reverse("cambiar_password_obligatorio"), {
            "nueva_password": "UnaClaveNuevaSegura9!",
            "confirmar_password": "OtraDistinta9!",
        })
        self.assertEqual(resp.status_code, 200)
        self.perfil.refresh_from_db()
        self.assertTrue(self.perfil.debe_cambiar_password)
