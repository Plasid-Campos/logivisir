"""
Solicitud de cuenta: datos de la empresa (RUT válido, dirección), datos de
transferencia en la confirmación y el correo, y comprobante del pago.
"""
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.cuentas import normalizar_rut
from core.models import Empresa, SolicitudCuenta
from core.tests.test_solicitudes import datos_solicitud

MEDIA_TEMPORAL = tempfile.mkdtemp()


def pdf(nombre="comprobante.pdf", tamano=1000):
    return SimpleUploadedFile(nombre, b"%PDF-1.4 " + b"0" * tamano, content_type="application/pdf")


class RutTests(TestCase):
    def test_valida_digito_verificador_y_formatea(self):
        self.assertEqual(normalizar_rut("760864285"), "76.086.428-5")
        self.assertEqual(normalizar_rut("76.086.428-5"), "76.086.428-5")
        self.assertIsNone(normalizar_rut("76.086.428-0"))
        self.assertIsNone(normalizar_rut("abc"))


@override_settings(MEDIA_ROOT=MEDIA_TEMPORAL)
class SolicitudConDatosYComprobanteTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_TEMPORAL, ignore_errors=True)

    def _enviar(self, **extra):
        return self.client.post(reverse("solicitar_cuenta"), datos_solicitud(**extra))

    def test_guarda_rut_y_direccion(self):
        self._enviar(rut_empresa="760864285")
        sol = SolicitudCuenta.objects.get()
        self.assertEqual(sol.rut_empresa, "76.086.428-5")
        self.assertEqual(sol.comuna, "San Miguel")

    def test_rechaza_rut_invalido_y_conserva_lo_escrito(self):
        resp = self._enviar(rut_empresa="76.086.428-0")
        self.assertFalse(SolicitudCuenta.objects.exists())
        self.assertContains(resp, "RUT de la empresa no es válido")
        self.assertContains(resp, "Panadería Nueva")

    def test_rechaza_rut_de_una_empresa_existente(self):
        Empresa.objects.create(nombre="Ya cliente", rut_empresa="76.086.428-5",
                               owner=User.objects.create_user(username="x"))
        self._enviar()
        self.assertFalse(SolicitudCuenta.objects.exists())

    def test_exige_direccion_y_comuna(self):
        self._enviar(direccion="", comuna="")
        self.assertFalse(SolicitudCuenta.objects.exists())

    def test_correo_de_acuse_trae_datos_de_transferencia(self):
        self._enviar()
        cuerpo = mail.outbox[-1].body
        self.assertIn("SOL-", cuerpo)
        self.assertIn("$89.990", cuerpo)
        self.assertIn("Glosa", cuerpo)
        self.assertIn(reverse("subir_comprobante"), cuerpo)

    def test_confirmacion_muestra_monto_y_aviso_de_datos_demo(self):
        resp = self.client.get(self._enviar().url)
        self.assertContains(resp, "$89.990")
        self.assertContains(resp, "no transfieras dinero")

    @override_settings(PAGO_NUMERO_CUENTA="123-4-567890-1")
    def test_con_cuenta_configurada_no_muestra_aviso_demo(self):
        resp = self.client.get(self._enviar().url)
        self.assertContains(resp, "123-4-567890-1")
        self.assertNotContains(resp, "no transfieras dinero")

    def test_otra_persona_no_ve_la_confirmacion(self):
        url = self._enviar().url
        self.client.session.flush()
        self.client.cookies.clear()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_sube_comprobante_desde_la_confirmacion(self):
        url = self._enviar().url
        self.client.post(url, {"comprobante": pdf()})
        sol = SolicitudCuenta.objects.get()
        self.assertTrue(sol.comprobante.name.startswith("comprobantes/"))
        self.assertIsNotNone(sol.comprobante_subido_en)

    def test_rechaza_tipo_y_tamano_de_archivo(self):
        url = self._enviar().url
        self.client.post(url, {"comprobante": SimpleUploadedFile("virus.exe", b"MZ")})
        self.client.post(url, {"comprobante": pdf(tamano=6 * 1024 * 1024)})
        self.assertFalse(SolicitudCuenta.objects.get().comprobante)

    def test_sube_comprobante_despues_con_codigo_y_correo(self):
        self._enviar()
        sol = SolicitudCuenta.objects.get()
        self.client.cookies.clear()
        resp = self.client.post(reverse("subir_comprobante"), {
            "codigo": sol.codigo_referencia, "email": "JUANITA@nueva.cl", "comprobante": pdf(),
        })
        self.assertContains(resp, "Comprobante recibido")
        sol.refresh_from_db()
        self.assertTrue(sol.comprobante)

    def test_no_sube_comprobante_con_correo_distinto(self):
        self._enviar()
        sol = SolicitudCuenta.objects.get()
        resp = self.client.post(reverse("subir_comprobante"), {
            "codigo": sol.codigo_referencia, "email": "otro@correo.cl", "comprobante": pdf(),
        })
        self.assertContains(resp, "No encontramos una solicitud")
        sol.refresh_from_db()
        self.assertFalse(sol.comprobante)

    def test_solo_el_equipo_descarga_el_comprobante(self):
        url = self._enviar().url
        self.client.post(url, {"comprobante": pdf()})
        sol = SolicitudCuenta.objects.get()
        descarga = reverse("staff_comprobante", args=[sol.id])
        self.assertEqual(self.client.get(descarga).status_code, 302)
        staff = User.objects.create_user(username="equipo", password="x", is_staff=True)
        self.client.force_login(staff)
        resp = self.client.get(descarga)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(sol.codigo_referencia, resp["Content-Disposition"])

    def test_crear_cuenta_copia_rut_y_direccion_a_la_empresa(self):
        self._enviar()
        sol = SolicitudCuenta.objects.get()
        sol.estado = "PAGO_VALIDADO"
        sol.save()
        staff = User.objects.create_user(username="equipo", password="x", is_staff=True)
        self.client.force_login(staff)
        self.client.post(reverse("crear_cuenta_solicitud", args=[sol.id]))
        empresa = Empresa.objects.get(nombre="Panadería Nueva")
        self.assertEqual(empresa.rut_empresa, "76.086.428-5")
        self.assertEqual(empresa.direccion_origen, "Gran Avenida 4400")
        self.assertEqual(empresa.comuna_origen, "San Miguel")
        self.assertIsNone(empresa.latitud_origen)  # el dueño la confirma en el mapa
