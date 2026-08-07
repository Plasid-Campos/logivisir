def user_role(request):
    rol = None
    if request.user.is_authenticated:
        perfil = getattr(request.user, "perfilusuario", None)
        rol = getattr(perfil, "rol", None)
    return {"USER_ROL": rol}
