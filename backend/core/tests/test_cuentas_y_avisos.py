"""
Correo de cuentas (bienvenida, recuperación, aviso de cambio de clave, acuse
de solicitud) y avisos al chofer cuando se le asigna o cambia una ruta.
"""
import re
from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Chofer, Cliente, Empresa, Notificacion, ParadaRuta, Pedido, PerfilUsuario, Ruta,
)
from core.tests.test_solicitudes import datos_solicitud


def crear_empresa():
    owner = User.objects.create_user(username="duena", password="Segura123!", email="duena@example.com")
    empresa = Empresa.objects.create(nombre="Panadería Avisos", owner=owner, direccion_origen="Salesianos 768")
    PerfilUsuario.objects.create(user=owner, rol="OWNER", empresa=empresa)
    return empresa, owner


def crear_chofer(empresa, username="chofer_av", email="chofer@example.com"):
    user = User.objects.create_user(username=username, password="Segura123!", email=email, first_name="Marco")
    perfil = PerfilUsuario.objects.create(user=user, rol="CHOFER", empresa=empresa)
    return Chofer.objects.create(perfil=perfil, rut=f"{username}-rut")


class CrearUsuarioConCorreoTests(TestCase):
    def setUp(self):
        self.empresa, self.owner = crear_empresa()
        self.client.login(username="duena", password="Segura123!")

    def _crear(self, **extra):
        datos = {
            "username": "nuevo_admin", "password": "UnaClaveBienSegura9!", "nombre": "Pedro",
            "apellido": "Admin", "rol": "ADMIN", "email": "pedro@example.com",
        }
        datos.update(extra)
        return self.client.post(reverse("crear_usuario"), datos)

    def test_correo_es_obligatorio(self):
        self._crear(email="")
        self.assertFalse(User.objects.filter(username="nuevo_admin").exists())

    def test_correo_repetido_se_rechaza(self):
        self._crear(email="DUENA@example.com")
        self.assertFalse(User.objects.filter(username="nuevo_admin").exists())

    def test_usuario_nuevo_recibe_bienvenida_y_debe_cambiar_la_clave(self):
        self._crear()
        perfil = PerfilUsuario.objects.get(user__username="nuevo_admin")
        self.assertTrue(perfil.debe_cambiar_password)

        self.assertEqual(len(mail.outbox), 1)
        correo = mail.outbox[0]
        self.assertEqual(correo.to, ["pedro@example.com"])
        self.assertIn("nuevo_admin", correo.body)
        self.assertNotIn("UnaClaveBienSegura9!", correo.body)  # la clave nunca va por correo

    def test_chofer_nuevo_tambien_recibe_bienvenida(self):
        self.client.post(reverse("crear_chofer"), {
            "username": "chofer_nuevo", "password": "UnaClaveBienSegura9!", "nombre": "Ana",
            "apellido": "Ruiz", "email": "ana@example.com", "rut": "11.111.111-1",
        })
        perfil = PerfilUsuario.objects.get(user__username="chofer_nuevo")
        self.assertTrue(perfil.debe_cambiar_password)
        self.assertEqual(mail.outbox[0].to, ["ana@example.com"])


