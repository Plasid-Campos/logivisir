"""
El admin de Django solo expone lo que administra LogiVisir: empresas que
contratan el servicio, solicitudes y usuarios. Clientes, rutas, paradas,
pedidos y choferes NO se registran a proposito: son datos de cada empresa
cliente y el equipo LogiVisir no debe poder verlos (privacidad, Ley 19.628).
"""
from django.contrib import admin
from .models import Empresa, PerfilUsuario, SolicitudCuenta


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "rut_empresa", "owner", "activa", "creada_en")
    search_fields = ("nombre", "rut_empresa", "owner__username")
    list_filter = ("activa",)


@admin.register(SolicitudCuenta)
class SolicitudCuentaAdmin(admin.ModelAdmin):
    list_display = ("nombre_empresa", "email_contacto", "plan_solicitado", "estado", "creada_en")
    list_filter = ("estado", "plan_solicitado")
    search_fields = ("nombre_empresa", "email_contacto", "nombre_contacto")


@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = ("user", "rol", "empresa", "debe_cambiar_password")
    list_filter = ("empresa", "rol")
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "rol",
    )
