from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Empresa, PerfilUsuario, Cliente, Pedido


class CrearPedidoTests(TestCase):
    """Un pedido es solo cliente + que se despacha: sin productos ni montos."""

    def setUp(self):
        self.owner = User.objects.create_user(username="owner3", password="Segura123!")
        self.empresa = Empresa.objects.create(nombre="Empresa 3", owner=self.owner, direccion_origen="Centro")
        PerfilUsuario.objects.create(user=self.owner, rol="OWNER", empresa=self.empresa)

        self.cliente = Cliente.objects.create(
            empresa=self.empresa, rut="9-9", nombre="Cliente Pedido", direccion="Calle X"
        )
        self.client.login(username="owner3", password="Segura123!")

    def test_crear_pedido_con_cliente_y_nota(self):
        resp = self.client.post(reverse("crear_pedido"), {
            "cliente_id": self.cliente.id, "nota": "10 kg marraqueta, 2 bandejas de empanadas",
        })
        pedido = Pedido.objects.get(cliente=self.cliente)
        self.assertRedirects(resp, reverse("detalle_pedido", args=[pedido.id]))
        self.assertEqual(pedido.estado, "PENDIENTE")
        self.assertEqual(pedido.nota, "10 kg marraqueta, 2 bandejas de empanadas")
        self.assertEqual(pedido.creado_por, self.owner)

        detalle = self.client.get(reverse("detalle_pedido", args=[pedido.id]))
        self.assertContains(detalle, "10 kg marraqueta")
        self.assertNotContains(detalle, "$")

    def test_no_se_puede_crear_pedido_sin_cliente(self):
        resp = self.client.post(reverse("crear_pedido"), {"nota": "algo"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Pedido.objects.exists())

    def test_no_se_puede_crear_pedido_para_cliente_de_otra_empresa(self):
        otro_owner = User.objects.create_user(username="owner_otro", password="Segura123!")
        otra = Empresa.objects.create(nombre="Otra", owner=otro_owner)
        cliente_ajeno = Cliente.objects.create(empresa=otra, nombre="Ajeno", direccion="D")

        resp = self.client.post(reverse("crear_pedido"), {"cliente_id": cliente_ajeno.id})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Pedido.objects.exists())

    def test_no_se_puede_crear_pedido_para_cliente_inactivo(self):
        self.cliente.activo = False
        self.cliente.save()
        resp = self.client.post(reverse("crear_pedido"), {"cliente_id": self.cliente.id})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Pedido.objects.exists())
