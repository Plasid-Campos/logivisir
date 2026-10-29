from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Chofer, Cliente, Empresa, Notificacion, ParadaRuta, PerfilUsuario, Ruta


def crear_chofer(empresa, username, activo=True):
    user = User.objects.create_user(
        username=username, password="Segura123!", email=f"{username}@example.com", first_name=username.title(),
    )
    perfil = PerfilUsuario.objects.create(user=user, rol="CHOFER", empresa=empresa)
    return Chofer.objects.create(perfil=perfil, rut=f"{username}-rut", activo=activo)


class EditarRutaTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user(username="duena_er", password="Segura123!")
        self.empresa = Empresa.objects.create(nombre="Panadería Editar", owner=owner)
        PerfilUsuario.objects.create(user=owner, rol="OWNER", empresa=self.empresa)
        self.marco = crear_chofer(self.empresa, "marco")
        self.ana = crear_chofer(self.empresa, "ana")
        self.hoy = timezone.localdate()
        self.ruta = Ruta.objects.create(
            empresa=self.empresa, nombre="Reparto viernes", fecha=self.hoy + timedelta(days=2), chofer=self.marco,
        )
        cliente = Cliente.objects.create(empresa=self.empresa, nombre="Almacén 1", direccion="Calle 1")
        self.parada = ParadaRuta.objects.create(ruta=self.ruta, cliente=cliente, orden=1)
        self.client.login(username="duena_er", password="Segura123!")

    def _editar(self, **cambios):
        datos = {
            "nombre": self.ruta.nombre,
            "fecha": self.ruta.fecha.isoformat(),
            "chofer_id": self.ruta.chofer_id,
        }
        datos.update(cambios)
        return self.client.post(reverse("editar_ruta", args=[self.ruta.id]), datos)

    def test_detalle_de_ruta_tiene_boton_editar(self):
        resp = self.client.get(reverse("detalle_ruta", args=[self.ruta.id]))
        self.assertContains(resp, reverse("editar_ruta", args=[self.ruta.id]))

    def test_reasignar_chofer_avisa_al_nuevo_y_al_anterior(self):
        resp = self._editar(chofer_id=self.ana.id)
        self.assertRedirects(resp, reverse("detalle_ruta", args=[self.ruta.id]))
        self.ruta.refresh_from_db()
        self.assertEqual(self.ruta.chofer, self.ana)

        aviso_ana = Notificacion.objects.get(usuario=self.ana.perfil.user)
        self.assertEqual(aviso_ana.tipo, "RUTA_ASIGNADA")
        aviso_marco = Notificacion.objects.get(usuario=self.marco.perfil.user)
        self.assertEqual(aviso_marco.tipo, "RUTA_QUITADA")
        self.assertIn("Ya no tienes", aviso_marco.titulo)

        destinatarios = sorted(m.to[0] for m in mail.outbox)
        self.assertEqual(destinatarios, ["ana@example.com", "marco@example.com"])

    def test_aviso_pendiente_del_chofer_anterior_queda_leido(self):
        Notificacion.objects.create(
            usuario=self.marco.perfil.user, tipo="RUTA_ASIGNADA", titulo="Nueva ruta", ruta=self.ruta,
        )
        self._editar(chofer_id=self.ana.id)
        pendientes = Notificacion.objects.filter(usuario=self.marco.perfil.user, leida=False)
        self.assertEqual([n.tipo for n in pendientes], ["RUTA_QUITADA"])

    def test_chofer_anterior_ya_no_ve_la_ruta(self):
        self._editar(chofer_id=self.ana.id)
        self.client.logout()
        self.client.login(username="marco", password="Segura123!")
        resp = self.client.get(reverse("chofer_ruta_hoy") + f"?fecha={self.ruta.fecha.isoformat()}")
        self.assertIsNone(resp.context["ruta"])

    def test_cambiar_fecha_actualiza_el_enlace_de_los_avisos(self):
        aviso = Notificacion.objects.create(
            usuario=self.marco.perfil.user, tipo="RUTA_ASIGNADA", titulo="Nueva ruta", ruta=self.ruta,
            url=f"/chofer/ruta/?fecha={self.ruta.fecha.isoformat()}", leida=True,
        )
        nueva = self.hoy + timedelta(days=5)
        self._editar(fecha=nueva.isoformat())

        self.ruta.refresh_from_db()
        self.assertEqual(self.ruta.fecha, nueva)
        aviso.refresh_from_db()
        self.assertIn(f"fecha={nueva.isoformat()}", aviso.url)
        nuevo = Notificacion.objects.get(usuario=self.marco.perfil.user, leida=False)
        self.assertIn("la fecha cambió", nuevo.mensaje)

    def test_no_se_puede_mover_a_una_fecha_pasada(self):
        self._editar(fecha=(self.hoy - timedelta(days=1)).isoformat())
        self.ruta.refresh_from_db()
        self.assertEqual(self.ruta.fecha, self.hoy + timedelta(days=2))

    def test_ruta_empezada_no_cambia_de_dia_pero_si_de_chofer(self):
        self.ruta.fecha = self.hoy
        self.ruta.save()
        self.parada.estado_entrega = "ENTREGADO"
        self.parada.save()

        self._editar(fecha=(self.hoy + timedelta(days=3)).isoformat(), chofer_id=self.ana.id)
        self.ruta.refresh_from_db()
        self.assertEqual(self.ruta.fecha, self.hoy)      # la fecha no se movió
        self.assertEqual(self.ruta.chofer, self.ana)     # el chofer sí

    def test_ruta_pasada_solo_cambia_el_nombre(self):
        Ruta.objects.filter(pk=self.ruta.pk).update(fecha=self.hoy - timedelta(days=3))
        self.ruta.refresh_from_db()
        self._editar(nombre="Reparto histórico", chofer_id=self.ana.id, fecha=self.hoy.isoformat())
        self.ruta.refresh_from_db()
        self.assertEqual(self.ruta.nombre, "Reparto histórico")
        self.assertEqual(self.ruta.chofer, self.marco)
        self.assertEqual(self.ruta.fecha, self.hoy - timedelta(days=3))
        self.assertFalse(Notificacion.objects.exists())

    def test_no_acepta_chofer_inactivo_ni_de_otra_empresa(self):
        inactivo = crear_chofer(self.empresa, "pedro", activo=False)
        otro_owner = User.objects.create_user(username="otro_er", password="Segura123!")
        otra = Empresa.objects.create(nombre="Otra", owner=otro_owner)
        ajeno = crear_chofer(otra, "ajeno")

        for chofer in (inactivo, ajeno):
            resp = self._editar(chofer_id=chofer.id)
            self.assertEqual(resp.status_code, 200)
            self.ruta.refresh_from_db()
            self.assertEqual(self.ruta.chofer, self.marco)

    def test_nombre_obligatorio(self):
        resp = self._editar(nombre="  ")
        self.assertEqual(resp.status_code, 200)
        self.ruta.refresh_from_db()
        self.assertEqual(self.ruta.nombre, "Reparto viernes")

    def test_sin_cambios_no_avisa(self):
        self._editar()
        self.assertFalse(Notificacion.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_otra_empresa_no_puede_editar_la_ruta(self):
        otro_owner = User.objects.create_user(username="otro_owner_er", password="Segura123!")
        otra = Empresa.objects.create(nombre="Otra 2", owner=otro_owner)
        PerfilUsuario.objects.create(user=otro_owner, rol="OWNER", empresa=otra)
        self.client.login(username="otro_owner_er", password="Segura123!")
        resp = self.client.get(reverse("editar_ruta", args=[self.ruta.id]))
        self.assertEqual(resp.status_code, 404)

    def test_chofer_no_puede_editar_rutas(self):
        self.client.login(username="marco", password="Segura123!")
        resp = self.client.get(reverse("editar_ruta", args=[self.ruta.id]))
        self.assertEqual(resp.status_code, 302)
