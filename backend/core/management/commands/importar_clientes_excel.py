"""
Importa el listado real de clientes de Panaderia Macarron desde el Excel
de rutas que usan hoy (hojas "CLIENTES" y "CLIENTES DELIVERY"). Uso:

    python manage.py importar_clientes_excel "C:\\ruta\\al\\archivo.xlsx" --empresa "Panadería Macarrón"

Es idempotente: si vuelves a correrlo, no duplica clientes ya importados
(se identifican por nombre + direccion dentro de la misma empresa).
"""
import openpyxl
from django.core.management.base import BaseCommand, CommandError

from core.models import Empresa, Cliente

HOJAS_CLIENTES = ["CLIENTES ", "CLIENTES DELIVERY"]


class Command(BaseCommand):
    help = "Importa clientes reales desde el Excel de rutas de la panaderia (hojas CLIENTES / CLIENTES DELIVERY)."

    def add_arguments(self, parser):
        parser.add_argument("archivo", type=str, help="Ruta al archivo .xlsx")
        parser.add_argument("--empresa", type=str, default="Panadería Macarrón")
        parser.add_argument("--ciudad", type=str, default="Santiago")

    def handle(self, *args, **options):
        ruta_archivo = options["archivo"]
        nombre_empresa = options["empresa"]
        ciudad_default = options["ciudad"]

        try:
            empresa = Empresa.objects.get(nombre=nombre_empresa)
        except Empresa.DoesNotExist:
            raise CommandError(
                f"No existe una Empresa llamada '{nombre_empresa}'. "
                "Revisa el nombre exacto o crea la empresa primero."
            )

        try:
            wb = openpyxl.load_workbook(ruta_archivo, data_only=True)
        except FileNotFoundError:
            raise CommandError(f"No se encontró el archivo: {ruta_archivo}")

        filas = []
        for nombre_hoja in HOJAS_CLIENTES:
            if nombre_hoja not in wb.sheetnames:
                self.stdout.write(self.style.WARNING(f"Hoja '{nombre_hoja}' no encontrada, se omite."))
                continue
            ws = wb[nombre_hoja]
            for row in ws.iter_rows(min_row=2, values_only=True):
                fantasia, direccion, comuna = row[1], row[2], row[3]
                if not fantasia or not direccion:
                    continue
                filas.append({
                    "nombre": str(fantasia).strip(),
                    "direccion": str(direccion).strip(),
                    "comuna": str(comuna).strip() if comuna else "",
                })

        # Dedup por (nombre, direccion) en mayusculas, conservando la ultima aparicion
        vistos = {}
        for f in filas:
            clave = (f["nombre"].upper(), f["direccion"].upper())
            vistos[clave] = f

        creados = 0
        existentes = 0

        for f in vistos.values():
            nombre = f["nombre"].title()
            direccion = f["direccion"].title()
            comuna = f["comuna"].title() if f["comuna"] else ""

            ya_existe = Cliente.objects.filter(
                empresa=empresa, nombre__iexact=nombre, direccion__iexact=direccion
            ).exists()
            if ya_existe:
                existentes += 1
                continue

            Cliente.objects.create(
                empresa=empresa,
                nombre=nombre,
                direccion=direccion,
                comuna=comuna,
                ciudad=ciudad_default,
                activo=True,
            )
            creados += 1

        self.stdout.write(self.style.SUCCESS(
            f"Listo. Clientes creados: {creados}. Ya existian (omitidos): {existentes}."
        ))
        self.stdout.write(
            "Nota: estos clientes NO quedaron geocodificados todavia (son muchos y "
            "Nominatim tiene limite de ~1 request/seg). Corre por separado:\n"
            "  python manage.py regeocodificar_clientes\n"
            "cuando quieras (puede demorar bastante con este volumen)."
        )
