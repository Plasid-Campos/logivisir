from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Empresa, PerfilUsuario, Chofer, Cliente, Ruta


class FechaRutaTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner_fecha", password="Segura123!")
        self.empresa = Empresa.objects.create(nombre="Empresa Fecha", owner=self.owner, direccion_origen="Centro")
        PerfilUsuario.objects.create(user=self.owner, rol="OWNER", empresa=self.empresa)

        chofer_user = User.objects.create_user(username="chofer_fecha", password="Segura123!")
        chofer_perfil = PerfilUsuario.objects.create(user=chofer_user, rol="CHOFER", empresa=self.empresa)
        self.chofer = Chofer.objects.create(perfil=chofer_perfil, rut="9-1")

        self.client.login(username="owner_fecha", password="Segura123!")

    def test_no_permite_fecha_pasada(self):
        ayer = date.today() - timedelta(days=1)
        resp = self.client.post(reverse("crear_ruta"), {
            "nombre": "Ruta ayer",
            "fecha": ayer.isoformat(),
            "chofer_id": self.chofer.id,
        })
        self.assertEqual(resp.status_code, 200)  # vuelve al form con error, no redirige
        self.assertFalse(Ruta.objects.filter(nombre="Ruta ayer").exists())

    def test_permite_fecha_de_hoy(self):
        hoy = date.today()
        resp = self.client.post(reverse("crear_ruta"), {
            "nombre": "Ruta hoy",
            "fecha": hoy.isoformat(),
            "chofer_id": self.chofer.id,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Ruta.objects.filter(nombre="Ruta hoy").exists())

    def test_permite_fecha_futura(self):
        futuro = date.today() + timedelta(days=10)
        resp = self.client.post(reverse("crear_ruta"), {
            "nombre": "Ruta futura",
            "fecha": futuro.isoformat(),
            "chofer_id": self.chofer.id,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Ruta.objects.filter(nombre="Ruta futura").exists())

    def test_fecha_invalida_no_crashea(self):
        resp = self.client.post(reverse("crear_ruta"), {
            "nombre": "Ruta invalida",
            "fecha": "no-es-una-fecha",
            "chofer_id": self.chofer.id,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Ruta.objects.filter(nombre="Ruta invalida").exists())


class FiltrosListaClientesTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner_filtros", password="Segura123!")
        self.empresa = Empresa.objects.create(nombre="Empresa Filtros", owner=self.owner, direccion_origen="Centro")
        PerfilUsuario.objects.create(user=self.owner, rol="OWNER", empresa=self.empresa)

        Cliente.objects.create(
            empresa=self.empresa, nombre="La Martina", direccion="Marchant Pereira 3030",
            comuna="Ñuñoa", tipo_cliente="NORMAL", activo=True,
        )
        Cliente.objects.create(
            empresa=self.empresa, nombre="Martina Verdaguer", direccion="Los Leones 220",
            comuna="Providencia", tipo_cliente="DELIVERY", activo=True,
        )
        Cliente.objects.create(
            empresa=self.empresa, nombre="Panadería Central", direccion="Av. Principal 100",
            comuna="Santiago", tipo_cliente="NORMAL", activo=False,
        )

        self.client.login(username="owner_filtros", password="Segura123!")

    def test_busqueda_por_texto(self):
        resp = self.client.get(reverse("lista_clientes"), {"q": "martina"})
        nombres = [c.nombre for c in resp.context["clientes"]]
        self.assertCountEqual(nombres, ["La Martina", "Martina Verdaguer"])

    def test_filtro_por_comuna(self):
        resp = self.client.get(reverse("lista_clientes"), {"comuna": "Ñuñoa"})
        nombres = [c.nombre for c in resp.context["clientes"]]
        self.assertEqual(nombres, ["La Martina"])

    def test_filtro_por_tipo(self):
        resp = self.client.get(reverse("lista_clientes"), {"tipo": "DELIVERY"})
        nombres = [c.nombre for c in resp.context["clientes"]]
        self.assertEqual(nombres, ["Martina Verdaguer"])

    def test_filtro_por_estado_inactivos(self):
        resp = self.client.get(reverse("lista_clientes"), {"estado": "inactivos"})
        nombres = [c.nombre for c in resp.context["clientes"]]
        self.assertEqual(nombres, ["Panadería Central"])

    def test_sin_filtros_muestra_todos(self):
        resp = self.client.get(reverse("lista_clientes"))
        self.assertEqual(len(resp.context["clientes"]), 3)

    def test_combinar_filtros(self):
        resp = self.client.get(reverse("lista_clientes"), {"q": "martina", "tipo": "NORMAL"})
        nombres = [c.nombre for c in resp.context["clientes"]]
        self.assertEqual(nombres, ["La Martina"])
