"""
Puebla la base con datos de demostración (ficticios) para poder probar
Logivisir de punta a punta sin cargar información real de clientes.

    python manage.py seed_demo            # crea la empresa demo si no existe
    python manage.py seed_demo --reset    # la borra y la vuelve a crear

Usuarios que deja creados (contraseña: demo12345):
    equipo_logivisir -> Equipo LogiVisir (panel, empresas, usuarios, pagos y solicitudes;
                      no ve clientes, rutas ni pedidos de ninguna empresa)
    panaderia_dueno  -> Dueña de la Panadería Demo (todo + usuarios de su empresa)
    panaderia_admin  -> Administrador de la Panadería Demo (operación diaria)
    panaderia_chofer -> Chofer de la Panadería Demo (panel de reparto del día)
    loaguirre_dueno, loaguirre_admin, loaguirre_chofer1 -> Distribuidora Lo Aguirre (demo)

Los nombres de los clientes son inventados, pero las direcciones son
reales: cada una se verificó con Nominatim (OpenStreetMap) con su número
de calle, y las coordenadas son las de ese número. Así Google Maps y el
optimizador llevan a lugares que existen. La panadería sale de Salesianos
768, San Miguel (la dirección de la panadería piloto).
"""
from datetime import timedelta
import random

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.notifications import fecha_legible, url_ruta_chofer
from core.optimizer import _distancia_total, optimizar_ruta
from core.membresias import PRECIOS_PLAN, sumar_meses

from core.models import (
    Empresa, PerfilUsuario, Chofer, Cliente,
    Pedido, Ruta, ParadaRuta, SolicitudCuenta, Notificacion, Pago,
)

EMPRESA_NOMBRE = "Panadería Demo"
SEGUNDA_EMPRESA = "Distribuidora Lo Aguirre (demo)"
SOLICITUDES_DEMO = (EMPRESA_NOMBRE, "Distribuidora Los Andes (demo)", SEGUNDA_EMPRESA)

# Segunda empresa cliente, más chica, para que el panel del equipo LogiVisir
# compare membresías, ubicación y uso entre empresas. Nombres inventados.
ORIGEN_LO_AGUIRRE = {
    "direccion_origen": "Avenida Pajaritos 2500",
    "comuna_origen": "Maipú",
    "ciudad_origen": "Santiago",
    "latitud_origen": -33.5095,
    "longitud_origen": -70.7570,
}
CLIENTES_LO_AGUIRRE = [
    ("Almacén La Esquina", "Avenida Pajaritos 1800", -33.5040, -70.7520),
    ("Minimarket El Trébol", "Avenida 5 de Abril 300", -33.5130, -70.7610),
    ("Botillería Los Héroes", "Avenida Los Pajaritos 3200", -33.5150, -70.7660),
    ("Kiosco Plaza Maipú", "Avenida 5 de Abril 50", -33.5105, -70.7565),
    ("Almacén Santa Ana", "Camino a Rinconada 900", -33.5230, -70.7740),
    ("Supermercado Del Valle", "Avenida Sur 1500", -33.4990, -70.7690),
]
PASSWORD = "demo12345"

ORIGEN = {
    "direccion_origen": "Avenida Salesianos 768",
    "comuna_origen": "San Miguel",
    "ciudad_origen": "Santiago",
    "latitud_origen": -33.494197,
    "longitud_origen": -70.644544,
}

STAFF_USERNAME = "equipo_logivisir"
# Nombres usados hasta noviembre de 2026: se borran al recrear la demo.
USUARIOS_ANTIGUOS = ("owner_demo", "admin_demo", "chofer_demo", "logivisir_demo")

# Solo para describir que se despacha en cada pedido (texto libre, sin precios:
# LogiVisir no maneja montos del negocio de sus empresas clientes).
ARTICULOS = [
    ("kg de marraqueta", (5, 20)),
    ("kg de hallulla", (3, 15)),
    ("kg de pan integral", (2, 8)),
    ("empanadas de pino", (12, 48)),
    ("empanadas de queso", (12, 36)),
    ("berlines", (10, 30)),
    ("porciones de torta", (6, 20)),
    ("panes de molde", (4, 12)),
    ("croissants", (10, 40)),
    ("alfajores", (12, 36)),
]

