import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Endurece empresa a NOT NULL en PerfilUsuario/Cliente/Ruta ahora que la
    migracion de datos 0009 ya dejo todas las filas existentes asignadas a
    una Empresa. Escrita a mano (en vez de generada por makemigrations)
    porque el autodetector pide un default interactivo que no aplica aqui:
    ya verificamos que no quedan filas con empresa NULL.
    """

    dependencies = [
        ("core", "0009_backfill_empresa_por_defecto"),
    ]

    operations = [
        migrations.AlterField(
            model_name="perfilusuario",
            name="empresa",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="perfiles",
                to="core.empresa",
            ),
        ),
        migrations.AlterField(
            model_name="cliente",
            name="empresa",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="clientes",
                to="core.empresa",
            ),
        ),
        migrations.AlterField(
            model_name="ruta",
            name="empresa",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="rutas_empresa",
                to="core.empresa",
            ),
        ),
    ]
