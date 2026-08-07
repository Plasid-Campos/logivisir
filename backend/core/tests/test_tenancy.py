"""
Suite de regresion para el bug mas grave encontrado en la auditoria: antes
de esta refactorizacion, cualquier OWNER/ADMIN autenticado podia ver/editar
los datos de CUALQUIER otra empresa con solo cambiar el ID en la URL
(IDOR). Estos tests crean dos empresas separadas y verifican que ninguna
vista deja cruzar datos de una a la otra.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Empresa, PerfilUsuario, Chofer, Cliente, Ruta, ParadaRuta


def crear_empresa_con_owner(nombre, username):
    user = User.objects.create_user(username=username, password="Segura123!")
    empresa = Empresa.objects.create(nombre=nombre, owner=user, direccion_origen="Centro")
    PerfilUsuario.objects.create(user=user, rol="OWNER", empresa=empresa)
    return empresa, user


def crear_chofer(empresa, username):
    user = User.objects.create_user(username=username, password="Segura123!")
    perfil = PerfilUsuario.objects.create(user=user, rol="CHOFER", empresa=empresa)
    return Chofer.objects.create(perfil=perfil, rut=f"{username}-rut")


class AislamientoEntreEmpresasTests(TestCase):
    def setUp(self):
        self.empresa_a, self.owner_a = crear_empresa_con_owner("Empresa A", "owner_a")
        self.empresa_b, self.owner_b = crear_empresa_con_owner("Empresa B", "owner_b")

        self.chofer_a = crear_chofer(self.empresa_a, "chofer_a")
        self.chofer_b = crear_chofer(self.empresa_b, "chofer_b")

        self.cliente_a = Cliente.objects.create(
            empresa=self.empresa_a, rut="1-1", nombre="Cliente A", direccion="Calle A 123"
        )
        self.cliente_b = Cliente.objects.create(
            empresa=self.empresa_b, rut="2-2", nombre="Cliente B", direccion="Calle B 456"
        )

        self.ruta_a = Ruta.objects.create(
            empresa=self.empresa_a, nombre="Ruta A", fecha="2026-01-01", chofer=self.chofer_a
        )
        self.ruta_b = Ruta.objects.create(
            empresa=self.empresa_b, nombre="Ruta B", fecha="2026-01-01", chofer=self.chofer_b
        )

        self.parada_a = ParadaRuta.objects.create(ruta=self.ruta_a, cliente=self.cliente_a, orden=1)

        self.client.login(username="owner_a", password="Segura123!")

    def test_no_puede_ver_detalle_de_ruta_ajena(self):
        resp = self.client.get(reverse("detalle_ruta", args=[self.ruta_b.id]))
        self.assertEqual(resp.status_code, 404)

    def test_no_puede_editar_chofer_ajeno(self):
        resp = self.client.get(reverse("editar_chofer", args=[self.chofer_b.id]))
        self.assertEqual(resp.status_code, 404)

    def test_no_puede_eliminar_chofer_ajeno(self):
        resp = self.client.post(reverse("eliminar_chofer", args=[self.chofer_b.id]))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(User.objects.filter(username="chofer_b").exists())

    def test_no_puede_editar_cliente_ajeno(self):
        resp = self.client.get(reverse("editar_cliente", args=[self.cliente_b.id]))
        self.assertEqual(resp.status_code, 404)

    def test_no_puede_eliminar_cliente_ajeno(self):
        resp = self.client.post(reverse("eliminar_cliente", args=[self.cliente_b.id]))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Cliente.objects.filter(id=self.cliente_b.id).exists())

    def test_no_puede_agregar_cliente_ajeno_a_ruta_propia(self):
        resp = self.client.post(
            reverse("agregar_parada", args=[self.ruta_a.id]),
            {"cliente_id": self.cliente_b.id},
        )
        # get_object_or_404_scoped debe cortar con 404 antes de crear nada
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(self.ruta_a.paradas.filter(cliente=self.cliente_b).exists())

    def test_no_puede_asignar_chofer_ajeno_a_ruta_nueva(self):
        resp = self.client.post(reverse("crear_ruta"), {
            "nombre": "Ruta con chofer ajeno",
            "fecha": "2026-01-02",
            "chofer_id": self.chofer_b.id,
        })
        self.assertEqual(resp.status_code, 200)  # vuelve al form con error, no crea la ruta
        self.assertFalse(Ruta.objects.filter(nombre="Ruta con chofer ajeno").exists())

    def test_lista_clientes_solo_muestra_los_propios(self):
        resp = self.client.get(reverse("lista_clientes"))
        nombres = [c.nombre for c in resp.context["clientes"]]
        self.assertIn("Cliente A", nombres)
        self.assertNotIn("Cliente B", nombres)

    def test_lista_rutas_solo_muestra_las_propias(self):
        resp = self.client.get(reverse("lista_rutas"))
        nombres = [r.nombre for r in resp.context["rutas"]]
        self.assertIn("Ruta A", nombres)
        self.assertNotIn("Ruta B", nombres)

    def test_toggle_parada_ajena_devuelve_404(self):
        parada_b = ParadaRuta.objects.create(ruta=self.ruta_b, cliente=self.cliente_b, orden=1)
        resp = self.client.post(reverse("toggle_parada", args=[parada_b.id]))
        self.assertEqual(resp.status_code, 404)
