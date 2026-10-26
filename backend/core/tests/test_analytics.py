from datetime import date, datetime, time, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core import analytics
from core.models import Chofer, Cliente, Empresa, ParadaRuta, PerfilUsuario, Pedido, Ruta


def crear_empresa_con_owner(nombre, username):
    user = User.objects.create_user(username=username, password="Segura123!")
    empresa = Empresa.objects.create(nombre=nombre, owner=user, direccion_origen="Centro")
    PerfilUsuario.objects.create(user=user, rol="OWNER", empresa=empresa)
    return empresa, user


def crear_pedido(empresa, cliente, estado="ENTREGADO", dias_atras=0, hoy=None):
    """
    `Pedido.creado_en` es auto_now_add=True: no se puede fijar al crear, hay
    que crear y luego hacer un UPDATE directo saltandose el auto_now_add.
    """
    pedido = Pedido.objects.create(
        empresa=empresa, cliente=cliente, estado=estado, nota="5 kg marraqueta",
    )
    hoy = hoy or date.today()
    fecha = hoy - timedelta(days=dias_atras)
    fecha_hora = timezone.make_aware(datetime.combine(fecha, time.min))
    Pedido.objects.filter(pk=pedido.pk).update(creado_en=fecha_hora)
    pedido.refresh_from_db()
    return pedido


