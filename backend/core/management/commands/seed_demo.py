"""
Puebla la base con datos de demostración (ficticios) para poder probar
Logivisir de punta a punta sin cargar información real de clientes.

    python manage.py seed_demo            # crea la empresa demo si no existe
    python manage.py seed_demo --reset    # la borra y la vuelve a crear

Usuarios que deja creados (contraseña: demo12345):
    owner_demo    -> Dueño   (panel completo + analítica)
    admin_demo    -> Administrador
    chofer_demo   -> Chofer  (panel de reparto del día)

Todas las direcciones y coordenadas son inventadas pero verosímiles
(comunas de Santiago) para que el optimizador de rutas funcione sin
salir a internet a geocodificar.
"""
from datetime import timedelta
from decimal import Decimal
import random

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import (
    Empresa, PerfilUsuario, Chofer, Cliente, Producto,
    Pedido, PedidoItem, Ruta, ParadaRuta,
)

EMPRESA_NOMBRE = "Panadería Demo"
PASSWORD = "demo12345"

ORIGEN = {
    "direccion_origen": "Av. Manuel Antonio Matta 1234",
    "comuna_origen": "Santiago",
    "ciudad_origen": "Santiago",
    "latitud_origen": -33.4550,
    "longitud_origen": -70.6580,
}

PRODUCTOS = [
    ("Marraqueta (kg)", "El pan de cada día, crujiente.", 1900, "kg"),
    ("Hallulla (kg)", "Redonda y suave.", 1900, "kg"),
    ("Pan integral (kg)", "Harina integral y semillas.", 2600, "kg"),
    ("Empanada de pino", "Horneada, receta de la casa.", 1800, "unidad"),
    ("Empanada de queso", "Bien rellena.", 1600, "unidad"),
    ("Berlín con crema pastelera", "Clásico de vitrina.", 1200, "unidad"),
    ("Torta tres leches (porción)", "Húmeda, para el once.", 2500, "unidad"),
    ("Pan de molde artesanal", "Sin conservantes, dura 4 días.", 3200, "unidad"),
    ("Croissant de mantequilla", "Hojaldre de verdad.", 1500, "unidad"),
    ("Alfajor de manjar", "Bañado en chocolate.", 1300, "unidad"),
    ("Kuchen de nuez", "Para pedidos grandes.", 12000, "unidad"),
    ("Bebida 1.5 L", "Para acompañar el reparto.", 2200, "unidad"),
]

