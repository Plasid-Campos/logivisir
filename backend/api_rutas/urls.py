from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path
from core import views as core_views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path("admin/", admin.site.urls),

    # --------- HOME / LANDING PÚBLICA ---------
    path("", core_views.home_view, name="home"),

    # --------- SOLICITUD DE CUENTA (venta del servicio) ---------
    path("solicitar-cuenta/", core_views.solicitar_cuenta_view, name="solicitar_cuenta"),
    path("solicitar-cuenta/<int:solicitud_id>/confirmacion/", core_views.solicitud_confirmacion_view, name="solicitud_confirmacion"),

    # --------- AUTENTICACIÓN ---------
    path("login/", core_views.login_view, name="login"),
    path("dashboard/", core_views.dashboard_view, name="dashboard"),
    path("logout/", core_views.logout_view, name="logout"),
    path("cambiar-password/", core_views.cambiar_password_obligatorio_view, name="cambiar_password_obligatorio"),

    # --------- USUARIOS / PERFILES ---------
    path("crear-usuario/", core_views.crear_usuario_view, name="crear_usuario"),
    path("usuarios/", core_views.lista_usuarios_view, name="lista_usuarios"),
    path("usuarios/<int:user_id>/estado/", core_views.cambiar_estado_usuario_view, name="cambiar_estado_usuario"),
    path("usuarios/<int:user_id>/restablecer-clave/", core_views.restablecer_clave_usuario_view, name="restablecer_clave_usuario"),

    # --------- CHOFERES (OWNER + ADMIN) ---------
    path("choferes/", core_views.lista_choferes_view, name="lista_choferes"),
    path("choferes/crear/", core_views.crear_chofer_view, name="crear_chofer"),
    path("choferes/<int:chofer_id>/editar/", core_views.editar_chofer_view, name="editar_chofer"),
    path("choferes/<int:chofer_id>/eliminar/", core_views.eliminar_chofer_view, name="eliminar_chofer"),

    # --------- CLIENTES (OWNER + ADMIN) ---------
    path("clientes/", core_views.lista_clientes_view, name="lista_clientes"),
    path("clientes/crear/", core_views.crear_cliente_view, name="crear_cliente"),
    path("clientes/<int:cliente_id>/editar/", core_views.editar_cliente_view, name="editar_cliente"),
    path("clientes/<int:cliente_id>/reubicar/", core_views.reubicar_cliente_view, name="reubicar_cliente"),
    path("clientes/reubicar-sin-ubicacion/", core_views.reubicar_clientes_lote_view, name="reubicar_clientes_lote"),
    path("clientes/<int:cliente_id>/desactivar/", core_views.desactivar_cliente_view, name="desactivar_cliente"),
    path("clientes/<int:cliente_id>/eliminar/", core_views.eliminar_cliente_view, name="eliminar_cliente"),

    # --------- RUTAS (OWNER + ADMIN) ---------
    path("rutas/", core_views.lista_rutas_view, name="lista_rutas"),
    path("rutas/crear/", core_views.crear_ruta_view, name="crear_ruta"),
    path("rutas/<int:ruta_id>/", core_views.detalle_ruta_view, name="detalle_ruta"),
    path("rutas/<int:ruta_id>/editar/", core_views.editar_ruta_view, name="editar_ruta"),
    path("rutas/<int:ruta_id>/agregar-parada/", core_views.agregar_parada_view, name="agregar_parada"),
    path("paradas/<int:parada_id>/eliminar/", core_views.eliminar_parada_view, name="eliminar_parada"),
    path("paradas/<int:parada_id>/toggle/", core_views.toggle_parada_entregada_view, name="toggle_parada"),
    path("rutas/<int:ruta_id>/cambiar-estado/", core_views.cambiar_estado_ruta_view, name="cambiar_estado_ruta"),
    path("rutas/<int:ruta_id>/optimizar/", core_views.optimizar_ruta_view, name="optimizar_ruta"),
    path("rutas/<int:ruta_id>/agregar-pedido/", core_views.agregar_pedido_a_ruta_view, name="agregar_pedido_a_ruta"),

    # --------- PEDIDOS ---------
    path("pedidos/", core_views.lista_pedidos_view, name="lista_pedidos"),
    path("pedidos/nuevo/", core_views.crear_pedido_view, name="crear_pedido"),
    path("pedidos/<int:pedido_id>/", core_views.detalle_pedido_view, name="detalle_pedido"),

    # --------- ANALITICA DE DESPACHOS / SEGMENTACION (OWNER + ADMIN) ---------
    path("analitica/", core_views.analitica_view, name="analitica"),
    path("analitica/exportar/segmentacion-clientes.csv", core_views.exportar_segmentacion_csv_view, name="exportar_segmentacion_csv"),
    path("analitica/exportar/despachos-mensuales.csv", core_views.exportar_despachos_mensuales_csv_view, name="exportar_despachos_mensuales_csv"),

    # --------- CONFIGURACION DE LA EMPRESA ---------
    path("empresa/configuracion/", core_views.configurar_empresa_view, name="configurar_empresa"),

    # --------- MI CUENTA ---------
    path("cuenta/cambiar-clave/", core_views.CambiarPasswordView.as_view(), name="cambiar_password"),

    # --------- NOTIFICACIONES (todos los roles) ---------
    path("notificaciones/", core_views.lista_notificaciones_view, name="lista_notificaciones"),
    path("notificaciones/<int:notificacion_id>/abrir/", core_views.abrir_notificacion_view, name="abrir_notificacion"),
    path("notificaciones/marcar-leidas/", core_views.marcar_notificaciones_leidas_view, name="marcar_notificaciones_leidas"),
    path("chofer/mis-rutas/", core_views.chofer_mis_rutas_view, name="chofer_mis_rutas"),

    # --------- STAFF LOGIVISIR (empresas clientes: ficha y acceso, sin sus datos) ---------
    path("staff/empresas/", core_views.staff_lista_empresas_view, name="staff_lista_empresas"),
    path("staff/empresas/<int:empresa_id>/", core_views.staff_detalle_empresa_view, name="staff_detalle_empresa"),
    path("staff/empresas/<int:empresa_id>/estado/", core_views.staff_cambiar_estado_empresa_view, name="staff_cambiar_estado_empresa"),
    path("staff/empresas/<int:empresa_id>/usuarios/crear/", core_views.staff_crear_usuario_empresa_view, name="staff_crear_usuario_empresa"),
    path("staff/usuarios/<int:user_id>/restablecer-clave/", core_views.staff_restablecer_clave_view, name="staff_restablecer_clave"),

    # --------- STAFF LOGIVISIR (solicitudes de cuenta) ---------
    path("staff/solicitudes/", core_views.lista_solicitudes_view, name="lista_solicitudes"),
    path("staff/solicitudes/<int:solicitud_id>/", core_views.detalle_solicitud_view, name="detalle_solicitud"),
    path("staff/solicitudes/<int:solicitud_id>/marcar-pago/", core_views.marcar_pago_validado_view, name="marcar_pago_validado"),
    path("staff/solicitudes/<int:solicitud_id>/crear-cuenta/", core_views.crear_cuenta_solicitud_view, name="crear_cuenta_solicitud"),
    path("staff/solicitudes/<int:solicitud_id>/rechazar/", core_views.rechazar_solicitud_view, name="rechazar_solicitud"),

    # --------- PANEL DEL CHOFER ---------
    path("chofer/ruta/", core_views.chofer_ruta_hoy_view, name="chofer_ruta_hoy"),
    path(
        "chofer/parada/<int:parada_id>/marcar/",
        core_views.chofer_marcar_parada_view,
        name="chofer_marcar_parada",
    ),

    # --------- RECUPERAR CONTRASEÑA ---------
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="core/password_reset_form.html",
            email_template_name="core/password_reset_email.html",
            subject_template_name="core/password_reset_subject.txt",
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="core/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        core_views.RestablecerPasswordConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="core/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif settings.SERVIR_MEDIA:
    # static() no hace nada con DEBUG apagado, por eso se registra la vista a mano
    from django.urls import re_path
    from django.views.static import serve
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    ]
