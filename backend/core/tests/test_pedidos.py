from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Empresa, PerfilUsuario, Cliente, Producto, Pedido


class CarritoYPedidoTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner3", password="Segura123!")
        self.empresa = Empresa.objects.create(nombre="Empresa 3", owner=self.owner, direccion_origen="Centro")
        PerfilUsuario.objects.create(user=self.owner, rol="OWNER", empresa=self.empresa)

        self.cliente = Cliente.objects.create(
            empresa=self.empresa, rut="9-9", nombre="Cliente Carrito", direccion="Calle X"
        )
        self.producto = Producto.objects.create(
            empresa=self.empresa, nombre="Producto Test", precio=Decimal("1000.00")
        )
        self.client.login(username="owner3", password="Segura123!")

    def test_flujo_completo_carrito_a_pedido(self):
        self.client.post(reverse("seleccionar_cliente_carrito"), {"cliente_id": self.cliente.id})
        self.client.post(reverse("carrito_agregar", args=[self.producto.id]), {"cantidad": 4})

        resp = self.client.get(reverse("carrito"))
        self.assertEqual(resp.context["total"], Decimal("4000.00"))

        resp = self.client.post(reverse("carrito_confirmar"))
        self.assertEqual(resp.status_code, 302)

        pedido = Pedido.objects.get(cliente=self.cliente)
        self.assertEqual(pedido.total, Decimal("4000.00"))
        self.assertEqual(pedido.items.count(), 1)
        self.assertEqual(pedido.items.first().cantidad, 4)

        # el carrito debe quedar vacio tras confirmar
        resp = self.client.get(reverse("carrito"))
        self.assertEqual(len(resp.context["items"]), 0)

    def test_no_se_puede_confirmar_carrito_vacio(self):
        self.client.post(reverse("seleccionar_cliente_carrito"), {"cliente_id": self.cliente.id})
        resp = self.client.post(reverse("carrito_confirmar"))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Pedido.objects.filter(cliente=self.cliente).exists())