MOTIVOS_NO_ENTREGA = (
    "Local cerrado",
    "Cliente no recibió",
    "Dirección no encontrada",
)

# (nombre, comuna, direccion, lat, lon, perfil_rfm, tipo)
# perfil_rfm controla cuántos pedidos y qué tan recientes se generan.
CLIENTES = [
    ("Almacén Doña Rosa",        "San Miguel",          "Gran Avenida José Miguel Carrera 4400", -33.494342, -70.652075, "vip",       "NORMAL"),
    ("Cafetería El Rincón",      "San Joaquín",         "Avenida Santa Rosa 3100",               -33.483792, -70.641111, "vip",       "NORMAL"),
    ("Minimarket Las Tres T",    "San Miguel",          "Carlos Edwards 1200",                   -33.501140, -70.656432, "vip",       "NORMAL"),
    ("Hotel Plaza Sur",          "Santiago",            "San Diego 1900",                        -33.471177, -70.648328, "vip",       "NORMAL"),
    ("Kiosco Estación Franklin", "Santiago",            "Franklin 700",                          -33.473014, -70.641905, "frecuente", "NORMAL"),
    ("Botillería El Roble",      "San Miguel",          "Gran Avenida José Miguel Carrera 5800", -33.507722, -70.655929, "frecuente", "NORMAL"),
    ("Casino Empresa TecnoSur",  "Macul",               "Avenida Macul 2800",                    -33.480197, -70.598969, "frecuente", "NORMAL"),
    ("Jardín Infantil Girasol",  "Santiago",            "San Francisco 1800",                    -33.468963, -70.643921, "frecuente", "DELIVERY"),
    ("Almacén San Pedro",        "San Miguel",          "Avenida Lo Ovalle 800",                 -33.512440, -70.665939, "ocasional", "NORMAL"),
    ("Verdulería La Chacra",     "La Cisterna",         "Avenida El Parrón 600",                 -33.524443, -70.667523, "ocasional", "DELIVERY"),
    ("Panadería aliada El Sol",  "La Granja",           "Avenida Santa Rosa 7500",               -33.527076, -70.635502, "ocasional", "NORMAL"),
    ("Café de la Villa",         "Ñuñoa",               "Avenida Grecia 1500",                   -33.461390, -70.616384, "ocasional", "NORMAL"),
    ("Colegio San Ignacio Sur",  "Santiago",            "San Ignacio de Loyola 1500",            -33.466590, -70.654796, "ocasional", "NORMAL"),
    ("Local eventos Doña Marta", "Santiago",            "Avenida Santa Rosa 2000",               -33.471805, -70.641928, "en_riesgo", "DELIVERY"),
    ("Minimarket Don Lucho",     "Macul",               "Avenida Macul 4500",                    -33.494921, -70.599160, "en_riesgo", "NORMAL"),
    ("Fuente de soda La Esquina", "La Cisterna",        "Avenida El Parrón 1000",                -33.528163, -70.650370, "en_riesgo", "NORMAL"),
]

PERFIL_PEDIDOS = {
    # perfil: (nº pedidos, días desde la última compra aprox.)
    "vip":       (12, 4),
    "frecuente": (6, 12),
    "ocasional": (3, 45),
    "en_riesgo": (2, 120),
}


