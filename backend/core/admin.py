from django.contrib import admin
from .models import PerfilUsuario, Chofer, Cliente, Ruta, ParadaRuta


@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = ("user", "rol")
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "rol",
    )


@admin.register(Chofer)
class ChoferAdmin(admin.ModelAdmin):
    list_display = ("nombre_completo", "rut", "telefono", "licencia", "patente", "activo")
    search_fields = (
        "rut",
        "perfil__user__username",
        "perfil__user__first_name",
        "perfil__user__last_name",
    )
    list_filter = ("activo",)

    def nombre_completo(self, obj):
        return f"{obj.perfil.user.first_name} {obj.perfil.user.last_name}"
    nombre_completo.short_description = "Nombre"


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nombre", "rut", "ciudad", "comuna", "telefono", "activo")
    search_fields = ("rut", "nombre", "ciudad", "comuna")
    list_filter = ("activo", "ciudad", "comuna")


class ParadaRutaInline(admin.TabularInline):
    model = ParadaRuta
    extra = 0


@admin.register(Ruta)
class RutaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "fecha", "chofer", "estado", "activa")
    list_filter = ("estado", "activa", "fecha")
    search_fields = ("nombre", "chofer__perfil__user__first_name", "chofer__perfil__user__last_name")
    inlines = [ParadaRutaInline]


@admin.register(ParadaRuta)
class ParadaRutaAdmin(admin.ModelAdmin):
    list_display = ("ruta", "orden", "cliente", "entregado", "hora_entrega")
    list_filter = ("entregado", "ruta__fecha")
    search_fields = ("cliente__nombre", "cliente__rut", "ruta__nombre")
