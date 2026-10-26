"""
Panel del equipo LogiVisir: administra a las empresas que contratan el
servicio (ficha, estado, usuarios) sin poder ver los datos del negocio de
cada empresa (clientes, rutas, pedidos, choferes).
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Cliente, Empresa, PerfilUsuario, Pedido


class PanelStaffEmpresasTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="staff_lv", password="Segura123!", is_staff=True)
        self.owner = User.objects.create_user(
            username="duena_panaderia", password="Segura123!", email="duena@panaderia.cl",
        )
        self.empresa = Empresa.objects.create(nombre="Panadería Cliente", owner=self.owner)
        PerfilUsuario.objects.create(user=self.owner, rol="OWNER", empresa=self.empresa)
        cliente = Cliente.objects.create(
            empresa=self.empresa, nombre="Almacén Confidencial", direccion="Calle Privada 123",
        )
        Pedido.objects.create(empresa=self.empresa, cliente=cliente, nota="Pedido confidencial")

    def _login_staff(self):
        self.client.login(username="staff_lv", password="Segura123!")

    def test_staff_ve_la_lista_de_empresas_sin_sus_clientes(self):
        self._login_staff()
        resp = self.client.get(reverse("staff_lista_empresas"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Panadería Cliente")
        self.assertNotContains(resp, "Almacén Confidencial")

    def test_ficha_de_empresa_no_muestra_clientes_ni_pedidos(self):
        self._login_staff()
        resp = self.client.get(reverse("staff_detalle_empresa", args=[self.empresa.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "duena_panaderia")
        self.assertNotContains(resp, "Almacén Confidencial")
        self.assertNotContains(resp, "Calle Privada")
        self.assertNotContains(resp, "Pedido confidencial")

    def test_staff_no_puede_entrar_a_las_vistas_de_la_empresa(self):
        self._login_staff()
        for nombre in ("lista_clientes", "lista_rutas", "lista_pedidos", "analitica"):
            resp = self.client.get(reverse(nombre))
            self.assertNotEqual(resp.status_code, 200, nombre)

    def test_admin_de_django_no_expone_datos_de_las_empresas(self):
        superuser = User.objects.create_superuser(username="root_lv", password="Segura123!")
        self.client.force_login(superuser)
        for modelo in ("cliente", "ruta", "pedido", "chofer", "paradaruta"):
            resp = self.client.get(f"/admin/core/{modelo}/")
            self.assertEqual(resp.status_code, 404, modelo)
        self.assertEqual(self.client.get("/admin/core/empresa/").status_code, 200)

    def test_usuario_de_empresa_no_entra_al_panel_staff(self):
        self.client.login(username="duena_panaderia", password="Segura123!")
        resp = self.client.get(reverse("staff_lista_empresas"))
        self.assertEqual(resp.status_code, 302)

    def test_staff_crea_usuario_administrador_para_la_empresa(self):
        self._login_staff()
        resp = self.client.post(
            reverse("staff_crear_usuario_empresa", args=[self.empresa.id]),
            {"rol": "ADMIN", "nombre": "Pedro Admin", "email": "pedro@panaderia.cl"},
        )
        self.assertRedirects(resp, reverse("staff_detalle_empresa", args=[self.empresa.id]))
        perfil = PerfilUsuario.objects.get(user__email="pedro@panaderia.cl")
        self.assertEqual(perfil.empresa, self.empresa)
        self.assertEqual(perfil.rol, "ADMIN")
        self.assertTrue(perfil.debe_cambiar_password)

    def test_staff_no_puede_crear_choferes_ni_roles_invalidos(self):
        self._login_staff()
        self.client.post(
            reverse("staff_crear_usuario_empresa", args=[self.empresa.id]),
            {"rol": "CHOFER", "nombre": "X", "email": "x@x.cl"},
        )
        self.assertFalse(User.objects.filter(email="x@x.cl").exists())

    def test_restablecer_clave_obliga_a_cambiarla(self):
        self._login_staff()
        self.client.post(reverse("staff_restablecer_clave", args=[self.owner.id]))
        perfil = PerfilUsuario.objects.get(user=self.owner)
        self.assertTrue(perfil.debe_cambiar_password)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.check_password("Segura123!"))

    def test_restablecer_clave_no_aplica_a_otro_staff(self):
        otro_staff = User.objects.create_user(username="otro_staff", password="Segura123!", is_staff=True)
        self._login_staff()
        resp = self.client.post(reverse("staff_restablecer_clave", args=[otro_staff.id]))
        self.assertEqual(resp.status_code, 404)
        otro_staff.refresh_from_db()
        self.assertTrue(otro_staff.check_password("Segura123!"))

    def test_login_de_staff_lleva_al_panel_de_empresas(self):
        resp = self.client.post(reverse("login"), {"username": "staff_lv", "password": "Segura123!"})
        self.assertRedirects(resp, reverse("staff_lista_empresas"))


class SuspensionDeEmpresaTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="staff_susp", password="Segura123!", is_staff=True)
        self.owner = User.objects.create_user(username="owner_susp", password="Segura123!")
        self.empresa = Empresa.objects.create(nombre="Empresa Morosa", owner=self.owner)
        PerfilUsuario.objects.create(user=self.owner, rol="OWNER", empresa=self.empresa)

    def _suspender(self):
        self.client.login(username="staff_susp", password="Segura123!")
        self.client.post(reverse("staff_cambiar_estado_empresa", args=[self.empresa.id]))
        self.client.logout()
        self.empresa.refresh_from_db()

    def test_empresa_suspendida_no_puede_iniciar_sesion(self):
        self._suspender()
        self.assertFalse(self.empresa.activa)

        resp = self.client.post(reverse("login"), {"username": "owner_susp", "password": "Segura123!"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "suspendida")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_sesion_abierta_queda_bloqueada_al_suspender(self):
        self.client.login(username="owner_susp", password="Segura123!")
        self.empresa.activa = False
        self.empresa.save()
        resp = self.client.get(reverse("lista_clientes"))
        self.assertEqual(resp.status_code, 403)

    def test_reactivar_devuelve_el_acceso(self):
        self._suspender()
        self._suspender()  # segundo clic: reactiva
        self.assertTrue(self.empresa.activa)
        resp = self.client.post(reverse("login"), {"username": "owner_susp", "password": "Segura123!"})
        self.assertEqual(resp.status_code, 302)


class LoginNextSeguroTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user(username="owner_next", password="Segura123!")
        empresa = Empresa.objects.create(nombre="Empresa Next", owner=owner)
        PerfilUsuario.objects.create(user=owner, rol="OWNER", empresa=empresa)

    def test_next_externo_se_ignora(self):
        resp = self.client.post(
            reverse("login") + "?next=https://sitio-falso.example/",
            {"username": "owner_next", "password": "Segura123!", "next": "https://sitio-falso.example/"},
        )
        self.assertRedirects(resp, reverse("dashboard"), fetch_redirect_response=False)

    def test_next_interno_se_respeta(self):
        resp = self.client.post(
            reverse("login"),
            {"username": "owner_next", "password": "Segura123!", "next": reverse("lista_rutas")},
        )
        self.assertRedirects(resp, reverse("lista_rutas"), fetch_redirect_response=False)
