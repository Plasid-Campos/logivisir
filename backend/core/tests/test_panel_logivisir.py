"""
El equipo LogiVisir ve los datos de su negocio SaaS (empresas, membresías,
uso y km ahorrados) y nunca los datos operativos de sus empresas clientes,
aunque su cuenta también figure como usuario de una de ellas.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Chofer, Cliente, Empresa, ParadaRuta, PerfilUsuario, Pedido, Ruta, SolicitudCuenta


class BaseLogiVisir(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="equipo_lv", password="Segura123!", is_staff=True)
        self.owner = User.objects.create_user(username="duena_pan", password="Segura123!", email="duena@pan.cl")
        self.empresa = Empresa.objects.create(
            nombre="Panadería Cliente", owner=self.owner, plan="PRO",
            comuna_origen="San Miguel", ciudad_origen="Santiago",
            latitud_origen=-33.49, longitud_origen=-70.64,
            suscripcion_vence=timezone.localdate() + timedelta(days=5),
        )
        PerfilUsuario.objects.create(user=self.owner, empresa=self.empresa, rol="OWNER")
        chofer_user = User.objects.create_user(username="chofer_pan", password="Segura123!")
        self.perfil_chofer = PerfilUsuario.objects.create(user=chofer_user, empresa=self.empresa, rol="CHOFER")
        self.chofer = Chofer.objects.create(perfil=self.perfil_chofer, rut="11.111.111-1")
        self.cliente = Cliente.objects.create(
            empresa=self.empresa, nombre="Almacén Confidencial", direccion="Calle Privada 123",
            latitud=-33.48, longitud=-70.65, geocodificado=True,
        )
        Pedido.objects.create(empresa=self.empresa, cliente=self.cliente, nota="Pedido confidencial")
        self.ruta = Ruta.objects.create(
            empresa=self.empresa, nombre="Ruta secreta", fecha=timezone.localdate(), chofer=self.chofer,
            km_antes=20.0, km_despues=15.5, optimizada_en=timezone.now(),
        )


class StaffSeparadoDeLasEmpresasTests(BaseLogiVisir):
    def setUp(self):
        super().setUp()
        # Cuenta mixta: es del equipo LogiVisir y además dueña de una empresa.
        self.mixta = User.objects.create_user(username="mixta", password="Segura123!", is_staff=True)
        PerfilUsuario.objects.create(user=self.mixta, empresa=self.empresa, rol="OWNER")

    def test_cuenta_mixta_entra_al_panel_de_logivisir(self):
        resp = self.client.post(reverse("login"), {"username": "mixta", "password": "Segura123!"})
        self.assertRedirects(resp, reverse("staff_panel"))

    def test_cuenta_mixta_no_ve_datos_de_la_empresa(self):
        self.client.login(username="mixta", password="Segura123!")
        for nombre in ("lista_clientes", "lista_rutas", "lista_choferes", "lista_pedidos",
                       "analitica", "configurar_empresa", "lista_usuarios"):
            resp = self.client.get(reverse(nombre))
            self.assertNotEqual(resp.status_code, 200, nombre)

    def test_dashboard_de_empresa_redirige_al_panel_de_logivisir(self):
        self.client.login(username="mixta", password="Segura123!")
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("staff_panel"))

    def test_menu_del_equipo_no_tiene_enlaces_de_empresa(self):
        self.client.login(username="mixta", password="Segura123!")
        resp = self.client.get(reverse("staff_panel"))
        self.assertContains(resp, reverse("staff_lista_empresas"))
        self.assertContains(resp, reverse("staff_usuarios"))
        for nombre in ("lista_clientes", "lista_rutas", "lista_choferes", "lista_pedidos", "configurar_empresa"):
            self.assertNotContains(resp, f'href="{reverse(nombre)}"')

    def test_ficha_avisa_que_el_dueno_es_cuenta_del_equipo(self):
        self.empresa.owner = self.mixta
        self.empresa.save()
        self.client.login(username="equipo_lv", password="Segura123!")
        resp = self.client.get(reverse("staff_detalle_empresa", args=[self.empresa.id]))
        self.assertContains(resp, "cuenta del equipo LogiVisir")

    def test_crear_dueno_reemplaza_a_la_cuenta_del_equipo(self):
        self.empresa.owner = self.mixta
        self.empresa.save()
        self.client.login(username="equipo_lv", password="Segura123!")
        self.client.post(
            reverse("staff_crear_usuario_empresa", args=[self.empresa.id]),
            {"rol": "OWNER", "nombre": "Dueña Real", "email": "duena.real@pan.cl"},
        )
        self.empresa.refresh_from_db()
        self.assertFalse(self.empresa.owner.is_staff)
        self.assertEqual(self.empresa.owner.email, "duena.real@pan.cl")


class PanelLogiVisirTests(BaseLogiVisir):
    def test_panel_muestra_empresas_membresia_y_km_sin_datos_operativos(self):
        self.client.login(username="equipo_lv", password="Segura123!")
        resp = self.client.get(reverse("staff_panel"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Panadería Cliente")
        self.assertContains(resp, "4,5 km")
        self.assertContains(resp, "Por vencer")
        self.assertContains(resp, "San Miguel, Santiago")
        for secreto in ("Almacén Confidencial", "Calle Privada", "Pedido confidencial", "Ruta secreta"):
            self.assertNotContains(resp, secreto)

    def test_usuario_de_empresa_no_entra_al_panel(self):
        self.client.login(username="duena_pan", password="Segura123!")
        self.assertEqual(self.client.get(reverse("staff_panel")).status_code, 302)

    def test_usuarios_sin_empresa_elegida_muestra_solo_totales(self):
        self.client.login(username="equipo_lv", password="Segura123!")
        resp = self.client.get(reverse("staff_usuarios"))
        self.assertContains(resp, "Panadería Cliente")
        self.assertNotContains(resp, "chofer_pan")
        self.assertNotContains(resp, "duena_pan")

    def test_usuarios_de_una_empresa_con_filtro_por_rol(self):
        otra_owner = User.objects.create_user(username="otro_dueno", password="x")
        otra = Empresa.objects.create(nombre="Otra Empresa", owner=otra_owner)
        PerfilUsuario.objects.create(user=otra_owner, empresa=otra, rol="OWNER")
        self.client.login(username="equipo_lv", password="Segura123!")
        resp = self.client.get(reverse("staff_usuarios"), {"empresa": self.empresa.id})
        self.assertContains(resp, "chofer_pan")
        self.assertContains(resp, "duena_pan")
        self.assertNotContains(resp, "otro_dueno")
        resp = self.client.get(reverse("staff_usuarios"), {"empresa": self.empresa.id, "rol": "CHOFER"})
        self.assertContains(resp, "chofer_pan")
        self.assertNotContains(resp, "duena_pan")

    def test_staff_actualiza_la_membresia(self):
        self.client.login(username="equipo_lv", password="Segura123!")
        self.client.post(
            reverse("staff_membresia_empresa", args=[self.empresa.id]),
            {"plan": "EMPRESARIAL", "suscripcion_vence": "2027-01-31"},
        )
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.plan, "EMPRESARIAL")
        self.assertEqual(str(self.empresa.suscripcion_vence), "2027-01-31")

    def test_membresia_rechaza_fecha_invalida(self):
        self.client.login(username="equipo_lv", password="Segura123!")
        self.client.post(
            reverse("staff_membresia_empresa", args=[self.empresa.id]),
            {"plan": "BASICO", "suscripcion_vence": "31-31-2027"},
        )
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.plan, "PRO")

    def test_crear_cuenta_desde_solicitud_registra_plan_y_vencimiento(self):
        sol = SolicitudCuenta.objects.create(
            nombre_empresa="Nueva Pyme", nombre_contacto="Ana", email_contacto="ana@pyme.cl",
            telefono_contacto="1", plan_solicitado="BASICO", estado="PAGO_VALIDADO",
        )
        self.client.login(username="equipo_lv", password="Segura123!")
        self.client.post(reverse("crear_cuenta_solicitud", args=[sol.id]))
        empresa = Empresa.objects.get(nombre="Nueva Pyme")
        self.assertEqual(empresa.plan, "BASICO")
        from core.membresias import sumar_meses
        self.assertEqual(empresa.suscripcion_vence, sumar_meses(timezone.localdate(), 1) - timedelta(days=1))


class FechasDeUsoTests(BaseLogiVisir):
    def test_desactivar_registra_la_fecha_y_reactivar_la_borra(self):
        self.client.login(username="duena_pan", password="Segura123!")
        url = reverse("cambiar_estado_usuario", args=[self.perfil_chofer.user_id])
        self.client.post(url)
        self.perfil_chofer.refresh_from_db()
        self.assertIsNotNone(self.perfil_chofer.desactivado_en)
        self.client.post(url)
        self.perfil_chofer.refresh_from_db()
        self.assertIsNone(self.perfil_chofer.desactivado_en)

    @override_settings(OSRM_HABILITADO=False)
    def test_optimizar_guarda_los_km_de_la_ruta(self):
        ruta = Ruta.objects.create(empresa=self.empresa, nombre="R", fecha=timezone.localdate(), chofer=self.chofer)
        otro = Cliente.objects.create(empresa=self.empresa, nombre="B", direccion="x",
                                      latitud=-33.50, longitud=-70.66, geocodificado=True)
        ParadaRuta.objects.create(ruta=ruta, cliente=otro, orden=1)
        ParadaRuta.objects.create(ruta=ruta, cliente=self.cliente, orden=2)
        self.client.login(username="duena_pan", password="Segura123!")
        self.client.post(reverse("optimizar_ruta", args=[ruta.id]))
        ruta.refresh_from_db()
        self.assertIsNotNone(ruta.km_antes)
        self.assertIsNotNone(ruta.km_despues)
        self.assertLessEqual(ruta.km_despues, ruta.km_antes)
        self.assertIsNotNone(ruta.optimizada_en)
