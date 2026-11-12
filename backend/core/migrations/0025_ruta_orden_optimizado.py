from django.db import migrations, models


def marcar_optimizadas(apps, schema_editor):
    # Las rutas que ya se optimizaron alguna vez parten como optimizadas.
    Ruta = apps.get_model("core", "Ruta")
    Ruta.objects.filter(optimizada_en__isnull=False).update(orden_optimizado=True)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0024_cliente_ubicacion_pendiente"),
    ]

    operations = [
        migrations.AddField(
            model_name="ruta",
            name="orden_optimizado",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(marcar_optimizadas, migrations.RunPython.noop),
    ]