class AnalyticsCalculoTests(TestCase):
    def setUp(self):
        self.empresa, self.owner = crear_empresa_con_owner("Panadería Test", "owner_analytics")
        self.hoy = date(2026, 6, 15)

    def test_resumen_cuenta_solo_entregados_como_despachos(self):
        cliente = Cliente.objects.create(empresa=self.empresa, nombre="Cliente A", direccion="Calle 1")
        crear_pedido(self.empresa, cliente, estado="ENTREGADO", hoy=self.hoy)
        crear_pedido(self.empresa, cliente, estado="CANCELADO", hoy=self.hoy)
        crear_pedido(self.empresa, cliente, estado="PENDIENTE", hoy=self.hoy)

        resumen = analytics.resumen_despachos(self.empresa)
        self.assertEqual(resumen["despachos"], 1)
        self.assertEqual(resumen["pedidos_pendientes"], 1)
        self.assertEqual(resumen["clientes_atendidos"], 1)

    def test_resumen_empresa_sin_datos_no_lanza_excepcion(self):
        resumen = analytics.resumen_despachos(self.empresa)
        self.assertEqual(resumen["despachos"], 0)
        self.assertIsNone(resumen["tasa_exito"])
        self.assertIsNone(resumen["entregas_con_foto"])

    def test_tasa_de_exito_usa_resultado_de_las_paradas(self):
        chofer_user = User.objects.create_user(username="chofer_tasa", password="Segura123!")
        perfil = PerfilUsuario.objects.create(user=chofer_user, rol="CHOFER", empresa=self.empresa)
        chofer = Chofer.objects.create(perfil=perfil, rut="5-5")
        ruta = Ruta.objects.create(empresa=self.empresa, nombre="R", fecha=self.hoy, chofer=chofer)
        cliente = Cliente.objects.create(empresa=self.empresa, nombre="C", direccion="D")
        for orden, estado in enumerate(["ENTREGADO", "ENTREGADO", "ENTREGADO", "NO_ENTREGADO"], start=1):
            ParadaRuta.objects.create(ruta=ruta, cliente=cliente, orden=orden, estado_entrega=estado)

        resumen = analytics.resumen_despachos(self.empresa)
        self.assertEqual(resumen["tasa_exito"], 75.0)
        self.assertEqual(resumen["entregas_fallidas"], 1)
        self.assertEqual(resumen["entregas_con_foto"], 0.0)

    def test_despachos_por_comuna_agrupa_y_ordena_desc(self):
        c1 = Cliente.objects.create(empresa=self.empresa, nombre="C1", direccion="D1", comuna="Puente Alto")
        c2 = Cliente.objects.create(empresa=self.empresa, nombre="C2", direccion="D2", comuna="La Florida")
        crear_pedido(self.empresa, c1, hoy=self.hoy)
        for _ in range(3):
            crear_pedido(self.empresa, c2, hoy=self.hoy)

        filas = analytics.despachos_por_comuna(self.empresa)
        self.assertEqual(filas[0]["comuna"], "La Florida")
        self.assertEqual(filas[0]["despachos"], 3)
        self.assertEqual(filas[1]["comuna"], "Puente Alto")

    def test_top_clientes_orden_desc_por_cantidad_de_despachos(self):
        c1 = Cliente.objects.create(empresa=self.empresa, nombre="Pocos despachos", direccion="D1")
        c2 = Cliente.objects.create(empresa=self.empresa, nombre="Muchos despachos", direccion="D2")
        crear_pedido(self.empresa, c1, hoy=self.hoy)
        for _ in range(4):
            crear_pedido(self.empresa, c2, hoy=self.hoy)

        top = analytics.top_clientes(self.empresa)
        self.assertEqual(top[0]["nombre"], "Muchos despachos")
        self.assertEqual(top[0]["num_despachos"], 4)
        self.assertEqual(top[1]["nombre"], "Pocos despachos")

    def test_calcular_rf_excluye_clientes_sin_despachos_entregados(self):
        con_pedido = Cliente.objects.create(empresa=self.empresa, nombre="Con pedido", direccion="D1")
        sin_pedido = Cliente.objects.create(empresa=self.empresa, nombre="Sin pedido", direccion="D2")
        crear_pedido(self.empresa, con_pedido, hoy=self.hoy)
        crear_pedido(self.empresa, sin_pedido, estado="CANCELADO", hoy=self.hoy)

        rf = analytics.calcular_rf(self.empresa, hoy=self.hoy)
        nombres = [r["nombre"] for r in rf]
        self.assertIn("Con pedido", nombres)
        self.assertNotIn("Sin pedido", nombres)

    def test_calcular_rf_recencia_correcta(self):
        cliente = Cliente.objects.create(empresa=self.empresa, nombre="Cliente", direccion="D1")
        crear_pedido(self.empresa, cliente, dias_atras=7, hoy=self.hoy)

        rf = analytics.calcular_rf(self.empresa, hoy=self.hoy)
        self.assertEqual(rf[0]["recencia_dias"], 7)

    def test_segmentar_clientes_pocos_clientes_no_aplica_clustering(self):
        for i in range(2):
            cliente = Cliente.objects.create(empresa=self.empresa, nombre=f"Cliente {i}", direccion="D")
            crear_pedido(self.empresa, cliente, hoy=self.hoy)

        resultado = analytics.segmentar_clientes(self.empresa, hoy=self.hoy)
        self.assertFalse(resultado["clustering_aplicado"])
        self.assertIsNotNone(resultado["motivo"])
        for c in resultado["clientes"]:
            self.assertIsNone(c["segmento"])

    def _crear_dataset_diverso(self):
        mejor = Cliente.objects.create(empresa=self.empresa, nombre="Mejor cliente", direccion="D")
        peor = Cliente.objects.create(empresa=self.empresa, nombre="Peor cliente", direccion="D")
        medio1 = Cliente.objects.create(empresa=self.empresa, nombre="Medio 1", direccion="D")
        medio2 = Cliente.objects.create(empresa=self.empresa, nombre="Medio 2", direccion="D")

        # mejor: despachos recientes y frecuentes
        for _ in range(8):
            crear_pedido(self.empresa, mejor, dias_atras=1, hoy=self.hoy)
        # peor: un solo despacho, hace mucho
        crear_pedido(self.empresa, peor, dias_atras=300, hoy=self.hoy)
        # medios: perfiles intermedios distintos entre si
        for _ in range(3):
            crear_pedido(self.empresa, medio1, dias_atras=30, hoy=self.hoy)
        crear_pedido(self.empresa, medio2, dias_atras=90, hoy=self.hoy)

        return mejor, peor

    def test_segmentar_clientes_aplica_kmeans_y_etiqueta_correctamente(self):
        mejor, peor = self._crear_dataset_diverso()

        resultado = analytics.segmentar_clientes(self.empresa, hoy=self.hoy)
        self.assertTrue(resultado["clustering_aplicado"])

        por_id = {c["cliente_id"]: c for c in resultado["clientes"]}
        for c in resultado["clientes"]:
            self.assertIn(c["segmento"], analytics.SEGMENTOS_ORDEN)

        self.assertEqual(por_id[mejor.id]["segmento"], "VIP")
        self.assertEqual(por_id[peor.id]["segmento"], "En riesgo")

    def test_segmentar_clientes_es_determinista(self):
        self._crear_dataset_diverso()

        r1 = analytics.segmentar_clientes(self.empresa, hoy=self.hoy)
        r2 = analytics.segmentar_clientes(self.empresa, hoy=self.hoy)

        mapa1 = {c["cliente_id"]: c["segmento"] for c in r1["clientes"]}
        mapa2 = {c["cliente_id"]: c["segmento"] for c in r2["clientes"]}
        self.assertEqual(mapa1, mapa2)


