from django.db import models
from django.contrib.auth.models import User


class Empresa(models.Model):
    """
    Tenant: cada negocio (pyme) que usa la plataforma. Todo el resto de los
    modelos "de negocio" (Cliente, Chofer via perfil, Ruta) cuelgan de una
    Empresa, y cada vista filtra por la empresa del usuario autenticado.
    """
    nombre = models.CharField(max_length=150)
    rut_empresa = models.CharField(max_length=20, unique=True, blank=True, null=True)

    # Punto de origen/retorno para las rutas de esta empresa (reemplaza el
    # antiguo ORIGEN_FIJO hardcodeado en views.py)
    direccion_origen = models.CharField(max_length=200, blank=True, null=True)
    comuna_origen = models.CharField(max_length=100, blank=True, null=True)
    ciudad_origen = models.CharField(max_length=100, blank=True, null=True)
    latitud_origen = models.FloatField(blank=True, null=True)
    longitud_origen = models.FloatField(blank=True, null=True)

    owner = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="empresas_creadas"
    )
    activa = models.BooleanField(default=True)
    creada_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre

    def direccion_origen_completa(self):
        partes = [self.direccion_origen, self.comuna_origen, self.ciudad_origen, "Chile"]
        return ", ".join([p for p in partes if p])


class PerfilUsuario(models.Model):
    ROL_CHOICES = (
        ('OWNER', 'Dueño / Creador'),
        ('ADMIN', 'Administrador'),
        ('CHOFER', 'Chofer'),
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, related_name="perfiles",
    )
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
    empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, related_name="clientes",
    )
    rut = models.CharField(max_length=20)
    nombre = models.CharField(max_length=120)
    direccion = models.CharField(max_length=200)
    comuna = models.CharField(max_length=100, blank=True, null=True)
    ciudad = models.CharField(max_length=100, blank=True, null=True)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    activo = models.BooleanField(default=True)
    motivo_inactivo = models.CharField(max_length=200, blank=True, null=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    # Geocodificacion (usada por el optimizador de rutas)
    latitud = models.FloatField(blank=True, null=True)
    longitud = models.FloatField(blank=True, null=True)
    geocodificado = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["empresa", "rut"], name="unique_rut_por_empresa"),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.rut})"


class Ruta(models.Model):
    ESTADO_CHOICES = (
        ("PLANIFICADA", "Planificada"),
        ("EN_PROCESO", "En proceso"),
        ("COMPLETADA", "Completada"),
        ("CANCELADA", "Cancelada"),
    )

    empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, related_name="rutas_empresa",
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
