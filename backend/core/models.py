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


class SolicitudCuenta(models.Model):
    """
    Solicitud de contratación del servicio hecha desde el sitio público por
    un prospecto (aún no es cliente). No tiene FK obligatoria a Empresa
    porque la Empresa recién se crea cuando el equipo Logivisir valida el
    pago y aprovisiona la cuenta (ver crear_cuenta_solicitud_view).
    """
    PLAN_CHOICES = (
        ("BASICO", "Básico"),
        ("PRO", "Pro"),
        ("EMPRESARIAL", "Empresarial"),
    )
    ESTADO_CHOICES = (
        ("NUEVA", "Nueva"),
        ("PAGO_VALIDADO", "Pago validado"),
        ("CUENTA_CREADA", "Cuenta creada"),
        ("RECHAZADA", "Rechazada"),
    )

    nombre_empresa = models.CharField(max_length=150)
    nombre_contacto = models.CharField(max_length=150)
    email_contacto = models.EmailField()
    telefono_contacto = models.CharField(max_length=20)
    rubro = models.CharField(max_length=100, blank=True, null=True)
    plan_solicitado = models.CharField(max_length=20, choices=PLAN_CHOICES)
    mensaje = models.TextField(blank=True, null=True)

    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default="NUEVA")
    notas_internas = models.TextField(blank=True, null=True)
    creada_en = models.DateTimeField(auto_now_add=True)
    empresa_creada = models.ForeignKey(
        Empresa, on_delete=models.SET_NULL, blank=True, null=True,
        related_name="solicitud_origen",
    )

    class Meta:
        ordering = ["-creada_en"]

    @property
    def codigo_referencia(self):
        return f"SOL-{self.id:06d}"

    def __str__(self):
        return f"{self.codigo_referencia} - {self.nombre_empresa}"


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
    debe_cambiar_password = models.BooleanField(default=False)

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
    TIPO_CHOICES = (
        ("NORMAL", "Cliente regular"),
        ("DELIVERY", "Delivery a domicilio"),
    )

    empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, related_name="clientes",
    )
    tipo_cliente = models.CharField(max_length=20, choices=TIPO_CHOICES, default="NORMAL")
    rut = models.CharField(max_length=20, blank=True, null=True)
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


class Producto(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name="productos")
    nombre = models.CharField(max_length=150)
    descripcion = models.CharField(max_length=300, blank=True, null=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    unidad = models.CharField(max_length=30, default="unidad")
    stock_disponible = models.PositiveIntegerField(default=0)
    disponible = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return f"{self.nombre} (${self.precio})"


class Pedido(models.Model):
    ESTADO_CHOICES = (
        ("PENDIENTE", "Pendiente"),
        ("ASIGNADO", "Asignado a ruta"),
        ("ENTREGADO", "Entregado"),
        ("CANCELADO", "Cancelado"),
    )

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name="pedidos")
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="pedidos")
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default="PENDIENTE")
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    creado_en = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-creado_en"]

    def __str__(self):
        return f"Pedido #{self.id} - {self.cliente.nombre} ({self.get_estado_display()})"

    def recalcular_total(self):
        total = sum((item.subtotal for item in self.items.all()), start=0)
        self.total = total
        self.save(update_fields=["total"])


class PedidoItem(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField()
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.cantidad} x {self.producto.nombre}"

    @property
    def subtotal(self):
        return self.cantidad * self.precio_unitario


class ParadaRuta(models.Model):
    ESTADO_ENTREGA_CHOICES = (
        ("PENDIENTE", "Pendiente"),
        ("ENTREGADO", "Entregado"),
        ("NO_ENTREGADO", "No entregado"),
    )

    ruta = models.ForeignKey(Ruta, on_delete=models.CASCADE, related_name="paradas")
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT)
    orden = models.PositiveIntegerField()
    pedido = models.ForeignKey(
        Pedido, on_delete=models.SET_NULL, null=True, blank=True, related_name="paradas_pedido"
    )

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
