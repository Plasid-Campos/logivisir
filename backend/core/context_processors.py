def user_role(request):
    rol = None
    empresa = None
    notif_no_leidas = 0
    notif_recientes = []
    solicitudes_nuevas = 0
    if request.user.is_authenticated:
        # El equipo LogiVisir ve solo su menú, nunca el de una empresa cliente.
        perfil = None if request.user.is_staff else getattr(request.user, "perfilusuario", None)
        rol = getattr(perfil, "rol", None)
        empresa = getattr(perfil, "empresa", None)
        notif_no_leidas = request.user.notificaciones.filter(leida=False).count()
        notif_recientes = list(request.user.notificaciones.all()[:5])
        if request.user.is_staff:
            from .models import SolicitudCuenta
            solicitudes_nuevas = SolicitudCuenta.objects.filter(estado="NUEVA").count()
    return {
        "USER_ROL": rol,
        "USER_EMPRESA": empresa,
        "NOTIF_NO_LEIDAS": notif_no_leidas,
        "NOTIF_RECIENTES": notif_recientes,
        "SOLICITUDES_NUEVAS": solicitudes_nuevas,
    }
