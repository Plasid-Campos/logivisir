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
        self.assertContains(resp, "Marca al menos un pedido")
        self.assertFalse(Ruta.objects.exists())

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