# (nombre, comuna, direccion, lat, lon, perfil_rfm, tipo)
# perfil_rfm controla cuántos pedidos y qué tan recientes se generan.
CLIENTES = [
    ("Almacén Doña Rosa",        "Providencia",   "Av. Providencia 2145",   -33.4258, -70.6160, "vip",       "NORMAL"),
    ("Cafetería El Rincón",      "Ñuñoa",         "Irarrázaval 3410",       -33.4562, -70.5975, "vip",       "NORMAL"),
    ("Minimarket Las Tres T",    "Las Condes",    "Apoquindo 4501",         -33.4110, -70.5695, "vip",       "NORMAL"),
    ("Hotel Plaza Norte",        "Santiago",      "San Antonio 480",        -33.4405, -70.6490, "vip",       "NORMAL"),
    ("Kiosco Estación",          "Santiago",      "Alameda 3355",           -33.4520, -70.6870, "frecuente", "NORMAL"),
    ("Botillería El Roble",      "San Miguel",    "Gran Avenida 5200",      -33.4975, -70.6520, "frecuente", "NORMAL"),
    ("Casino Empresa TecnoSur",  "Macul",         "Quilín 3100",            -33.4895, -70.5990, "frecuente", "NORMAL"),
    ("Jardín Infantil Girasol",  "Peñalolén",     "Consistorial 2450",      -33.4780, -70.5415, "frecuente", "DELIVERY"),
    ("Almacén San Pedro",        "La Florida",    "Vicuña Mackenna 8850",   -33.5325, -70.5985, "ocasional", "NORMAL"),
    ("Verdulería La Chacra",     "Maipú",         "Av. Pajaritos 2900",     -33.4880, -70.7590, "ocasional", "DELIVERY"),
    ("Panadería aliada El Sol",  "Puente Alto",   "Concha y Toro 1450",     -33.6115, -70.5765, "ocasional", "NORMAL"),
    ("Café de la Villa",         "Ñuñoa",         "Grecia 1855",            -33.4600, -70.5860, "ocasional", "NORMAL"),
    ("Local eventos Doña Marta", "La Florida",    "Walker Martínez 1600",   -33.5420, -70.5810, "en_riesgo", "DELIVERY"),
    ("Quiosco Parque O'Higgins", "Santiago",      "Av. Matta 900",          -33.4630, -70.6470, "en_riesgo", "NORMAL"),
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

        owner_user = self._usuario("owner_demo", "Camila", "Rojas")
        admin_user = self._usuario("admin_demo", "Diego", "Fuentes")
        chofer_user = self._usuario("chofer_demo", "Marco", "Peña")

        empresa = Empresa.objects.create(
            nombre=EMPRESA_NOMBRE, rut_empresa="77.123.456-7",
            owner=owner_user, **ORIGEN,
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

        productos = [
            Producto.objects.create(
                empresa=empresa, nombre=n, descripcion=d,
                precio=Decimal(p), unidad=u, stock_disponible=500,
            )
            for (n, d, p, u) in PRODUCTOS
        ]

        clientes = []
        for (nombre, comuna, direccion, lat, lon, perfil, tipo) in CLIENTES:
            clientes.append((Cliente.objects.create(
                empresa=empresa, tipo_cliente=tipo, nombre=nombre,
                direccion=direccion, comuna=comuna, ciudad="Santiago",
                telefono=f"+56 9 {random.randint(3000, 9999)} {random.randint(1000, 9999)}",
                email=f"{nombre.split()[0].lower()}@ejemplo.cl",
                rut=f"{random.randint(60, 99)}.{random.randint(100,999)}.{random.randint(100,999)}-{random.randint(0,9)}",
                latitud=lat + random.uniform(-0.004, 0.004),
                longitud=lon + random.uniform(-0.004, 0.004),
                geocodificado=True,
            ), perfil))

        self._generar_pedidos(empresa, clientes, productos, owner_user)
        self._generar_ruta_de_hoy(empresa, chofer, clientes)

        self.stdout.write(self.style.SUCCESS(
            f'Listo. Empresa "{EMPRESA_NOMBRE}" creada con '
            f"{len(clientes)} clientes, {Pedido.objects.filter(empresa=empresa).count()} pedidos "
            f"y una ruta para hoy.\n"
            f"Entra en /login con  owner_demo  /  {PASSWORD}"
        ))

    # ---------------------------------------------------------------

    def _usuario(self, username, first, last):
        User.objects.filter(username=username).delete()
        return User.objects.create_user(
            username=username, password=PASSWORD,
            first_name=first, last_name=last,
            email=f"{username}@ejemplo.cl",
        )

    def _borrar(self, empresa):
        usernames = list(
            User.objects.filter(perfilusuario__empresa=empresa).values_list("username", flat=True)
        )
        empresa.delete()  # cascada: perfiles, clientes, rutas, pedidos, productos
        User.objects.filter(username__in=usernames).delete()
        self.stdout.write(self.style.WARNING(f'Empresa "{empresa.nombre}" anterior eliminada.'))

    def _generar_pedidos(self, empresa, clientes, productos, creado_por):
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
                    creado_por=creado_por,
                )
                for producto in random.sample(productos, random.randint(2, 5)):
                    cantidad = random.randint(1, 6)
                    PedidoItem.objects.create(
                        pedido=pedido, producto=producto, cantidad=cantidad,
                        precio_unitario=producto.precio,
                    )
                pedido.recalcular_total()
                # creado_en es auto_now_add: se corrige por UPDATE directo.
                Pedido.objects.filter(pk=pedido.pk).update(creado_en=creado)

        # algunos pedidos vivos (aún no entregados) para el panel de pendientes
        for cliente, _ in random.sample(clientes, 5):
            pedido = Pedido.objects.create(
                empresa=empresa, cliente=cliente, estado="PENDIENTE",
                creado_por=creado_por,
            )
            for producto in random.sample(productos, random.randint(2, 4)):
                PedidoItem.objects.create(
                    pedido=pedido, producto=producto, cantidad=random.randint(1, 4),
                    precio_unitario=producto.precio,
                )
            pedido.recalcular_total()

    def _generar_ruta_de_hoy(self, empresa, chofer, clientes):
        hoy = timezone.localdate()
        ruta = Ruta.objects.create(
            empresa=empresa, nombre=f"Reparto {hoy.strftime('%d-%m')}",
            fecha=hoy, chofer=chofer, estado="PLANIFICADA",
        )
        seleccion = [c for (c, _) in clientes][:9]
        for orden, cliente in enumerate(seleccion, start=1):
            ParadaRuta.objects.create(
                ruta=ruta, cliente=cliente, orden=orden,
                estado_entrega="PENDIENTE",
            )
