import io
from unittest.mock import patch

import openpyxl
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core import importar_clientes as imp
from core.models import Cliente, Empresa, PerfilUsuario

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def excel(hojas, nombre="clientes.xlsx"):
    """hojas: {titulo: [[celdas], ...]} -> archivo .xlsx subible."""
    libro = openpyxl.Workbook()
    libro.remove(libro.active)
    for titulo, filas in hojas.items():
        hoja = libro.create_sheet(titulo)
        for fila in filas:
            hoja.append(fila)
    salida = io.BytesIO()
    libro.save(salida)
    return SimpleUploadedFile(nombre, salida.getvalue(), content_type=XLSX)


class LecturaYColumnasTests(TestCase):
    def test_reconoce_titulos_habituales_sin_importar_tildes(self):
        titulos = ["N°", "Razón Social", "Domicilio", "COMUNA", "Fono", "Correo electrónico", "R.U.T."]
        mapeo = imp.detectar_mapeo(titulos)
        self.assertEqual(mapeo["nombre"], 1)
        self.assertEqual(mapeo["direccion"], 2)
        self.assertEqual(mapeo["comuna"], 3)
        self.assertEqual(mapeo["telefono"], 4)
        self.assertEqual(mapeo["email"], 5)
        self.assertEqual(mapeo["rut"], 6)

    def test_prefiere_el_titulo_exacto_y_no_repite_columnas(self):
        mapeo = imp.detectar_mapeo(["Nombre contacto", "Nombre", "Dirección"])
        self.assertEqual(mapeo["nombre"], 1)
        self.assertEqual(mapeo["direccion"], 2)

    def test_encuentra_la_fila_de_titulos_bajo_un_encabezado(self):
        filas = [["Listado de clientes 2026", ""], ["", ""], ["Cliente", "Dirección"], ["Doña Rosa", "Gran Avenida 4400"]]
        self.assertEqual(imp.detectar_encabezado(filas), 2)

    def test_numeros_de_excel_se_leen_sin_decimales(self):
        self.assertEqual(imp._celda(912345678.0), "912345678")
        self.assertEqual(imp._celda("  Av.   Matta  "), "Av. Matta")

    def test_csv_con_punto_y_coma_y_tildes_de_excel_windows(self):
        contenido = "Nombre;Dirección;Comuna\nPanadería Ñuñoa;Irarrázaval 3000;Ñuñoa\n".encode("cp1252")
        hojas = imp.leer_archivo(SimpleUploadedFile("c.csv", contenido))
        self.assertEqual(hojas["CSV"][1], ["Panadería Ñuñoa", "Irarrázaval 3000", "Ñuñoa"])

    def test_rechaza_xls_antiguo_con_instrucciones(self):
        with self.assertRaisesMessage(imp.ArchivoInvalido, "guárdalo como"):
            imp.leer_archivo(SimpleUploadedFile("viejo.xls", b"\xd0\xcf\x11\xe0"))