class RecuperarYCambiarClaveTests(TestCase):
    def setUp(self):
        self.empresa, self.owner = crear_empresa()

    def test_olvide_mi_clave_envia_enlace_y_al_usarlo_avisa_el_cambio(self):
        self.client.post(reverse("password_reset"), {"email": "duena@example.com"})
        self.assertEqual(len(mail.outbox), 1)
        enlace = re.search(r"https?://[^/]+(/reset/\S+)", mail.outbox[0].body).group(1)

        resp = self.client.get(enlace, follow=True)  # Django redirige a la URL con el token en sesión
        resp = self.client.post(resp.redirect_chain[-1][0], {
            "new_password1": "OtraClaveSegura123!", "new_password2": "OtraClaveSegura123!",
        })
        self.assertRedirects(resp, reverse("password_reset_complete"))

        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password("OtraClaveSegura123!"))
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("fue cambiada", mail.outbox[1].subject)

    def test_recuperar_clave_despeja_el_cambio_obligatorio(self):
        PerfilUsuario.objects.filter(user=self.owner).update(debe_cambiar_password=True)
        self.client.post(reverse("password_reset"), {"email": "duena@example.com"})
        enlace = re.search(r"https?://[^/]+(/reset/\S+)", mail.outbox[0].body).group(1)
        resp = self.client.get(enlace, follow=True)
        self.client.post(resp.redirect_chain[-1][0], {
            "new_password1": "OtraClaveSegura123!", "new_password2": "OtraClaveSegura123!",
        })
        self.assertFalse(PerfilUsuario.objects.get(user=self.owner).debe_cambiar_password)

    def test_correo_desconocido_no_revela_nada_ni_envia(self):
        resp = self.client.post(reverse("password_reset"), {"email": "nadie@example.com"})
        self.assertRedirects(resp, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_cambio_voluntario_de_clave_avisa_por_correo(self):
        self.client.login(username="duena", password="Segura123!")
        resp = self.client.post(reverse("cambiar_password"), {
            "old_password": "Segura123!",
            "new_password1": "NuevaClaveSegura456!", "new_password2": "NuevaClaveSegura456!",
        })
        self.assertRedirects(resp, reverse("dashboard"))
        self.assertEqual(mail.outbox[0].to, ["duena@example.com"])
        # la sesión sigue abierta después del cambio
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_cambio_obligatorio_tambien_avisa(self):
        PerfilUsuario.objects.filter(user=self.owner).update(debe_cambiar_password=True)
        self.client.login(username="duena", password="Segura123!")
        self.client.post(reverse("cambiar_password_obligatorio"), {
            "nueva_password": "NuevaClaveSegura456!", "confirmar_password": "NuevaClaveSegura456!",
        })
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("fue cambiada", mail.outbox[0].subject)


class AcuseDeSolicitudTests(TestCase):
    def test_prospecto_recibe_correo_con_codigo(self):
        self.client.post(reverse("solicitar_cuenta"), datos_solicitud())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("SOL-", mail.outbox[0].subject)


class AvisosDeRutaAlChoferTests(TestCase):
    def setUp(self):
        self.empresa, self.owner = crear_empresa()
        self.chofer = crear_chofer(self.empresa)
        self.usuario_chofer = self.chofer.perfil.user
        self.manana = timezone.localdate() + timedelta(days=1)
        self.client.login(username="duena", password="Segura123!")

    def _crear_ruta(self):
        self.client.post(reverse("crear_ruta"), {
            "nombre": "Reparto mañana", "fecha": self.manana.isoformat(), "chofer_id": self.chofer.id,
        })
        return Ruta.objects.get(nombre="Reparto mañana")

    def _agregar(self, ruta, nombre):
        cliente = Cliente.objects.create(empresa=self.empresa, nombre=nombre, direccion="Calle 1")
        self.client.post(reverse("agregar_parada", args=[ruta.id]), {"cliente_id": cliente.id})

    def test_crear_ruta_avisa_al_chofer_en_la_app_y_por_correo(self):
        ruta = self._crear_ruta()
        aviso = Notificacion.objects.get(usuario=self.usuario_chofer)
        self.assertEqual(aviso.tipo, "RUTA_ASIGNADA")
        self.assertFalse(aviso.leida)
        self.assertIn(f"fecha={self.manana.isoformat()}", aviso.url)

        self.assertEqual(mail.outbox[0].to, ["chofer@example.com"])
        self.assertIn(f"fecha={self.manana.isoformat()}", mail.outbox[0].body)
        self.assertEqual(ruta.chofer, self.chofer)

    def test_armar_la_ruta_parada_por_parada_no_llena_la_campana(self):
        ruta = self._crear_ruta()
        for nombre in ("Almacén 1", "Almacén 2", "Almacén 3"):
            self._agregar(ruta, nombre)

        avisos = Notificacion.objects.filter(usuario=self.usuario_chofer)
        self.assertEqual(avisos.count(), 1)
        self.assertIn("3 paradas", avisos.first().mensaje)

    def test_cambio_despues_de_leer_genera_un_aviso_nuevo(self):
        ruta = self._crear_ruta()
        Notificacion.objects.filter(usuario=self.usuario_chofer).update(leida=True)
        self._agregar(ruta, "Almacén tarde")

        nuevo = Notificacion.objects.get(usuario=self.usuario_chofer, leida=False)
        self.assertEqual(nuevo.tipo, "RUTA_ACTUALIZADA")
        self.assertIn("Almacén tarde", nuevo.mensaje)

    def test_chofer_ve_la_campana_y_abrir_el_aviso_lo_lleva_a_su_ruta(self):
        ruta = self._crear_ruta()
        self._agregar(ruta, "Almacén 1")
        aviso = Notificacion.objects.get(usuario=self.usuario_chofer)

        self.client.logout()
        self.client.login(username="chofer_av", password="Segura123!")
        panel = self.client.get(reverse("chofer_ruta_hoy"))
        self.assertContains(panel, "notif-badge")
        self.assertContains(panel, "Nueva ruta: Reparto mañana")

        resp = self.client.get(reverse("abrir_notificacion", args=[aviso.id]))
        self.assertRedirects(resp, aviso.url, fetch_redirect_response=False)
        aviso.refresh_from_db()
        self.assertTrue(aviso.leida)

        vista = self.client.get(aviso.url)
        self.assertEqual(vista.context["ruta"], ruta)
        self.assertFalse(vista.context["es_hoy"])
        self.assertContains(vista, "Almacén 1")

    def test_no_se_puede_abrir_el_aviso_de_otro_usuario(self):
        self._crear_ruta()
        aviso = Notificacion.objects.get(usuario=self.usuario_chofer)
        # sigue logueada la dueña, no el chofer
        resp = self.client.get(reverse("abrir_notificacion", args=[aviso.id]))
        self.assertEqual(resp.status_code, 404)

    def test_mis_rutas_lista_las_proximas(self):
        self._crear_ruta()
        self.client.logout()
        self.client.login(username="chofer_av", password="Segura123!")
        resp = self.client.get(reverse("chofer_mis_rutas"))
        self.assertContains(resp, "Reparto mañana")

    def test_marcar_todo_como_leido(self):
        self._crear_ruta()
        self.client.logout()
        self.client.login(username="chofer_av", password="Segura123!")
        self.client.post(reverse("marcar_notificaciones_leidas"))
        self.assertFalse(Notificacion.objects.filter(usuario=self.usuario_chofer, leida=False).exists())


class QuitarParadaLiberaElPedidoTests(TestCase):
    def test_pedido_vuelve_a_pendiente(self):
        empresa, owner = crear_empresa()
        chofer = crear_chofer(empresa)
        cliente = Cliente.objects.create(empresa=empresa, nombre="C", direccion="D")
        pedido = Pedido.objects.create(empresa=empresa, cliente=cliente, estado="ASIGNADO")
        ruta = Ruta.objects.create(empresa=empresa, nombre="R", fecha=timezone.localdate(), chofer=chofer)
        parada = ParadaRuta.objects.create(ruta=ruta, cliente=cliente, orden=1, pedido=pedido)

        self.client.login(username="duena", password="Segura123!")
        self.client.post(reverse("eliminar_parada", args=[parada.id]))
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, "PENDIENTE")
