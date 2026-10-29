from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Cliente, Empresa, Notificacion, ParadaRuta, Pedido, PerfilUsuario, Ruta
from core.tests.test_editar_ruta import crear_chofer


class CancelarEditarPedidoTests(TestCase):
    """CU-03: corregir o cancelar un pedido antes de que se entregue."""

    def setUp(self):
        self.owner = User.objects.create_user(username="duena_pe", password="Segura123!")
        self.empresa = Empresa.objects.create(nombre="Panadería Pedidos", owner=self.owner)
        PerfilUsuario.objects.create(user=self.owner, rol="OWNER", empresa=self.empresa)
        self.almacen = Cliente.objects.create(empresa=self.empresa, nombre="Almacén Rosa", direccion="Calle 1")
        self.kiosco = Cliente.objects.create(empresa=self.empresa, nombre="Kiosco Luna", direccion="Calle 2")
        self.pedido = Pedido.objects.create(empresa=self.empresa, cliente=self.almacen, nota="10 kg marraqueta")

        self.chofer = crear_chofer(self.empresa, "marco_pe")
        self.ruta = Ruta.objects.create(
            empresa=self.empresa, nombre="Reparto mañana",
            fecha=timezone.localdate() + timedelta(days=1), chofer=self.chofer,
        )
        self.client.login(username="duena_pe", password="Segura123!")

    def _asignar(self):
        parada = ParadaRuta.objects.create(ruta=self.ruta, cliente=self.almacen, orden=1, pedido=self.pedido)
        self.pedido.estado = "ASIGNADO"
        self.pedido.save()
        return parada

    def _avisos_chofer(self):
        return Notificacion.objects.filter(usuario=self.chofer.perfil.user)

    # --- editar
    def test_pendiente_permite_cambiar_cliente_y_nota(self):
        resp = self.client.post(reverse("editar_pedido", args=[self.pedido.id]), {
            "cliente_id": self.kiosco.id, "nota": "2 bandejas de empanadas",
        })
        self.assertRedirects(resp, reverse("detalle_pedido", args=[self.pedido.id]))
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.cliente, self.kiosco)
        self.assertEqual(self.pedido.nota, "2 bandejas de empanadas")

    def test_asignado_solo_cambia_la_nota_y_avisa_al_chofer(self):
        self._asignar()
        self.client.post(reverse("editar_pedido", args=[self.pedido.id]), {
            "cliente_id": self.kiosco.id, "nota": "12 kg marraqueta",
        })
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.cliente, self.almacen)  # el cliente no cambia
        self.assertEqual(self.pedido.nota, "12 kg marraqueta")
        self.assertIn("cambió lo que se lleva", self._avisos_chofer().get().mensaje)

    def test_guardar_sin_cambiar_la_nota_no_avisa(self):
        self._asignar()
        self.client.post(reverse("editar_pedido", args=[self.pedido.id]), {"nota": self.pedido.nota})
        self.assertFalse(self._avisos_chofer().exists())

    def test_nota_demasiado_larga_no_se_guarda(self):
        resp = self.client.post(reverse("editar_pedido", args=[self.pedido.id]), {
            "cliente_id": self.almacen.id, "nota": "x" * 501,
        })
        self.assertContains(resp, "no puede superar")
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.nota, "10 kg marraqueta")

    def test_entregado_no_se_puede_editar(self):
        self.pedido.estado = "ENTREGADO"
        self.pedido.save()
        resp = self.client.post(reverse("editar_pedido", args=[self.pedido.id]), {
            "cliente_id": self.kiosco.id, "nota": "otra cosa",
        })
        self.assertRedirects(resp, reverse("detalle_pedido", args=[self.pedido.id]))
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.nota, "10 kg marraqueta")

    def test_chofer_ve_lo_que_lleva_en_su_ruta(self):
        self._asignar()
        self.ruta.fecha = timezone.localdate()
        self.ruta.save()
        self.client.login(username="marco_pe", password="Segura123!")
        resp = self.client.get(reverse("chofer_ruta_hoy"))
        self.assertContains(resp, "10 kg marraqueta")

    # --- cancelar
    def test_cancelar_pendiente_guarda_quien_cuando_y_motivo(self):
        resp = self.client.post(
            reverse("cancelar_pedido", args=[self.pedido.id]), {"motivo": "Cerró por vacaciones"}, follow=True,
        )
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, "CANCELADO")
        self.assertEqual(self.pedido.cancelado_por, self.owner)
        self.assertIsNotNone(self.pedido.cancelado_en)
        self.assertContains(resp, "Cerró por vacaciones")
        self.assertNotContains(resp, "Confirmar cancelación")  # ya no se puede volver a cancelar

    def test_cancelar_asignado_quita_la_parada_y_avisa_al_chofer(self):
        self._asignar()
        self.client.post(reverse("cancelar_pedido", args=[self.pedido.id]))
        self.assertFalse(self.ruta.paradas.exists())
        self.assertIn("ya no hay que ir", self._avisos_chofer().get().mensaje)

    def test_cancelar_conserva_intentos_fallidos_como_historial(self):
        ParadaRuta.objects.create(
            ruta=self.ruta, cliente=self.almacen, orden=1, pedido=self.pedido, estado_entrega="NO_ENTREGADO",
        )
        self.pedido.estado = "ASIGNADO"
        self.pedido.save()
        self.client.post(reverse("cancelar_pedido", args=[self.pedido.id]))
        self.assertTrue(self.ruta.paradas.filter(estado_entrega="NO_ENTREGADO").exists())
        self.assertFalse(self._avisos_chofer().exists())  # no habia nada pendiente en la ruta

    def test_entregado_no_se_puede_cancelar(self):
        self.pedido.estado = "ENTREGADO"
        self.pedido.save()
        self.client.post(reverse("cancelar_pedido", args=[self.pedido.id]))
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, "ENTREGADO")

    def test_cancelar_exige_post(self):
        self.assertEqual(self.client.get(reverse("cancelar_pedido", args=[self.pedido.id])).status_code, 405)

    def test_no_puede_tocar_pedidos_de_otra_empresa(self):
        otro = User.objects.create_user(username="otro_pe", password="Segura123!")
        otra = Empresa.objects.create(nombre="Otra", owner=otro)
        ajeno = Pedido.objects.create(
            empresa=otra, cliente=Cliente.objects.create(empresa=otra, nombre="Ajeno", direccion="Z"),
        )
        self.assertEqual(self.client.post(reverse("cancelar_pedido", args=[ajeno.id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("editar_pedido", args=[ajeno.id])).status_code, 404)
        ajeno.refresh_from_db()
        self.assertEqual(ajeno.estado, "PENDIENTE")

    def test_chofer_no_puede_cancelar(self):
        self.client.login(username="marco_pe", password="Segura123!")
        self.client.post(reverse("cancelar_pedido", args=[self.pedido.id]))
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, "PENDIENTE")