class PlanillasSinTitulosTests(TestCase):
    FILAS = [
        ["Almacén Doña Rosa", "Gran Avenida 4400", "San Miguel", "+56 9 1234 5678", "rosa@correo.cl", "76.543.210-3"],
        ["Minimarket El Sol", "Av. Pajaritos 2150, local 3", "Maipú", "225551234", "", ""],
        ["Kiosko Azul", "Pio Nono 235", "Providencia", "", "azul@correo.cl", "11.111.111-1"],
        ["Botillería Central", "San Pablo 5600", "Lo Prado", "987654321", "", ""],
    ]

    def test_reconoce_las_columnas_por_su_contenido(self):
        est = imp.estructura(self.FILAS)
        self.assertIsNone(est["fila_titulos"])
        self.assertEqual(est["inicio"], 0)   # la primera fila ya es un cliente
        self.assertEqual(est["mapeo"], {"nombre": 0, "direccion": 1, "comuna": 2, "telefono": 3, "email": 4, "rut": 5})

    def test_salta_un_titulo_de_planilla_sin_titulos_de_columna(self):
        filas = [["Clientes de la distribuidora", "", ""], ["", "", ""]] + [f[:3] for f in self.FILAS]
        est = imp.estructura(filas)
        self.assertIsNone(est["fila_titulos"])
        self.assertEqual(est["inicio"], 2)
        self.assertEqual((est["mapeo"]["nombre"], est["mapeo"]["direccion"]), (0, 1))

    def test_una_fila_de_datos_con_cliente_regular_no_se_toma_como_titulos(self):
        filas = [f[:2] + ["Cliente regular"] for f in self.FILAS]
        self.assertIsNone(imp.detectar_encabezado(filas))

    def test_titulos_desconocidos_siguen_siendo_titulos(self):
        filas = [["Cod", "Local", "Ubicación"]] + [[str(i), f[0], f[1]] for i, f in enumerate(self.FILAS, 1)]
        est = imp.estructura(filas)
        self.assertEqual(est["fila_titulos"], 0)
        self.assertEqual((est["mapeo"]["nombre"], est["mapeo"]["direccion"]), (1, 2))

    def test_no_confunde_telefonos_con_rut_ni_codigos_con_nombre(self):
        filas = [[str(i), "9" + str(12345670 + i), f"{f[0]} {i}", f[1]] for i, f in enumerate(self.FILAS * 3, 1)]
        mapeo = imp.estructura(filas)["mapeo"]
        self.assertEqual((mapeo["telefono"], mapeo["nombre"], mapeo["direccion"]), (1, 2, 3))
        self.assertNotIn("rut", mapeo)