class AnaliticaViewTests(TestCase):
    def setUp(self):
        self.empresa, self.owner = crear_empresa_con_owner("Panadería Vista", "owner_vista")
        chofer_user = User.objects.create_user(username="chofer_vista", password="Segura123!")
        PerfilUsuario.objects.create(user=chofer_user, rol="CHOFER", empresa=self.empresa)

        self.hoy = date(2026, 6, 15)
        cliente = Cliente.objects.create(
            empresa=self.empresa, nombre="José Muñoz", direccion="D1", comuna="Ñuñoa"
        )
        crear_pedido(self.empresa, cliente, hoy=self.hoy)

    def test_dashboard_requiere_login(self):
        resp = self.client.get(reverse("analitica"))
        self.assertEqual(resp.status_code, 302)

    def test_chofer_no_puede_acceder_a_analitica(self):
        self.client.login(username="chofer_vista", password="Segura123!")
        resp = self.client.get(reverse("analitica"))
        self.assertEqual(resp.status_code, 302)

    def test_owner_puede_ver_analitica_sin_montos(self):
        self.client.login(username="owner_vista", password="Segura123!")
        resp = self.client.get(reverse("analitica"))
        self.assertEqual(resp.status_code, 200)
        for key in ("resumen", "segmentacion", "top_clientes", "conteo_segmentos"):
            self.assertIn(key, resp.context)
        # LogiVisir no maneja dinero de sus empresas clientes
        self.assertNotContains(resp, "$")
        self.assertNotContains(resp, "Ingreso")

    def test_exportar_segmentacion_csv_responde_csv_con_headers_correctos(self):
        self.client.login(username="owner_vista", password="Segura123!")
        resp = self.client.get(reverse("exportar_segmentacion_csv"))
        self.assertTrue(resp["Content-Type"].startswith("text/csv"))
        self.assertIn(".csv", resp["Content-Disposition"])
        self.assertTrue(resp.content.startswith(b"\xef\xbb\xbf"))

        texto = resp.content.decode("utf-8-sig")
        primera_linea = texto.splitlines()[0]
        self.assertEqual(
            primera_linea,
            "cliente_id,nombre,comuna,recencia_dias,frecuencia_despachos,cluster_id,segmento",
        )

    def test_exportar_csv_con_nombre_con_tilde_no_rompe_encoding(self):
        self.client.login(username="owner_vista", password="Segura123!")
        resp = self.client.get(reverse("exportar_segmentacion_csv"))
        texto = resp.content.decode("utf-8-sig")
        self.assertIn("José Muñoz", texto)
        self.assertIn("Ñuñoa", texto)

    def test_exportar_despachos_mensuales_csv_responde_ok(self):
        self.client.login(username="owner_vista", password="Segura123!")
        resp = self.client.get(reverse("exportar_despachos_mensuales_csv"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp["Content-Type"].startswith("text/csv"))
        self.assertEqual(resp.content.decode("utf-8-sig").splitlines()[0], "mes,despachos,clientes_atendidos")


class AislamientoEntreEmpresasAnaliticaTests(TestCase):
    """
    Replica el patron de test_tenancy.py: dos empresas separadas, y ninguna
    vista de analitica debe dejar cruzar despachos/clientes de una a la otra.
    """

    def setUp(self):
        self.hoy = date(2026, 6, 15)
        self.empresa_a, self.owner_a = crear_empresa_con_owner("Empresa A", "owner_a_analytics")
        self.empresa_b, self.owner_b = crear_empresa_con_owner("Empresa B", "owner_b_analytics")

        self.cliente_a = Cliente.objects.create(
            empresa=self.empresa_a, nombre="Cliente Secreto A", direccion="D", comuna="Comuna A"
        )
        self.cliente_b = Cliente.objects.create(
            empresa=self.empresa_b, nombre="Cliente Secreto B", direccion="D", comuna="Comuna B"
        )
        crear_pedido(self.empresa_a, self.cliente_a, hoy=self.hoy)
        for _ in range(5):
            crear_pedido(self.empresa_b, self.cliente_b, hoy=self.hoy)

    def test_analitica_no_filtra_datos_de_otra_empresa(self):
        self.client.login(username="owner_a_analytics", password="Segura123!")
        resp = self.client.get(reverse("analitica"))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["resumen"]["despachos"], 1)
        self.assertNotContains(resp, "Cliente Secreto B")
        self.assertNotContains(resp, "Comuna B")

    def test_export_csv_no_filtra_datos_de_otra_empresa(self):
        self.client.login(username="owner_a_analytics", password="Segura123!")
        resp = self.client.get(reverse("exportar_segmentacion_csv"))
        texto = resp.content.decode("utf-8-sig")

        self.assertIn("Cliente Secreto A", texto)
        self.assertNotIn("Cliente Secreto B", texto)
