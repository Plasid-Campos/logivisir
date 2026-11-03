"""
Pagos de membresía: registrar un pago renueva el vencimiento sin perder días,
anularlo lo revierte, y el panel calcula los ingresos de LogiVisir.
"""
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core import membresias
from core.models import Empresa, Pago, PerfilUsuario, SolicitudCuenta


class SumarMesesTests(TestCase):
    def test_fin_de_mes_y_cambio_de_anio(self):
        self.assertEqual(membresias.sumar_meses(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(membresias.sumar_meses(date(2026, 11, 15), 3), date(2027, 2, 15))
        self.assertEqual(membresias.sumar_meses(date(2026, 1, 10), -1), date(2025, 12, 10))


class PagosTests(TestCase):
    def setUp(self):
        self.hoy = timezone.localdate()
        self.staff = User.objects.create_user(username="equipo", password="Segura123!", is_staff=True)
        self.owner = User.objects.create_user(username="dueno", password="Segura123!")
        self.empresa = Empresa.objects.create(nombre="Pyme", owner=self.owner, plan="BASICO")
        PerfilUsuario.objects.create(user=self.owner, empresa=self.empresa, rol="OWNER")
        self.client.login(username="equipo", password="Segura123!")

    def _pagar(self, **extra):
        datos = {"plan": "PRO", "meses": "1", "monto": "89990", "fecha_pago": self.hoy.isoformat(),
                 "medio": "TRANSFERENCIA", "referencia": "TRF-1"}
        datos.update(extra)
        return self.client.post(reverse("staff_registrar_pago", args=[self.empresa.id]), datos)

    def test_pago_sin_vencimiento_parte_hoy(self):
        self._pagar()
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.plan, "PRO")
        self.assertEqual(self.empresa.suscripcion_vence, membresias.sumar_meses(self.hoy, 1) - timedelta(days=1))
        pago = Pago.objects.get()
        self.assertEqual(pago.registrado_por, self.staff)
        self.assertEqual(pago.monto, 89990)

    def test_pago_con_membresia_vigente_se_suma_al_vencimiento(self):
        vence = self.hoy + timedelta(days=10)
        self.empresa.suscripcion_vence = vence
        self.empresa.save()
        self._pagar(meses="3", monto="269970")
        self.empresa.refresh_from_db()
        desde = vence + timedelta(days=1)
        self.assertEqual(self.empresa.suscripcion_vence, membresias.sumar_meses(desde, 3) - timedelta(days=1))

    def test_pago_con_membresia_vencida_parte_hoy(self):
        self.empresa.suscripcion_vence = self.hoy - timedelta(days=20)
        self.empresa.save()
        self._pagar()
        pago = Pago.objects.get()
        self.assertEqual(pago.periodo_desde, self.hoy)

    def test_pago_puede_reactivar_una_empresa_suspendida(self):
        self.empresa.activa = False
        self.empresa.save()
        self._pagar(reactivar="1")
        self.empresa.refresh_from_db()
        self.assertTrue(self.empresa.activa)

    def test_rechaza_monto_invalido_y_fecha_futura(self):
        self._pagar(monto="abc")
        self._pagar(monto="0")
        self._pagar(fecha_pago=(self.hoy + timedelta(days=1)).isoformat())
        self._pagar(meses="7")
        self.assertFalse(Pago.objects.exists())

    def test_anular_revierte_el_vencimiento_y_queda_en_el_historial(self):
        vence = self.hoy + timedelta(days=4)
        self.empresa.suscripcion_vence = vence
        self.empresa.save()
        self._pagar()
        pago = Pago.objects.get()
        self.client.post(reverse("staff_anular_pago", args=[pago.id]), {"motivo": "Transferencia rebotada"})
        pago.refresh_from_db()
        self.empresa.refresh_from_db()
        self.assertTrue(pago.anulado)
        self.assertEqual(pago.anulado_por, self.staff)
        self.assertEqual(self.empresa.suscripcion_vence, vence)

    def test_anular_exige_motivo(self):
        self._pagar()
        pago = Pago.objects.get()
        self.client.post(reverse("staff_anular_pago", args=[pago.id]), {"motivo": ""})
        pago.refresh_from_db()
        self.assertFalse(pago.anulado)

    def test_empresa_no_puede_registrar_pagos(self):
        self.client.logout()
        self.client.login(username="dueno", password="Segura123!")
        resp = self._pagar()
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Pago.objects.exists())

    def test_crear_cuenta_desde_solicitud_registra_el_primer_pago(self):
        sol = SolicitudCuenta.objects.create(
            nombre_empresa="Nueva", nombre_contacto="Ana", email_contacto="ana@n.cl",
            telefono_contacto="1", plan_solicitado="EMPRESARIAL", estado="PAGO_VALIDADO",
        )
        self.client.post(reverse("crear_cuenta_solicitud", args=[sol.id]))
        pago = Pago.objects.get(empresa__nombre="Nueva")
        self.assertEqual(pago.monto, 149990)
        self.assertEqual(pago.referencia, sol.codigo_referencia)

    def test_lista_de_pagos_filtra_y_exporta_csv(self):
        self._pagar()
        otra = Empresa.objects.create(nombre="Otra Pyme", owner=self.owner)
        membresias.registrar_pago(otra, plan="BASICO", monto=49990, fecha_pago=self.hoy, meses=1, medio="EFECTIVO")
        resp = self.client.get(reverse("staff_pagos"), {"empresa": self.empresa.id})
        self.assertContains(resp, "89.990")
        self.assertNotContains(resp, "Otra Pyme</a>")
        csv_resp = self.client.get(reverse("staff_pagos"), {"formato": "csv"})
        contenido = csv_resp.content.decode("utf-8")
        self.assertIn("Otra Pyme", contenido)
        self.assertIn("89990", contenido)