class ImportarClientesTests(TestCase):
    def setUp(self):
        cache.clear()
        owner = User.objects.create_user(username="dueno_imp", password="Segura123!")
        self.empresa = Empresa.objects.create(nombre="Distribuidora Importa", owner=owner, ciudad_origen="Santiago")
        PerfilUsuario.objects.create(user=owner, rol="OWNER", empresa=self.empresa)
        Cliente.objects.create(empresa=self.empresa, nombre="Almacén Existente", direccion="Franklin 700", rut="76.543.210-3")
        self.client.login(username="dueno_imp", password="Segura123!")

    def subir(self, archivo):
        return self.client.post(reverse("importar_clientes"), {"archivo": archivo})

    def test_flujo_completo_omite_repetidos_y_filas_sin_direccion(self):
        archivo = excel({"Clientes": [
            ["Nombre", "Dirección", "Comuna", "Teléfono", "Correo", "RUT", "Tipo"],
            ["Doña Rosa", "Gran Avenida 4400", "San Miguel", 912345678, "rosa@correo.cl", "", "Cliente regular"],
            ["ALMACÉN EXISTENTE", "franklin 700", "Santiago", "", "", "", ""],      # ya existe (nombre+dirección)
            ["Otro nombre", "Otra calle 1", "", "", "", "765432103", ""],            # ya existe (mismo RUT)
            ["Sin Dirección", "", "Maipú", "", "", "", ""],                          # error
            ["Doña Rosa", "Gran Avenida 4400", "San Miguel", "", "", "", ""],        # repetida en el archivo
            ["María González", "Los Aromos 345", "La Florida", "", "no-es-correo", "11.111.111-2", "Delivery a domicilio"],
            ["", "", "", "", "", "", ""],                                             # vacía: se ignora
        ]})
        resp = self.subir(archivo)
        self.assertRedirects(resp, reverse("importar_clientes") + "?revisar=1", fetch_redirect_response=False)

        resp = self.client.get(reverse("importar_clientes") + "?revisar=1")
        analisis = resp.context["analisis"]
        self.assertEqual([r["nombre"] for r in analisis["nuevos"]], ["Doña Rosa", "María González"])
        self.assertEqual(len(analisis["repetidos"]), 3)
        self.assertEqual([r["fila"] for r in analisis["errores"]], [5])
        self.assertContains(resp, "Importar 2 clientes")

        datos = {"accion": "importar", "hoja": "Clientes"}
        datos.update({f"col_{c}": str(j) for c, j in resp.context["mapeo"].items()})
        resp = self.client.post(reverse("importar_clientes"), datos)
        self.assertRedirects(resp, reverse("importar_clientes_resultado"), fetch_redirect_response=False)

        rosa = Cliente.objects.get(empresa=self.empresa, nombre="Doña Rosa")
        self.assertEqual((rosa.telefono, rosa.email, rosa.ciudad), ("912345678", "rosa@correo.cl", "Santiago"))
        self.assertTrue(rosa.ubicacion_pendiente)
        maria = Cliente.objects.get(empresa=self.empresa, nombre="María González")
        self.assertIsNone(maria.email)   # correo inválido queda en blanco
        self.assertIsNone(maria.rut)     # RUT con dígito verificador malo queda en blanco
        self.assertEqual(maria.tipo_cliente, "DELIVERY")
        self.assertEqual(Cliente.objects.filter(empresa=self.empresa).count(), 3)

        resp = self.client.get(reverse("importar_clientes_resultado"))
        self.assertContains(resp, "2 clientes importados")
        self.assertEqual(resp.context["estado"]["pendientes"], 2)

    def test_el_usuario_puede_corregir_la_columna_y_elegir_hoja(self):
        archivo = excel({
            "Resumen": [["Total", 2]],
            "Cartera": [["Cod", "Local", "Ubicación"], ["1", "Kiosko Azul", "Pio Nono 235"]],
        })
        self.subir(archivo)
        resp = self.client.get(reverse("importar_clientes") + "?revisar=1")
        self.assertEqual(resp.context["hoja"], "Cartera")       # la hoja con datos de clientes
        # «Ubicación» no es un título conocido, pero su contenido es una dirección.
        self.assertEqual(resp.context["mapeo"]["direccion"], 2)
        self.assertContains(resp, "Reconocida por su contenido")

        # El usuario puede cambiar la columna: aquí elige «Cod» como nombre a propósito.
        resp = self.client.get(reverse("importar_clientes"), {"revisar": 1, "hoja": "Cartera", "titulos": "si", "col_nombre": 0, "col_direccion": 2})
        self.assertEqual(resp.context["analisis"]["nuevos"][0]["nombre"], "1")
        resp = self.client.get(reverse("importar_clientes"), {"revisar": 1, "hoja": "Cartera", "titulos": "si", "col_nombre": 1})
        self.assertEqual(resp.context["falta"], ["Dirección"])
        self.assertContains(resp, "No está en mi archivo")

        self.client.post(reverse("importar_clientes"), {"accion": "importar", "hoja": "Cartera", "titulos": "si", "col_nombre": 1, "col_direccion": 2})
        self.assertTrue(Cliente.objects.filter(empresa=self.empresa, nombre="Kiosko Azul", direccion="Pio Nono 235").exists())

    def test_planilla_sin_titulos_importa_tambien_la_primera_fila(self):
        self.subir(excel({"Hoja1": [r[:3] for r in PlanillasSinTitulosTests.FILAS]}))
        resp = self.client.get(reverse("importar_clientes") + "?revisar=1")
        self.assertFalse(resp.context["con_titulos"])
        self.assertContains(resp, "sin fila de títulos")
        self.assertEqual(resp.context["analisis"]["nuevos"][0]["nombre"], "Almacén Doña Rosa")
        self.assertContains(resp, "Columna A")

        datos = {"accion": "importar", "hoja": "Hoja1", "titulos": "no"}
        datos.update({f"col_{c}": str(j) for c, j in resp.context["mapeo"].items()})
        self.client.post(reverse("importar_clientes"), datos)
        self.assertTrue(Cliente.objects.filter(empresa=self.empresa, nombre="Almacén Doña Rosa", comuna="San Miguel").exists())
        self.assertEqual(Cliente.objects.filter(empresa=self.empresa).count(), 5)

    def test_el_usuario_puede_indicar_si_hay_fila_de_titulos(self):
        self.subir(excel({"Hoja1": [["Nombre", "Dirección"], ["Doña Rosa", "Gran Avenida 4400"], ["El Sol", "Pajaritos 2150"], ["Kiosko Azul", "Pio Nono 235"]]}))
        resp = self.client.get(reverse("importar_clientes"), {"revisar": 1, "hoja": "Hoja1", "titulos": "no"})
        self.assertFalse(resp.context["con_titulos"])
        # Leída sin títulos, la fila 1 («Nombre / Dirección») aparecería como cliente en la vista previa.
        self.assertEqual(resp.context["analisis"]["nuevos"][0]["nombre"], "Nombre")
        resp = self.client.get(reverse("importar_clientes"), {"revisar": 1, "hoja": "Hoja1", "titulos": "si"})
        self.assertEqual([r["nombre"] for r in resp.context["analisis"]["nuevos"]], ["Doña Rosa", "El Sol", "Kiosko Azul"])

    def test_mil_doscientos_clientes_se_guardan_de_una_vez(self):
        filas = [["Nombre", "Dirección", "Comuna"]] + [[f"Cliente {i}", f"Calle {i}", "Maipú"] for i in range(1200)]
        self.subir(excel({"Hoja1": filas}))
        resp = self.client.post(reverse("importar_clientes"), {"accion": "importar", "hoja": "Hoja1", "col_nombre": 0, "col_direccion": 1, "col_comuna": 2})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Cliente.objects.filter(empresa=self.empresa, ubicacion_pendiente=True).count(), 1200)

    def test_archivo_invalido_muestra_el_error(self):
        resp = self.subir(SimpleUploadedFile("foto.png", b"x"))
        self.assertContains(resp, "Sube un archivo Excel")
        self.assertEqual(Cliente.objects.filter(empresa=self.empresa).count(), 1)

    def test_importar_sin_archivo_en_sesion_pide_volver_a_subir(self):
        resp = self.client.post(reverse("importar_clientes"), {"accion": "importar"})
        self.assertRedirects(resp, reverse("importar_clientes"), fetch_redirect_response=False)

    def test_chofer_no_puede_importar(self):
        chofer = User.objects.create_user(username="chofer_imp", password="Segura123!")
        PerfilUsuario.objects.create(user=chofer, rol="CHOFER", empresa=self.empresa)
        self.client.login(username="chofer_imp", password="Segura123!")
        self.assertEqual(self.client.get(reverse("importar_clientes")).status_code, 302)
        self.assertEqual(self.client.get(reverse("plantilla_clientes")).status_code, 302)

    def test_plantilla_descargable_se_reconoce_sola(self):
        resp = self.client.get(reverse("plantilla_clientes"))
        self.assertEqual(resp["Content-Type"], XLSX)
        hojas = imp.leer_archivo(SimpleUploadedFile("plantilla_clientes_logivisir.xlsx", resp.content))
        mapeo = imp.detectar_mapeo(hojas["Clientes"][0])
        self.assertEqual(set(mapeo), set(imp.SINONIMOS))

    def test_lista_y_alta_ofrecen_importar(self):
        self.assertContains(self.client.get(reverse("lista_clientes")), "Importar desde Excel")
        self.assertContains(self.client.get(reverse("crear_cliente")), "Impórtalos todos de una vez")


