def user_role(request):
    rol = None
    empresa = None
    if request.user.is_authenticated:
        perfil = getattr(request.user, "perfilusuario", None)
        rol = getattr(perfil, "rol", None)
        empresa = getattr(perfil, "empresa", None)
    return {"USER_ROL": rol, "USER_EMPRESA": empresa}
