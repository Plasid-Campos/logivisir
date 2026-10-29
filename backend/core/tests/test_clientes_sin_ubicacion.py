from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Cliente, Empresa, PerfilUsuario, Pedido


class ClientesSinUbicacionTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user(username="duena_ub", password="Segura123!")
        self.empresa = Empresa.objects.create(nombre="Panadería Ubicación", owner=owner)
        PerfilUsuario.objects.create(user=owner, rol="OWNER", empresa=self.empresa)
        self.ubicado = Cliente.objects.create(
            empresa=self.empresa, nombre="Almacén Ubicado", direccion="Franklin 700", comuna="Santiago",
            latitud=-33.473014, longitud=-70.641905, geocodificado=True,
        )
        self.perdido = Cliente.objects.create(
            empresa=self.empresa, nombre="Almacén Perdido", direccion="Pasaje Sin Nombre 12", comuna="San Miguel",
        )
        self.client.login(username="duena_ub", password="Segura123!")

    def test_lista_avisa_cuantos_activos_no_estan_ubicados(self):
        resp = self.client.get(reverse("lista_clientes"))
        self.assertEqual(resp.context["activos_sin_ubicacion"], 1)
        self.assertContains(resp, "sin ubicación en el mapa")
        self.assertContains(resp, "Sin ubicación")  # badge en la fila

    def test_filtro_muestra_solo_los_sin_ubicacion(self):
        resp = self.client.get(reverse("lista_clientes") + "?ubicacion=sin")
        nombres = [c.nombre for c in resp.context["clientes"]]
        self.assertEqual(nombres, ["Almacén Perdido"])

        resp = self.client.get(reverse("lista_clientes") + "?ubicacion=con")
        self.assertEqual([c.nombre for c in resp.context["clientes"]], ["Almacén Ubicado"])

    def test_sin_clientes_perdidos_no_hay_aviso(self):
        self.perdido.delete()
        resp = self.client.get(reverse("lista_clientes"))
        self.assertNotContains(resp, "sin ubicación en el mapa")

    @patch("core.geocoding.geocodificar_direccion", return_value=(-33.5, -70.65))
    def test_boton_ubicar_reintenta_y_vuelve_a_la_lista_filtrada(self, _):
        volver = reverse("lista_clientes") + "?ubicacion=sin"
        resp = self.client.post(reverse("reubicar_cliente", args=[self.perdido.id]), {"volver": volver})
        self.assertRedirects(resp, volver, fetch_redirect_response=False)
        self.perdido.refresh_from_db()
        self.assertTrue(self.perdido.geocodificado)

    def test_ubicar_no_redirige_fuera_del_sitio(self):
        with patch("core.geocoding.geocodificar_direccion", return_value=None):
            resp = self.client.post(
                reverse("reubicar_cliente", args=[self.perdido.id]), {"volver": "https://sitio-falso.example/"},
            )
        self.assertRedirects(resp, reverse("lista_clientes"), fetch_redirect_response=False)

    @patch("core.geocoding.geocodificar_direccion", side_effect=[(-33.5, -70.65), None])
    def test_lote_reintenta_los_activos_sin_ubicacion(self, geocodificar):
        otro = Cliente.objects.create(empresa=self.empresa, nombre="Otro Perdido", direccion="X 1")
        Cliente.objects.create(empresa=self.empresa, nombre="Inactivo Perdido", direccion="Y 2", activo=False)

        with patch("time.sleep"):
            resp = self.client.post(reverse("reubicar_clientes_lote"), follow=True)

        self.assertEqual(geocodificar.call_count, 2)  # el inactivo no se toca
        self.perdido.refresh_from_db()
        otro.refresh_from_db()
        self.assertTrue(self.perdido.geocodificado)
        self.assertFalse(otro.geocodificado)
        self.assertContains(resp, "1 quedaron en el mapa")

    def test_coordenadas_pegadas_en_editar_fijan_la_ubicacion(self):
        datos = {
            "nombre": self.perdido.nombre, "direccion": self.perdido.direccion, "comuna": self.perdido.comuna,
            "ciudad": "", "activo": "on", "coordenadas": "-33.5012, -70.6564",
        }
        resp = self.client.post(reverse("editar_cliente", args=[self.perdido.id]), datos)
        self.perdido.refresh_from_db()
        self.assertTrue(self.perdido.geocodificado)
        self.assertAlmostEqual(self.perdido.latitud, -33.5012)
        self.assertContains(resp, "openstreetmap.org/export/embed.html")

    def test_coordenadas_invalidas_en_editar_no_guardan_nada(self):
        datos = {
            "nombre": "Nombre cambiado", "direccion": self.perdido.direccion, "comuna": "",
            "activo": "on", "coordenadas": "40.4, -3.7",
        }
        resp = self.client.post(reverse("editar_cliente", args=[self.perdido.id]), datos)
        self.assertContains(resp, "no están en Chile")
        self.perdido.refresh_from_db()
        self.assertEqual(self.perdido.nombre, "Almacén Perdido")

    def test_no_puede_reubicar_clientes_de_otra_empresa(self):
        otro_owner = User.objects.create_user(username="otro_ub", password="Segura123!")
        otra = Empresa.objects.create(nombre="Otra", owner=otro_owner)
        ajeno = Cliente.objects.create(empresa=otra, nombre="Ajeno", direccion="Z 1")
        resp = self.client.post(reverse("reubicar_cliente", args=[ajeno.id]))
        self.assertEqual(resp.status_code, 404)

    def test_eliminar_cliente_con_pedidos_lo_desactiva_en_vez_de_fallar(self):
        Pedido.objects.create(empresa=self.empresa, cliente=self.ubicado, estado="ENTREGADO")
        resp = self.client.post(reverse("eliminar_cliente", args=[self.ubicado.id]))
        self.assertRedirects(resp, reverse("lista_clientes"))
        self.ubicado.refresh_from_db()
        self.assertFalse(self.ubicado.activo)

    def test_eliminar_cliente_sin_historial_lo_borra(self):
        self.client.post(reverse("eliminar_cliente", args=[self.perdido.id]))
        self.assertFalse(Cliente.objects.filter(id=self.perdido.id).exists())