@patch("core.importar_clientes.INTERVALO_NOMINATIM", 0)
class UbicarImportadosTests(TestCase):
    def setUp(self):
        cache.clear()
        owner = User.objects.create_user(username="dueno_ub", password="Segura123!")
        self.empresa = Empresa.objects.create(nombre="Empresa Ubica", owner=owner)
        PerfilUsuario.objects.create(user=owner, rol="OWNER", empresa=self.empresa)
        self.client.login(username="dueno_ub", password="Segura123!")
        self.ya_ubicado = Cliente.objects.create(
            empresa=self.empresa, nombre="Vecino", direccion="Gran Avenida 4400", comuna="San Miguel",
            latitud=-33.49, longitud=-70.65, geocodificado=True,
        )
        self.pendientes = [
            Cliente.objects.create(empresa=self.empresa, nombre=f"P{i}", direccion=d, comuna="San Miguel", ubicacion_pendiente=True)
            for i, d in enumerate(["Gran Avenida 4400", "Llano Subercaseaux 3000", "Pasaje Inexistente 9"])
        ]

    @patch("core.geocoding.geocodificar_direccion", side_effect=[(-33.5, -70.66), None])
    def test_ubica_por_lotes_y_reutiliza_direcciones_conocidas(self, geocodificar):
        resp = self.client.post(reverse("ubicar_importados"))
        datos = resp.json()
        self.assertEqual(datos["pendientes"], 0)
        # La primera dirección ya estaba ubicada en otro cliente: no se consulta.
        self.assertEqual(geocodificar.call_count, 2)
        p0, p1, p2 = [Cliente.objects.get(id=c.id) for c in self.pendientes]
        self.assertEqual((p0.latitud, p0.geocodificado), (-33.49, True))
        self.assertTrue(p1.geocodificado)
        self.assertFalse(p2.geocodificado)
        self.assertFalse(any(c.ubicacion_pendiente for c in (p0, p1, p2)))

    @patch("core.geocoding.geocodificar_direccion", return_value=(-33.5, -70.66))
    def test_respeta_el_tiempo_de_cada_lote(self, geocodificar):
        procesados = imp.ubicar_lote(self.empresa, segundos=-1)
        self.assertEqual(procesados, 1)  # siempre avanza al menos uno

    def test_si_otra_pestana_esta_ubicando_responde_ocupado(self):
        cache.add(imp.CLAVE_CANDADO, 1, 30)
        datos = self.client.post(reverse("ubicar_importados")).json()
        self.assertTrue(datos["ocupado"])
        self.assertEqual(datos["pendientes"], 3)

    def test_otra_empresa_no_ubica_mis_clientes(self):
        otro = User.objects.create_user(username="ajeno_ub", password="Segura123!")
        empresa2 = Empresa.objects.create(nombre="Ajena", owner=otro)
        PerfilUsuario.objects.create(user=otro, rol="OWNER", empresa=empresa2)
        self.client.login(username="ajeno_ub", password="Segura123!")
        datos = self.client.post(reverse("ubicar_importados")).json()
        self.assertEqual((datos["procesados"], datos["pendientes"]), (0, 0))
        self.assertEqual(Cliente.objects.filter(empresa=self.empresa, ubicacion_pendiente=True).count(), 3)

    def test_lista_avisa_pendientes_aparte_de_los_no_encontrados(self):
        resp = self.client.get(reverse("lista_clientes"))
        self.assertEqual(resp.context["ubicacion_pendiente"], 3)
        self.assertEqual(resp.context["activos_sin_ubicacion"], 0)
        self.assertContains(resp, "Continuar ubicando")

    def test_resultado_sin_importacion_reciente_retoma_los_pendientes(self):
        resp = self.client.get(reverse("importar_clientes_resultado"))
        self.assertEqual(resp.context["estado"]["pendientes"], 3)
        Cliente.objects.filter(empresa=self.empresa).update(ubicacion_pendiente=False)
        self.assertRedirects(self.client.get(reverse("importar_clientes_resultado")), reverse("lista_clientes"), fetch_redirect_response=False)
