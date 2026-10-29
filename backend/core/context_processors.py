def user_role(request):
    rol = None
    empresa = None
    notif_no_leidas = 0
    notif_recientes = []
    if request.user.is_authenticated:
        perfil = getattr(request.user, "perfilusuario", None)
        rol = getattr(perfil, "rol", None)
        empresa = getattr(perfil, "empresa", None)
        notif_no_leidas = request.user.notificaciones.filter(leida=False).count()
        notif_recientes = list(request.user.notificaciones.all()[:5])
    return {
        "USER_ROL": rol,
        "USER_EMPRESA": empresa,
        "NOTIF_NO_LEIDAS": notif_no_leidas,
        "NOTIF_RECIENTES": notif_recientes,
    }
