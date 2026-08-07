from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Empresa, PerfilUsuario, Chofer, Cliente, Ruta, ParadaRuta


class AccionesDestructivasSoloPostTests(TestCase):
    """
    Antes de la refactorizacion, eliminar/desactivar/toggle se ejecutaban
    con un simple GET (disparable via CSRF/prefetch). Ahora deben rechazar
    GET con 405 y solo actuar sobre POST.
    """

    def setUp(self):
        self.owner = User.objects.create_user(username="owner1", password="Segura123!")
        self.empresa = Empresa.objects.create(nombre="Empresa 1", owner=self.owner, direccion_origen="Centro")
        PerfilUsuario.objects.create(user=self.owner, rol="OWNER", empresa=self.empresa)

        chofer_user = User.objects.create_user(username="chofer1", password="Segura123!")
        chofer_perfil = PerfilUsuario.objects.create(user=chofer_user, rol="CHOFER", empresa=self.empresa)
        self.chofer = Chofer.objects.create(perfil=chofer_perfil, rut="1-9")

        self.cliente = Cliente.objects.create(
            empresa=self.empresa, rut="11-1", nombre="Cliente", direccion="Calle 1", activo=True
        )
        self.ruta = Ruta.objects.create(
            empresa=self.empresa, nombre="Ruta", fecha="2026-01-01", chofer=self.chofer
        )
        self.parada = ParadaRuta.objects.create(ruta=self.ruta, cliente=self.cliente, orden=1)

        self.client.login(username="owner1", password="Segura123!")

    def test_get_a_eliminar_chofer_no_permitido(self):
        resp = self.client.get(reverse("eliminar_chofer", args=[self.chofer.id]))
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(User.objects.filter(username="chofer1").exists())

    def test_get_a_desactivar_cliente_no_permitido(self):
        resp = self.client.get(reverse("desactivar_cliente", args=[self.cliente.id]))
        self.assertEqual(resp.status_code, 405)
        self.cliente.refresh_from_db()
        self.assertTrue(self.cliente.activo)

    def test_get_a_eliminar_cliente_no_permitido(self):
        resp = self.client.get(reverse("eliminar_cliente", args=[self.cliente.id]))
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(Cliente.objects.filter(id=self.cliente.id).exists())

    def test_get_a_toggle_parada_no_permitido(self):
        resp = self.client.get(reverse("toggle_parada", args=[self.parada.id]))
        self.assertEqual(resp.status_code, 405)
        self.parada.refresh_from_db()
        self.assertFalse(self.parada.entregado)

    def test_get_a_eliminar_parada_no_permitido(self):
        resp = self.client.get(reverse("eliminar_parada", args=[self.parada.id]))
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(ParadaRuta.objects.filter(id=self.parada.id).exists())

    def test_post_si_desactiva_cliente(self):
        resp = self.client.post(reverse("desactivar_cliente", args=[self.cliente.id]))
        self.assertEqual(resp.status_code, 302)
        self.cliente.refresh_from_db()
        self.assertFalse(self.cliente.activo)


class ValidacionPasswordTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner2", password="Segura123!")
        self.empresa = Empresa.objects.create(nombre="Empresa 2", owner=self.owner, direccion_origen="Centro")
        PerfilUsuario.objects.create(user=self.owner, rol="OWNER", empresa=self.empresa)
        self.client.login(username="owner2", password="Segura123!")

    def test_password_debil_es_rechazada(self):
        resp = self.client.post(reverse("crear_usuario"), {
            "username": "nuevo_admin",
            "password": "1234",
            "nombre": "Nuevo",
            "apellido": "Admin",
            "rol": "ADMIN",
            "email": "nuevo@test.cl",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="nuevo_admin").exists())

    def test_password_vacia_es_rechazada(self):
        resp = self.client.post(reverse("crear_usuario"), {
            "username": "otro_admin",
            "password": "",
            "nombre": "Otro",
            "apellido": "Admin",
            "rol": "ADMIN",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="otro_admin").exists())

    def test_no_permite_crear_rol_owner(self):
        resp = self.client.post(reverse("crear_usuario"), {
            "username": "segundo_owner",
            "password": "UnaClaveBienSegura9!",
            "nombre": "Segundo",
            "apellido": "Owner",
            "rol": "OWNER",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="segundo_owner").exists())

    def test_password_valida_si_crea_usuario(self):
        resp = self.client.post(reverse("crear_usuario"), {
            "username": "admin_valido",
            "password": "UnaClaveBienSegura9!",
            "nombre": "Admin",
            "apellido": "Valido",
            "rol": "ADMIN",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(User.objects.filter(username="admin_valido").exists())
