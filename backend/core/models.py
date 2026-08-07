from django.db import models
from django.contrib.auth.models import User


class PerfilUsuario(models.Model):
    ROL_CHOICES = (
        ('OWNER', 'Dueño / Creador'),
        ('ADMIN', 'Administrador'),
        ('CHOFER', 'Chofer'),
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    rol = models.CharField(max_length=10, choices=ROL_CHOICES)

    def __str__(self):
        return f"{self.user.username} - {self.rol}"


class Chofer(models.Model):
    perfil = models.OneToOneField(PerfilUsuario, on_delete=models.CASCADE)
    rut = models.CharField(max_length=20, unique=True)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    licencia = models.CharField(max_length=50, blank=True, null=True)
    patente = models.CharField(max_length=10, blank=True, null=True)
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.perfil.user.first_name} {self.perfil.user.last_name} ({self.rut})"


class Cliente(models.Model):
    rut = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=120)
    direccion = models.CharField(max_length=200)
    comuna = models.CharField(max_length=100, blank=True, null=True)
    ciudad = models.CharField(max_length=100, blank=True, null=True)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    activo = models.BooleanField(default=True)
    motivo_inactivo = models.CharField(max_length=200, blank=True, null=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombre} ({self.rut})"


class Ruta(models.Model):
    ESTADO_CHOICES = (
        ("PLANIFICADA", "Planificada"),
        ("EN_PROCESO", "En proceso"),
        ("COMPLETADA", "Completada"),
        ("CANCELADA", "Cancelada"),
    )

    nombre = models.CharField(max_length=150)
    fecha = models.DateField()
    chofer = models.ForeignKey(Chofer, on_delete=models.PROTECT, related_name="rutas")
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default="PLANIFICADA")
    activa = models.BooleanField(default=True)
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.nombre} - {self.fecha} - {self.chofer}"


class ParadaRuta(models.Model):
    ESTADO_ENTREGA_CHOICES = (
        ("PENDIENTE", "Pendiente"),
        ("ENTREGADO", "Entregado"),
        ("NO_ENTREGADO", "No entregado"),
    )

    ruta = models.ForeignKey(Ruta, on_delete=models.CASCADE, related_name="paradas")
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT)
    orden = models.PositiveIntegerField()

    # Compatibilidad con lo que ya existe en vistas/templates
    entregado = models.BooleanField(default=False)
    hora_entrega = models.DateTimeField(blank=True, null=True)
    comentario = models.CharField(max_length=255, blank=True, null=True)

    # Nuevo flujo (chofer)
    estado_entrega = models.CharField(
        max_length=20,
        choices=ESTADO_ENTREGA_CHOICES,
        default="PENDIENTE",
    )
    motivo_no_entrega = models.CharField(max_length=200, blank=True, null=True)
    comentario_chofer = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        ordering = ["orden"]
        # recomendado para evitar que existan 2 paradas con el mismo orden en una misma ruta
        unique_together = ("ruta", "orden")

    def __str__(self):
        return f"{self.ruta} -> {self.cliente} (#{self.orden})"