class IngresosPanelTests(TestCase):
    def test_mrr_cuenta_solo_empresas_activas_al_dia(self):
        hoy = timezone.localdate()
        u = User.objects.create_user(username="x")
        al_dia = Empresa(nombre="A", owner=u, plan="PRO", activa=True, suscripcion_vence=hoy + timedelta(days=3))
        vencida = Empresa(nombre="B", owner=u, plan="PRO", activa=True, suscripcion_vence=hoy - timedelta(days=1))
        suspendida = Empresa(nombre="C", owner=u, plan="BASICO", activa=False, suscripcion_vence=hoy + timedelta(days=9))
        self.assertEqual(membresias.mrr([al_dia, vencida, suspendida], hoy), 89990)

    def test_panel_muestra_mrr_y_pagos_del_mes(self):
        hoy = timezone.localdate()
        staff = User.objects.create_user(username="equipo", password="Segura123!", is_staff=True)
        u = User.objects.create_user(username="d")
        e = Empresa.objects.create(nombre="Pyme Panel", owner=u)
        membresias.registrar_pago(e, plan="EMPRESARIAL", monto=149990, fecha_pago=hoy, meses=1, medio="TARJETA")
        self.client.force_login(staff)
        resp = self.client.get(reverse("staff_panel"))
        self.assertContains(resp, "$149.990")
        self.assertContains(resp, "Ingreso mensual recurrente")


class PreciosPaginaInicioTests(TestCase):
    """La página pública muestra los mismos precios que se cobran en la solicitud."""

    def test_home_muestra_precios_vigentes(self):
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        for codigo, precio in membresias.PRECIOS_PLAN.items():
            monto = f"${precio:,}".replace(",", ".")
            self.assertContains(resp, monto)
            self.assertContains(resp, f"?plan={codigo}")

    def test_home_no_ofrece_funciones_que_no_existen(self):
        resp = self.client.get(reverse("home"))
        self.assertNotContains(resp, "Catálogo de productos")
        self.assertNotContains(resp, "29.990")