class Command(BaseCommand):
    help = "Crea una empresa de demostración con datos ficticios."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true",
            help="Borra la empresa demo y la vuelve a crear desde cero.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(42)
        existente = Empresa.objects.filter(nombre=EMPRESA_NOMBRE).first()
        if existente:
            if not options["reset"]:
                self.stdout.write(self.style.WARNING(
                    f'"{EMPRESA_NOMBRE}" ya existe. Usa --reset para recrearla.'
                ))
                return
            self._borrar(existente)
        segunda = Empresa.objects.filter(nombre=SEGUNDA_EMPRESA).first()
        if segunda:
            self._borrar(segunda)

        User.objects.filter(username__in=USUARIOS_ANTIGUOS).delete()
        owner_user = self._usuario("panaderia_dueno", "Camila", "Rojas")
        admin_user = self._usuario("panaderia_admin", "Diego", "Fuentes")
        chofer_user = self._usuario("panaderia_chofer", "Marco", "Peña")

        empresa = Empresa.objects.create(
            nombre=EMPRESA_NOMBRE, rut_empresa="77.123.456-9",
            owner=owner_user, plan="PRO",
            suscripcion_vence=timezone.localdate() + timedelta(days=18),
            **ORIGEN,
        )
        PerfilUsuario.objects.create(user=owner_user, empresa=empresa, rol="OWNER")
        PerfilUsuario.objects.create(user=admin_user, empresa=empresa, rol="ADMIN")
        perfil_chofer = PerfilUsuario.objects.create(
            user=chofer_user, empresa=empresa, rol="CHOFER",
        )
        chofer = Chofer.objects.create(
            perfil=perfil_chofer, rut="16.842.115-3",
            telefono="+56 9 6543 2100", licencia="Clase B", patente="LLXR-42",
        )

        self._staff_y_solicitudes(empresa)
        self._historial_pagos(empresa, "PRO", periodos=4)

        clientes = []
        for (nombre, comuna, direccion, lat, lon, perfil, tipo) in CLIENTES:
            clientes.append((Cliente.objects.create(
                empresa=empresa, tipo_cliente=tipo, nombre=nombre,
                direccion=direccion, comuna=comuna, ciudad="Santiago",
                telefono=f"+56 9 {random.randint(3000, 9999)} {random.randint(1000, 9999)}",
                email=f"{nombre.split()[0].lower()}@example.com",
                rut=f"{random.randint(60, 99)}.{random.randint(100,999)}.{random.randint(100,999)}-{random.randint(0,9)}",
                latitud=lat,
                longitud=lon,
                geocodificado=True,
            ), perfil))

        self._generar_pedidos(empresa, clientes, owner_user)
        self._generar_rutas_pasadas(empresa, chofer)
        self._generar_ruta_de_hoy(empresa, chofer, clientes)
        self._ultimos_ingresos([owner_user, admin_user, chofer_user])
        self._segunda_empresa()

        self.stdout.write(self.style.SUCCESS(
            f'Listo. Empresa "{EMPRESA_NOMBRE}" creada con '
            f"{len(clientes)} clientes, {Pedido.objects.filter(empresa=empresa).count()} pedidos "
            f"y una ruta para hoy.\n"
            f"Usuarios (clave {PASSWORD} en todos):\n"
            f"  {STAFF_USERNAME:<18} equipo LogiVisir\n"
            f"  panaderia_dueno    dueña de la Panadería Demo\n"
            f"  panaderia_admin    administrador de la Panadería Demo\n"
            f"  panaderia_chofer   chofer de la Panadería Demo\n"
            f"  loaguirre_dueno    dueña de Distribuidora Lo Aguirre (demo)"
        ))

    # ---------------------------------------------------------------

    def _historial_pagos(self, empresa, plan, periodos):
        """
        Pagos mensuales hacia atrás desde el vencimiento actual, pagados 2 días
        antes de cada período (datos del negocio de LogiVisir, ficticios).
        """
        hoy = timezone.localdate()
        staff = User.objects.filter(username=STAFF_USERNAME).first()
        hasta = empresa.suscripcion_vence
        for _ in range(periodos):
            desde = sumar_meses(hasta + timedelta(days=1), -1)
            anterior = desde - timedelta(days=1)
            Pago.objects.create(
                empresa=empresa, plan=plan, monto=PRECIOS_PLAN[plan],
                fecha_pago=min(desde - timedelta(days=2), hoy), meses=1,
                periodo_desde=desde, periodo_hasta=hasta, medio="TRANSFERENCIA",
                referencia=f"TRF-{random.randint(10000, 99999)}", vence_anterior=anterior,
                registrado_por=staff,
            )
            hasta = anterior

    def _ultimos_ingresos(self, usuarios):
        ahora = timezone.now()
        for i, u in enumerate(usuarios):
            u.last_login = ahora - timedelta(hours=2 + i * 5)
            u.save(update_fields=["last_login"])

    def _registrar_optimizacion(self, ruta, origen):
        """Guarda los km antes/después como si la ruta se hubiera optimizado ese día."""
        paradas = list(ruta.paradas.select_related("cliente"))
        puntos = [(p.id, p.cliente.latitud, p.cliente.longitud) for p in paradas if p.cliente.latitud is not None]
        if len(puntos) < 2:
            return
        ingreso = [pid for pid, _, _ in puntos]
        optimo = optimizar_ruta(origen, puntos)
        momento = timezone.make_aware(timezone.datetime.combine(ruta.fecha, timezone.datetime.min.time())) + timedelta(hours=6)
        Ruta.objects.filter(id=ruta.id).update(
            km_antes=round(_distancia_total(origen, puntos, ingreso), 1),
            km_despues=round(_distancia_total(origen, puntos, optimo), 1),
            optimizada_en=momento, creada_en=momento - timedelta(hours=12),
        )

    def _segunda_empresa(self):
        hoy = timezone.localdate()
        dueno = self._usuario("loaguirre_dueno", "Patricia", "Aguirre")
        admin = self._usuario("loaguirre_admin", "Jorge", "Muñoz")
        chofer1 = self._usuario("loaguirre_chofer1", "Luis", "Soto")
        chofer2 = self._usuario("loaguirre_chofer2", "Pedro", "Vera")
        empresa = Empresa.objects.create(
            nombre=SEGUNDA_EMPRESA, rut_empresa="76.555.210-9", owner=dueno,
            plan="BASICO", suscripcion_vence=hoy + timedelta(days=5),
            **ORIGEN_LO_AGUIRRE,
        )
        PerfilUsuario.objects.create(user=dueno, empresa=empresa, rol="OWNER")
        PerfilUsuario.objects.create(user=admin, empresa=empresa, rol="ADMIN")
        p1 = PerfilUsuario.objects.create(user=chofer1, empresa=empresa, rol="CHOFER")
        p2 = PerfilUsuario.objects.create(
            user=chofer2, empresa=empresa, rol="CHOFER",
            desactivado_en=timezone.now() - timedelta(days=9),
        )
        chofer2.is_active = False
        chofer2.save(update_fields=["is_active"])
        chofer = Chofer.objects.create(perfil=p1, rut="17.321.654-0", licencia="Clase A2", patente="KTRS-19")
        Chofer.objects.create(perfil=p2, rut="18.456.789-2", licencia="Clase B", patente="JJPL-55", activo=False)
        self._ultimos_ingresos([dueno, admin, chofer1])
        self._historial_pagos(empresa, "BASICO", periodos=2)
        SolicitudCuenta.objects.create(
            nombre_empresa=SEGUNDA_EMPRESA, nombre_contacto="Patricia Aguirre",
            email_contacto="loaguirre_dueno@example.com", telefono_contacto="+56 9 7777 2211",
            rubro="Distribución de abarrotes", plan_solicitado="BASICO", estado="CUENTA_CREADA",
            empresa_creada=empresa, rut_empresa="76.555.210-9",
            direccion=ORIGEN_LO_AGUIRRE["direccion_origen"], comuna="Maipú", ciudad="Santiago",
        )
        clientes = [
            Cliente.objects.create(
                empresa=empresa, nombre=n, direccion=d, comuna="Maipú", ciudad="Santiago",
                latitud=lat, longitud=lon, geocodificado=True,
            )
            for n, d, lat, lon in CLIENTES_LO_AGUIRRE
        ]
        origen = (ORIGEN_LO_AGUIRRE["latitud_origen"], ORIGEN_LO_AGUIRRE["longitud_origen"])
        for dias in (2, 6, 9, 13, 16, 20, 27):
            fecha = hoy - timedelta(days=dias)
            ruta = Ruta.objects.create(
                empresa=empresa, nombre=f"Reparto {fecha.strftime('%d-%m')}",
                fecha=fecha, chofer=chofer, estado="COMPLETADA",
            )
            elegidos = random.sample(clientes, 5)
            for orden, cliente in enumerate(elegidos, start=1):
                ParadaRuta.objects.create(
                    ruta=ruta, cliente=cliente, orden=orden,
                    estado_entrega="ENTREGADO", entregado=True,
                )
            self._registrar_optimizacion(ruta, origen)

    def _usuario(self, username, first, last):
        User.objects.filter(username=username).delete()
        return User.objects.create_user(
            username=username, password=PASSWORD,
            first_name=first, last_name=last,
            email=f"{username}@example.com",
        )

    def _borrar(self, empresa):
        usernames = list(
            User.objects.filter(perfilusuario__empresa=empresa).values_list("username", flat=True)
        )
        SolicitudCuenta.objects.filter(nombre_empresa__in=SOLICITUDES_DEMO).delete()
        # ParadaRuta.cliente y Pedido.cliente son PROTECT: hay que borrarlos
        # antes que la empresa, o la cascada hacia Cliente se bloquea.
        ParadaRuta.objects.filter(ruta__empresa=empresa).delete()
        Pedido.objects.filter(empresa=empresa).delete()
        Ruta.objects.filter(empresa=empresa).delete()
        empresa.delete()  # cascada: perfiles, choferes, clientes
        User.objects.filter(username__in=usernames).delete()
        self.stdout.write(self.style.WARNING(f'Empresa "{empresa.nombre}" anterior eliminada.'))

    def _staff_y_solicitudes(self, empresa):
        """
        Usuario del equipo LogiVisir (is_staff, sin empresa) y solicitudes de
        ejemplo: la que dio origen a la Panaderia Demo y una nueva por revisar.
        """
        staff = self._usuario(STAFF_USERNAME, "Equipo", "LogiVisir")
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])

        SolicitudCuenta.objects.filter(nombre_empresa__in=SOLICITUDES_DEMO).delete()
        SolicitudCuenta.objects.create(
            nombre_empresa=EMPRESA_NOMBRE, nombre_contacto="Camila Rojas",
            email_contacto="panaderia_dueno@example.com", telefono_contacto="+56 9 5555 1234",
            rubro="Panadería", plan_solicitado="PRO", estado="CUENTA_CREADA",
            empresa_creada=empresa, rut_empresa="77.123.456-9",
            direccion=ORIGEN["direccion_origen"], comuna=ORIGEN["comuna_origen"], ciudad="Santiago",
        )
        SolicitudCuenta.objects.create(
            nombre_empresa="Distribuidora Los Andes (demo)", nombre_contacto="Rodrigo Saavedra",
            email_contacto="contacto.losandes@example.com", telefono_contacto="+56 9 4444 7788",
            rubro="Distribución de abarrotes", plan_solicitado="BASICO",
            mensaje="Tenemos 2 camionetas y unos 80 clientes en la zona sur de Santiago.",
            rut_empresa="76.543.210-3", direccion="Avenida La Florida 9500", comuna="La Florida",
            ciudad="Santiago",
        )

    def _nota_despacho(self):
        partes = []
        for nombre, (minimo, maximo) in random.sample(ARTICULOS, random.randint(2, 4)):
            partes.append(f"{random.randint(minimo, maximo)} {nombre}")
        return ", ".join(partes)

    def _generar_pedidos(self, empresa, clientes, creado_por):
        ahora = timezone.now()
        for cliente, perfil in clientes:
            n_pedidos, dias_ultima = PERFIL_PEDIDOS[perfil]
            for i in range(n_pedidos):
                # el pedido i más nuevo es "dias_ultima" atrás; los demás se
                # reparten hacia el pasado en tramos de ~20 días.
                dias_atras = dias_ultima + i * random.randint(12, 28)
                creado = ahora - timedelta(days=dias_atras, hours=random.randint(0, 10))

                pedido = Pedido.objects.create(
                    empresa=empresa, cliente=cliente, estado="ENTREGADO",
                    nota=self._nota_despacho(), creado_por=creado_por,
                )
                # creado_en es auto_now_add: se corrige por UPDATE directo.
                Pedido.objects.filter(pk=pedido.pk).update(creado_en=creado)

        # algunos pedidos vivos (aún no entregados) para el panel de pendientes
        for cliente, _ in random.sample(clientes, 5):
            Pedido.objects.create(
                empresa=empresa, cliente=cliente, estado="PENDIENTE",
                nota=self._nota_despacho(), creado_por=creado_por,
            )

    def _generar_rutas_pasadas(self, empresa, chofer):
        """
        Rutas ya realizadas en los ultimos 45 dias, una por cada dia con
        despachos, para que el historial y el indicador de entregas al primer
        intento tengan datos. Algunas paradas quedan como NO_ENTREGADO con su
        motivo, sin pedido asociado. No se generan fotos de entrega: esas
        solo las sube el chofer desde su panel.
        """
        hoy = timezone.localdate()
        desde = hoy - timedelta(days=45)
        pedidos = Pedido.objects.filter(
            empresa=empresa, estado="ENTREGADO", creado_en__date__gte=desde,
        ).select_related("cliente").order_by("creado_en")

        por_dia = {}
        for pedido in pedidos:
            por_dia.setdefault(timezone.localtime(pedido.creado_en).date(), []).append(pedido)

        clientes = list(Cliente.objects.filter(empresa=empresa))
        for n_ruta, (fecha, pedidos_dia) in enumerate(por_dia.items()):
            ruta = Ruta.objects.create(
                empresa=empresa, nombre=f"Reparto {fecha.strftime('%d-%m')}",
                fecha=fecha, chofer=chofer, estado="COMPLETADA",
            )
            orden = 0
            for pedido in pedidos_dia:
                orden += 1
                ParadaRuta.objects.create(
                    ruta=ruta, cliente=pedido.cliente, orden=orden, pedido=pedido,
                    estado_entrega="ENTREGADO", entregado=True,
                )
            self._registrar_optimizacion(ruta, (empresa.latitud_origen, empresa.longitud_origen))
            if n_ruta % 4 == 3:  # una parada fallida cada 4 rutas
                orden += 1
                ParadaRuta.objects.create(
                    ruta=ruta, cliente=random.choice(clientes), orden=orden,
                    estado_entrega="NO_ENTREGADO",
                    motivo_no_entrega=random.choice(MOTIVOS_NO_ENTREGA),
                )

    def _generar_ruta_de_hoy(self, empresa, chofer, clientes):
        hoy = timezone.localdate()
        ruta = Ruta.objects.create(
            empresa=empresa, nombre=f"Reparto {hoy.strftime('%d-%m')}",
            fecha=hoy, chofer=chofer, estado="PLANIFICADA",
        )
        # 12 paradas: más que las 9 intermedias que acepta Google Maps por
        # enlace, para que se vea la división en tramos del panel del chofer.
        seleccion = [c for (c, _) in clientes][:12]
        for orden, cliente in enumerate(seleccion, start=1):
            ParadaRuta.objects.create(
                ruta=ruta, cliente=cliente, orden=orden,
                estado_entrega="PENDIENTE",
            )

        # Ruta de mañana, recién asignada: el chofer la ve con un aviso sin
        # leer en la campana. El aviso de la de hoy ya está leído.
        manana = hoy + timedelta(days=1)
        ruta_manana = Ruta.objects.create(
            empresa=empresa, nombre=f"Reparto {manana.strftime('%d-%m')}",
            fecha=manana, chofer=chofer, estado="PLANIFICADA",
        )
        for orden, cliente in enumerate([c for (c, _) in clientes][4:10], start=1):
            ParadaRuta.objects.create(ruta=ruta_manana, cliente=cliente, orden=orden)

        usuario_chofer = chofer.perfil.user
        Notificacion.objects.filter(usuario=usuario_chofer).delete()
        for r, leida in ((ruta, True), (ruta_manana, False)):
            Notificacion.objects.create(
                usuario=usuario_chofer, tipo="RUTA_ASIGNADA", ruta=r, leida=leida,
                titulo=f"Nueva ruta: {r.nombre}",
                mensaje=f"Para {fecha_legible(r.fecha)}. {r.paradas.count()} paradas.",
                url=url_ruta_chofer(r),
            )
