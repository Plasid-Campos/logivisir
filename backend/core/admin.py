from django.contrib import admin
from .models import Empresa, PerfilUsuario, Chofer, Cliente, Ruta, ParadaRuta, Producto, Pedido, PedidoItem


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "rut_empresa", "owner", "activa", "creada_en")
    search_fields = ("nombre", "rut_empresa", "owner__username")
    list_filter = ("activa",)


@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = ("user", "rol", "empresa")
    list_filter = ("empresa", "rol")
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "rol",
    )


@admin.register(Chofer)
class ChoferAdmin(admin.ModelAdmin):
    list_display = ("nombre_completo", "rut", "empresa", "telefono", "licencia", "patente", "activo")
    search_fields = (
        "rut",
        "perfil__user__username",
        "perfil__user__first_name",
        "perfil__user__last_name",
    )
    list_filter = ("activo", "perfil__empresa")

    def nombre_completo(self, obj):
        return f"{obj.perfil.user.first_name} {obj.perfil.user.last_name}"
    nombre_completo.short_description = "Nombre"

    def empresa(self, obj):
        return obj.perfil.empresa
    empresa.short_description = "Empresa"


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nombre", "rut", "empresa", "ciudad", "comuna", "telefono", "activo", "geocodificado")
    search_fields = ("rut", "nombre", "ciudad", "comuna")
    list_filter = ("activo", "empresa", "ciudad", "comuna", "geocodificado")


class ParadaRutaInline(admin.TabularInline):
    model = ParadaRuta
    extra = 0


@admin.register(Ruta)
class RutaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "empresa", "fecha", "chofer", "estado", "activa")
    list_filter = ("estado", "activa", "empresa", "fecha")
    search_fields = ("nombre", "chofer__perfil__user__first_name", "chofer__perfil__user__last_name")
    inlines = [ParadaRutaInline]


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "empresa", "precio", "unidad", "stock_disponible", "disponible")
    list_filter = ("empresa", "disponible")
    search_fields = ("nombre",)


class PedidoItemInline(admin.TabularInline):
    model = PedidoItem
    extra = 0


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ("id", "empresa", "cliente", "estado", "total", "creado_en")
    list_filter = ("empresa", "estado")
    search_fields = ("cliente__nombre",)
    inlines = [PedidoItemInline]


@admin.register(ParadaRuta)
class ParadaRutaAdmin(admin.ModelAdmin):
    list_display = ("ruta", "orden", "cliente", "entregado", "hora_entrega")
    list_filter = ("entregado", "ruta__fecha")
    search_fields = ("cliente__nombre", "cliente__rut", "ruta__nombre")
