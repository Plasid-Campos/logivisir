from django.db import migrations


NOMBRE_EMPRESA_DEFECTO = "Panadería Macarrón"


def backfill_empresa(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Empresa = apps.get_model("core", "Empresa")
    PerfilUsuario = apps.get_model("core", "PerfilUsuario")
    Cliente = apps.get_model("core", "Cliente")
    Ruta = apps.get_model("core", "Ruta")

    if not PerfilUsuario.objects.exists():
        return

    owner_perfil = PerfilUsuario.objects.filter(rol="OWNER").order_by("id").first()
    owner_user = owner_perfil.user if owner_perfil else User.objects.order_by("id").first()

    if owner_user is None:
        return

    empresa, _ = Empresa.objects.get_or_create(
        nombre=NOMBRE_EMPRESA_DEFECTO,
        defaults={
            "owner": owner_user,
            "direccion_origen": "Salesianos 768",
            "comuna_origen": "San Miguel",
            "ciudad_origen": "Santiago",
        },
    )

    PerfilUsuario.objects.filter(empresa__isnull=True).update(empresa=empresa)
    Cliente.objects.filter(empresa__isnull=True).update(empresa=empresa)
    Ruta.objects.filter(empresa__isnull=True).update(empresa=empresa)


def revertir(apps, schema_editor):
    # No-op: revertir dejaria filas huerfanas sin empresa a proposito no es
    # deseable; si hay que revertir el retrofit completo se hace bajando
    # tambien la migracion 0008.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_cliente_geocodificado_cliente_latitud_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_empresa, revertir),
    ]
