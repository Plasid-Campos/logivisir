from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.analytics import resumen_despachos
from core.models import (
    Empresa, PerfilUsuario, Chofer, Cliente, Pedido, Ruta, ParadaRuta,
)


class SincronizacionPedidoEntregaTests(TestCase):
    """
    Regresion: al marcar una parada como entregada, el pedido asociado debe
    pasar a ENTREGADO para que la analitica lo cuente como despacho.
    """

    def setUp(self):
        self.owner = User.objects.create_user(username="owner_ent", password="Segura123!")
        self.empresa = Empresa.objects.create(nombre="Empresa Entregas", owner=self.owner)
        PerfilUsuario.objects.create(user=self.owner, rol="OWNER", empresa=self.empresa)

        chofer_user = User.objects.create_user(username="chofer_ent", password="Segura123!")
        chofer_perfil = PerfilUsuario.objects.create(user=chofer_user, rol="CHOFER", empresa=self.empresa)
        self.chofer = Chofer.objects.create(perfil=chofer_perfil, rut="7-7")

        cliente = Cliente.objects.create(empresa=self.empresa, nombre="Almacén Uno", direccion="Calle 1")
        self.pedido = Pedido.objects.create(
            empresa=self.empresa, cliente=cliente, estado="ASIGNADO",
        )
        self.ruta = Ruta.objects.create(
            empresa=self.empresa, nombre="Ruta hoy", fecha=timezone.localdate(), chofer=self.chofer,
        )
        self.parada = ParadaRuta.objects.create(
            ruta=self.ruta, cliente=cliente, orden=1, pedido=self.pedido,
        )

    def _chofer_marca(self, accion, **extra):
        self.client.login(username="chofer_ent", password="Segura123!")
        datos = {"accion": accion, **extra}
        return self.client.post(reverse("chofer_marcar_parada", args=[self.parada.id]), datos)

    def test_chofer_marca_entregado_actualiza_pedido_y_despachos(self):
        self._chofer_marca("ENTREGADO")

        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, "ENTREGADO")
        self.assertEqual(resumen_despachos(self.empresa)["despachos"], 1)

    def test_chofer_revierte_entrega_devuelve_pedido_a_asignado(self):
        self._chofer_marca("ENTREGADO")
        self._chofer_marca("REVERTIR")

        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, "ASIGNADO")

    def test_no_entregado_mantiene_pedido_asignado(self):
        self._chofer_marca("NO_ENTREGADO", motivo_no_entrega="Local cerrado")

        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, "ASIGNADO")

    def test_pedido_cancelado_no_se_reactiva(self):
        self.pedido.estado = "CANCELADO"
        self.pedido.save()

        self._chofer_marca("ENTREGADO")

        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, "CANCELADO")

    def test_toggle_admin_sincroniza_pedido(self):
        self.client.login(username="owner_ent", password="Segura123!")
        url = reverse("toggle_parada", args=[self.parada.id])

        self.client.post(url)
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, "ENTREGADO")

        self.client.post(url)
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, "ASIGNADO")
