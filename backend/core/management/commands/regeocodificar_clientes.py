import time

from django.core.management.base import BaseCommand

from core.models import Cliente, Empresa
from core.geocoding import geocodificar_cliente, geocodificar_empresa


class Command(BaseCommand):
    help = (
        "Geocodifica (asigna latitud/longitud) a los Cliente y Empresa que "
        "todavia no tienen coordenadas. Util para backfill despues de "
        "activar el optimizador de rutas sobre datos ya existentes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--todos",
            action="store_true",
            help="Re-geocodificar tambien los que ya tienen coordenadas.",
        )

    def handle(self, *args, **options):
        todos = options["todos"]

        empresas = Empresa.objects.all() if todos else Empresa.objects.filter(latitud_origen__isnull=True)
        for empresa in empresas:
            if not empresa.direccion_origen:
                continue
            ok = geocodificar_empresa(empresa)
            self.stdout.write(
                f"Empresa '{empresa.nombre}': {'OK' if ok else 'no se pudo geocodificar'}"
            )
            time.sleep(1)  # limite de uso razonable de Nominatim (~1 req/seg)

        clientes = Cliente.objects.all() if todos else Cliente.objects.filter(geocodificado=False)
        total = clientes.count()
        self.stdout.write(f"Geocodificando {total} cliente(s)...")

        exitosos = 0
        for cliente in clientes:
            ok = geocodificar_cliente(cliente)
            exitosos += int(ok)
            self.stdout.write(f"  - {cliente.nombre}: {'OK' if ok else 'no se pudo ubicar'}")
            time.sleep(1)

        self.stdout.write(self.style.SUCCESS(f"Listo: {exitosos}/{total} clientes geocodificados."))
