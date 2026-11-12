"""
Altas rápidas: chofer con 3 datos, cliente con «Guardar y agregar otro» y la
ruta del día armada y optimizada en una sola pantalla.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Chofer, Cliente, Empresa, Notificacion, ParadaRuta, Pedido, PerfilUsuario, Ruta
from core.tests.test_editar_ruta import crear_chofer


def crear_empresa(nombre="Panadería Rápida", username="duena_rapida", origen=True):
    owner = User.objects.create_user(username=username, password="Segura123!", email=f"{username}@example.com")
    empresa = Empresa.objects.create(nombre=nombre, owner=owner, ciudad_origen="Santiago")
    if origen:
        empresa.latitud_origen, empresa.longitud_origen = -33.494197, -70.644544
        empresa.save()
    PerfilUsuario.objects.create(user=owner, rol="OWNER", empresa=empresa)
    return empresa


class ChoferRapidoTests(TestCase):
    def setUp(self):
        self.empresa = crear_empresa()
        self.client.login(username="duena_rapida", password="Segura123!")

    def test_con_tres_datos_crea_usuario_y_clave_temporal(self):
        resp = self.client.post(reverse("crear_chofer"), {
            "nombre": "Manuel", "apellido": "Castro Díaz", "email": "manuel@example.com",
        })
        chofer = Chofer.objects.get(perfil__user__email="manuel@example.com")
        self.assertEqual(chofer.perfil.user.username, "manuel.castro")
        self.assertIsNone(chofer.rut)
        self.assertTrue(chofer.perfil.debe_cambiar_password)
        self.assertEqual(chofer.perfil.empresa, self.empresa)
        self.assertContains(resp, "manuel.castro")
        self.assertContains(resp, "Clave temporal")
        # la clave se muestra en pantalla pero nunca viaja por correo
        clave = resp.context["creado"]["clave"]
        self.assertTrue(chofer.perfil.user.check_password(clave))
        self.assertEqual(mail.outbox[0].to, ["manuel@example.com"])
        self.assertNotIn(clave, mail.outbox[0].body)

    def test_nombre_repetido_genera_usuario_distinto(self):
        for correo in ("a@example.com", "b@example.com"):
            self.client.post(reverse("crear_chofer"), {"nombre": "Ana", "apellido": "Ruiz", "email": correo})
        self.assertEqual(
            sorted(User.objects.filter(username__startswith="ana.ruiz").values_list("username", flat=True)),
            ["ana.ruiz", "ana.ruiz2"],
        )

    def test_sin_correo_no_crea_nada(self):
        resp = self.client.post(reverse("crear_chofer"), {"nombre": "Ana", "apellido": "Ruiz"})
        self.assertFalse(Chofer.objects.exists())
        self.assertContains(resp, "correo es obligatorio")


@patch("core.geocoding.geocodificar_cliente", return_value=True)
class ClienteRapidoTests(TestCase):
    def setUp(self):
        self.empresa = crear_empresa()
        self.client.login(username="duena_rapida", password="Segura123!")

    def test_guardar_y_agregar_otro_recuerda_la_comuna(self, _geo):
        resp = self.client.post(reverse("crear_cliente"), {
            "nombre": "Almacén Doña Rosa", "direccion": "Gran Avenida 4400", "comuna": "San Miguel",
            "ciudad": "Santiago", "accion": "otro",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Cliente.objects.filter(empresa=self.empresa, nombre="Almacén Doña Rosa").exists())
        self.assertContains(resp, "guardado y ubicado en el mapa")
        self.assertEqual(resp.context["datos"]["comuna"], "San Miguel")
        self.assertNotIn("nombre", resp.context["datos"])

    def test_guardar_y_terminar_vuelve_a_la_lista(self, _geo):
        resp = self.client.post(reverse("crear_cliente"), {
            "nombre": "Kiosco", "direccion": "Franklin 700", "accion": "guardar",
        })
        self.assertRedirects(resp, reverse("lista_clientes"))

    def test_sin_direccion_no_guarda(self, _geo):
        self.client.post(reverse("crear_cliente"), {"nombre": "Kiosco", "direccion": "  "})
        self.assertFalse(Cliente.objects.exists())


@override_settings(OSRM_HABILITADO=False)
class ArmarRutaTests(TestCase):
    def setUp(self):
        self.empresa = crear_empresa()
        self.chofer = crear_chofer(self.empresa, "marco_armar")
        self.pedidos = []
        for i, (lat, lon) in enumerate([(-33.48, -70.64), (-33.51, -70.66), (-33.47, -70.65)]):
            cliente = Cliente.objects.create(
                empresa=self.empresa, nombre=f"Cliente {i}", direccion=f"Calle {i}", latitud=lat, longitud=lon,
            )
            self.pedidos.append(Pedido.objects.create(empresa=self.empresa, cliente=cliente))
        self.hoy = timezone.localdate()
        self.client.login(username="duena_rapida", password="Segura123!")

    def _armar(self, pedidos, **extra):
        datos = {"chofer_id": self.chofer.id, "fecha": self.hoy.isoformat(), "pedidos": [p.id for p in pedidos]}
        datos.update(extra)
        return self.client.post(reverse("armar_ruta"), datos)

    def test_crea_paradas_optimiza_y_avisa_al_chofer(self):
        resp = self._armar(self.pedidos[:2])
        ruta = Ruta.objects.get(empresa=self.empresa)
        self.assertRedirects(resp, reverse("detalle_ruta", args=[ruta.id]))
        self.assertEqual(ruta.nombre, f"Reparto {self.hoy.strftime('%d-%m')}")
        self.assertEqual(ruta.paradas.count(), 2)
        self.assertIsNotNone(ruta.optimizada_en)
        self.assertEqual(
            set(Pedido.objects.filter(id__in=[p.id for p in self.pedidos[:2]]).values_list("estado", flat=True)),
            {"ASIGNADO"},
        )
        self.assertEqual(Pedido.objects.get(id=self.pedidos[2].id).estado, "PENDIENTE")
        self.assertTrue(Notificacion.objects.filter(usuario=self.chofer.perfil.user).exists())

    def test_detalle_dice_que_ya_esta_optimizada(self):
        self._armar(self.pedidos)
        ruta = Ruta.objects.get(empresa=self.empresa)
        self.assertTrue(ruta.orden_optimizado)
        resp = self.client.get(reverse("detalle_ruta", args=[ruta.id]))
        self.assertContains(resp, "Ruta optimizada.")
        self.assertContains(resp, "Volver a optimizar")
        self.assertNotContains(resp, "aún no está optimizada")

    def test_agregar_parada_pide_optimizar_de_nuevo(self):
        self._armar(self.pedidos[:2])
        ruta = Ruta.objects.get(empresa=self.empresa)
        olvidado = Cliente.objects.create(
            empresa=self.empresa, nombre="Olvidado", direccion="Calle 9", latitud=-33.49, longitud=-70.63,
        )
        self.client.post(reverse("agregar_parada", args=[ruta.id]), {"cliente_id": olvidado.id})
        ruta.refresh_from_db()
        self.assertFalse(ruta.orden_optimizado)
        self.assertContains(
            self.client.get(reverse("detalle_ruta", args=[ruta.id])), "Agregaste paradas después de optimizar"
        )

        self.client.post(reverse("optimizar_ruta", args=[ruta.id]))
        ruta.refresh_from_db()
        self.assertTrue(ruta.orden_optimizado)

    def test_volver_a_optimizar_no_cambia_una_ruta_ya_optimizada(self):
        self._armar(self.pedidos)
        ruta = Ruta.objects.get(empresa=self.empresa)
        orden = list(ruta.paradas.order_by("orden").values_list("cliente_id", flat=True))
        km = ruta.km_despues

        resp = self.client.post(reverse("optimizar_ruta", args=[ruta.id]), follow=True)
        ruta.refresh_from_db()
        self.assertEqual(list(ruta.paradas.order_by("orden").values_list("cliente_id", flat=True)), orden)
        self.assertEqual(ruta.km_despues, km)
        self.assertContains(resp, "ya tenía el orden más corto")

    def test_no_acepta_pedidos_ni_choferes_de_otra_empresa(self):
        otra = crear_empresa("Otra SpA", "dueno_otra")
        ajeno = crear_chofer(otra, "chofer_otra")
        cliente_ajeno = Cliente.objects.create(empresa=otra, nombre="Ajeno", direccion="X")
        pedido_ajeno = Pedido.objects.create(empresa=otra, cliente=cliente_ajeno)

        self._armar(self.pedidos[:1], chofer_id=ajeno.id)
        self.assertFalse(Ruta.objects.exists())

        self._armar([pedido_ajeno])
        self.assertFalse(Ruta.objects.exists())
        self.assertEqual(Pedido.objects.get(id=pedido_ajeno.id).estado, "PENDIENTE")

    def test_sin_pedidos_marcados_no_crea_ruta(self):
        resp = self._armar([])
        self.assertContains(resp, "Agrega al menos un cliente")
        self.assertFalse(Ruta.objects.exists())

    def test_agregar_clientes_sin_pedido_crea_sus_pedidos_y_paradas(self):
        sueltos = [
            Cliente.objects.create(empresa=self.empresa, nombre="Kiosko Azul", direccion="Pio Nono 235", latitud=-33.43, longitud=-70.63),
            Cliente.objects.create(empresa=self.empresa, nombre="Almacén Sur", direccion="Gran Avenida 4400", latitud=-33.50, longitud=-70.65),
        ]
        resp = self._armar(self.pedidos[:1], agregar=[c.id for c in sueltos], **{f"lleva_{sueltos[0].id}": "2 bandejas de pan"})
        ruta = Ruta.objects.get(empresa=self.empresa)
        self.assertRedirects(resp, reverse("detalle_ruta", args=[ruta.id]))
        self.assertEqual(set(ruta.paradas.values_list("cliente__nombre", flat=True)), {"Cliente 0", "Kiosko Azul", "Almacén Sur"})
        nuevo = Pedido.objects.get(cliente=sueltos[0])
        self.assertEqual((nuevo.estado, nuevo.nota), ("ASIGNADO", "2 bandejas de pan"))
        self.assertEqual(ruta.paradas.get(cliente=sueltos[0]).pedido, nuevo)

    def test_solo_clientes_agregados_sin_pedidos_previos(self):
        Pedido.objects.all().delete()
        resp = self.client.get(reverse("armar_ruta"))
        self.assertContains(resp, "Agregar cliente")          # ya no bloquea con «No hay pedidos pendientes»
        c = Cliente.objects.get(nombre="Cliente 1")
        self._armar([], agregar=[c.id])
        self.assertEqual(Ruta.objects.get().paradas.count(), 1)

    def test_cliente_agregado_que_ya_tiene_pedido_no_se_duplica(self):
        cliente = self.pedidos[0].cliente
        self._armar(self.pedidos[:1], agregar=[cliente.id, cliente.id])
        self.assertEqual(Pedido.objects.filter(cliente=cliente).count(), 1)
        self.assertEqual(Ruta.objects.get().paradas.count(), 1)

    def test_no_agrega_clientes_de_otra_empresa_ni_inactivos(self):
        otra = crear_empresa("Otra SpA", "dueno_otra2")
        ajeno = Cliente.objects.create(empresa=otra, nombre="Ajeno", direccion="X 1")
        inactivo = Cliente.objects.create(empresa=self.empresa, nombre="Cerrado", direccion="Y 2", activo=False)
        resp = self._armar([], agregar=[ajeno.id, inactivo.id])
        self.assertContains(resp, "Agrega al menos un cliente")
        self.assertFalse(Ruta.objects.exists())
        self.assertFalse(Pedido.objects.filter(cliente__in=[ajeno, inactivo]).exists())

    def test_si_falta_el_chofer_conserva_los_clientes_agregados(self):
        c = Cliente.objects.create(empresa=self.empresa, nombre="Kiosko Rojo", direccion="Matta 820")
        resp = self._armar([], chofer_id="", agregar=[c.id], **{f"lleva_{c.id}": "pan amasado"})
        self.assertContains(resp, "Elige el chofer")
        self.assertContains(resp, "Kiosko Rojo")
        self.assertContains(resp, 'value="pan amasado"')
        self.assertFalse(Pedido.objects.filter(cliente=c).exists())

    def test_la_lista_de_clientes_para_buscar_escapa_el_html(self):
        Cliente.objects.create(empresa=self.empresa, nombre="<script>alert(1)</script>", direccion="Z 3")
        resp = self.client.get(reverse("armar_ruta"))
        self.assertNotContains(resp, "<script>alert(1)</script>")

    def test_fecha_pasada_no_se_acepta(self):
        self._armar(self.pedidos, fecha=(self.hoy - timedelta(days=1)).isoformat())
        self.assertFalse(Ruta.objects.exists())

    def test_dos_pedidos_del_mismo_cliente_dejan_uno_pendiente(self):
        extra = Pedido.objects.create(empresa=self.empresa, cliente=self.pedidos[0].cliente)
        self._armar([self.pedidos[0], extra])
        ruta = Ruta.objects.get()
        self.assertEqual(ruta.paradas.count(), 1)
        self.assertEqual(Pedido.objects.filter(estado="PENDIENTE", cliente=self.pedidos[0].cliente).count(), 1)

    def test_administrador_tambien_puede_y_chofer_no(self):
        self.client.logout()
        self.client.login(username="marco_armar", password="Segura123!")
        self.assertNotEqual(self.client.get(reverse("armar_ruta")).status_code, 200)
