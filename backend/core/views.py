from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from urllib.parse import quote_plus

from .models import (
    PerfilUsuario,
    Chofer,
    Cliente,
    Ruta,
    ParadaRuta,
    Producto,
    Pedido,
    PedidoItem,
    Empresa,
    SolicitudCuenta,
)
from .tenancy import get_empresa, get_object_or_404_scoped
from .cart import Carrito

# =========================================================
# CONFIG
# =========================================================
MAX_WAYPOINTS_MAPS = 20  # evita que Maps falle
PAGINA_TAMANO = 25

# =========================================================
# HOME / LANDING
# =========================================================
def home_view(request):
    return render(request, "core/home.html")

# =========================================================
# SOLICITUD DE CUENTA (venta del servicio, público)
# =========================================================
PLANES_VALIDOS = dict(SolicitudCuenta.PLAN_CHOICES).keys()


def solicitar_cuenta_view(request):
    error = None
    plan_preseleccionado = request.GET.get("plan", "")
    if plan_preseleccionado not in PLANES_VALIDOS:
        plan_preseleccionado = ""

    if request.method == "POST":
        nombre_empresa = (request.POST.get("nombre_empresa") or "").strip()
        nombre_contacto = (request.POST.get("nombre_contacto") or "").strip()
        email_contacto = (request.POST.get("email_contacto") or "").strip()
        telefono_contacto = (request.POST.get("telefono_contacto") or "").strip()
        rubro = (request.POST.get("rubro") or "").strip()
        plan_solicitado = request.POST.get("plan_solicitado")
        mensaje = (request.POST.get("mensaje") or "").strip()

        if not (nombre_empresa and nombre_contacto and email_contacto and telefono_contacto):
            error = "Completa nombre de la empresa, contacto, correo y teléfono."
        elif plan_solicitado not in PLANES_VALIDOS:
            error = "Selecciona un plan válido."
        else:
            solicitud = SolicitudCuenta.objects.create(
                nombre_empresa=nombre_empresa,
                nombre_contacto=nombre_contacto,
                email_contacto=email_contacto,
                telefono_contacto=telefono_contacto,
                rubro=rubro,
                plan_solicitado=plan_solicitado,
                mensaje=mensaje,
            )
            return redirect("solicitud_confirmacion", solicitud_id=solicitud.id)

    return render(request, "core/solicitar_cuenta.html", {
        "error": error,
        "plan_preseleccionado": plan_preseleccionado,
        "planes": SolicitudCuenta.PLAN_CHOICES,
    })


def solicitud_confirmacion_view(request, solicitud_id):
    solicitud = get_object_or_404(SolicitudCuenta, id=solicitud_id)
    return render(request, "core/solicitud_confirmacion.html", {"solicitud": solicitud})

# =========================================================
# LOGIN / LOGOUT
# =========================================================
def login_view(request):
    mensaje_error = None
    next_url = request.GET.get("next") or request.POST.get("next") or ""

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        usuario = authenticate(request, username=username, password=password)
        if usuario is not None:
            login(request, usuario)
            perfil = getattr(usuario, "perfilusuario", None)

            # Cuentas recien aprovisionadas por el staff deben cambiar su
            # password temporal antes de hacer cualquier otra cosa. Este
            # chequeo va antes de mirar next_url a proposito, para que no
            # se pueda saltar con un ?next= manual.
            if perfil and perfil.debe_cambiar_password:
                return redirect("cambiar_password_obligatorio")

            if next_url:
                return redirect(next_url)

            if perfil and perfil.rol == "CHOFER":
                return redirect("chofer_ruta_hoy")

            # Staff de Logivisir no es un tenant: no tiene PerfilUsuario ni
            # empresa, asi que no puede ir al dashboard normal.
            if not perfil and usuario.is_staff:
                return redirect("lista_solicitudes")

            return redirect("dashboard")

        mensaje_error = "Usuario o contraseña incorrectos."

    return render(request, "core/login.html", {"mensaje_error": mensaje_error, "next": next_url})


@login_required
def logout_view(request):
    logout(request)
    return redirect("login")

# =========================================================
# VALIDACIONES DE ROL
# =========================================================
def es_owner(user):
    try:
        return user.perfilusuario.rol == "OWNER"
    except Exception:
        return False


def es_admin_o_owner(user):
    try:
        return user.perfilusuario.rol in ("ADMIN", "OWNER")
    except Exception:
        return False


def es_chofer(user):
    try:
        return user.perfilusuario.rol == "CHOFER"
    except Exception:
        return False


def es_staff_logivisir(user):
    """
    Equipo interno de Logivisir (no es un tenant): usa el flag nativo de
    Django is_staff, separado de los roles OWNER/ADMIN/CHOFER que viven
    dentro de una Empresa cliente.
    """
    return user.is_authenticated and user.is_staff

# =========================================================
# CAMBIO DE PASSWORD OBLIGATORIO (cuentas recien creadas por staff)
# =========================================================
@login_required
def cambiar_password_obligatorio_view(request):
    perfil = getattr(request.user, "perfilusuario", None)
    error = None

    if request.method == "POST":
        nueva = request.POST.get("nueva_password") or ""
        confirmacion = request.POST.get("confirmar_password") or ""

        if nueva != confirmacion:
            error = "Las contraseñas no coinciden."
        else:
            try:
                validate_password(nueva, user=request.user)
            except ValidationError as e:
                error = " ".join(e.messages)

        if not error:
            request.user.set_password(nueva)
            request.user.save()

            if perfil:
                perfil.debe_cambiar_password = False
                perfil.save(update_fields=["debe_cambiar_password"])

            # Sin esto, cambiar la password invalida la sesion actual y
            # el usuario queda expulsado justo despues de guardar.
            update_session_auth_hash(request, request.user)

            if perfil and perfil.rol == "CHOFER":
                return redirect("chofer_ruta_hoy")
            return redirect("dashboard")

    return render(request, "core/cambiar_password_obligatorio.html", {"error": error})

# =========================================================
# DASHBOARD
# =========================================================
@login_required
def dashboard_view(request):
    perfil = getattr(request.user, "perfilusuario", None)
    empresa = get_empresa(request)

    clientes_activos = Cliente.objects.filter(empresa=empresa, activo=True).count()
    choferes_activos = Chofer.objects.filter(perfil__empresa=empresa, activo=True).count()

    hoy = timezone.localdate()
    rutas_hoy_qs = Ruta.objects.filter(empresa=empresa, fecha=hoy, activa=True)

    rutas_pendientes = rutas_hoy_qs.exclude(estado="COMPLETADA").count()

    return render(request, "core/dashboard.html", {
        "perfil": perfil,
        "empresa": empresa,
        "resumen": {
            "clientes_activos": clientes_activos,
            "choferes_activos": choferes_activos,
            "rutas_hoy": rutas_hoy_qs.count(),
            "rutas_hoy_pendientes": rutas_pendientes,
        }
    })

# =========================================================
# CREAR USUARIO (solo OWNER)
# =========================================================
ROLES_CREABLES = ("ADMIN", "CHOFER")


@user_passes_test(es_owner)
def crear_usuario_view(request):
    mensaje = None
    error = None
    empresa = get_empresa(request)

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        nombre = request.POST.get("nombre")
        apellido = request.POST.get("apellido")
        rol = request.POST.get("rol")
        email = request.POST.get("email")

        if rol not in ROLES_CREABLES:
            error = "Rol inválido."
        elif User.objects.filter(username=username).exists():
            error = f"El nombre de usuario '{username}' ya existe. Elige otro."
        elif not password:
            error = "La contraseña es obligatoria."
        else:
            try:
                validate_password(password)
            except ValidationError as e:
                error = " ".join(e.messages)

        if not error:
            user = User.objects.create_user(
                username=username,
                password=password,
                first_name=nombre,
                last_name=apellido,
                email=email,
            )
            PerfilUsuario.objects.create(user=user, rol=rol, empresa=empresa)
            mensaje = f"Usuario '{username}' creado correctamente."

    return render(request, "core/crear_usuario.html", {"mensaje": mensaje, "error": error})

# =========================================================
# CHOFERES (OWNER + ADMIN)
# =========================================================
@user_passes_test(es_admin_o_owner)
def lista_choferes_view(request):
    empresa = get_empresa(request)
    choferes = Chofer.objects.filter(perfil__empresa=empresa).select_related("perfil", "perfil__user")
    return render(request, "core/lista_choferes.html", {"choferes": choferes})


@user_passes_test(es_admin_o_owner)
def crear_chofer_view(request):
    mensaje = None
    error = None
    empresa = get_empresa(request)

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        nombre = request.POST.get("nombre")
        apellido = request.POST.get("apellido")
        email = request.POST.get("email")

        rut = request.POST.get("rut")
        telefono = request.POST.get("telefono")
        licencia = request.POST.get("licencia")
        patente = request.POST.get("patente")

        if User.objects.filter(username=username).exists():
            error = f"El nombre de usuario '{username}' ya existe. Usa otro."
        elif Chofer.objects.filter(rut=rut).exists():
            error = f"Ya existe un chofer con el RUT {rut}."
        elif not password:
            error = "La contraseña es obligatoria."
        else:
            try:
                validate_password(password)
            except ValidationError as e:
                error = " ".join(e.messages)

        if not error:
            try:
                user = User.objects.create_user(
                    username=username,
                    password=password,
                    first_name=nombre,
                    last_name=apellido,
                    email=email,
                )
                perfil = PerfilUsuario.objects.create(user=user, rol="CHOFER", empresa=empresa)
                Chofer.objects.create(
                    perfil=perfil,
                    rut=rut,
                    telefono=telefono,
                    licencia=licencia,
                    patente=patente,
                )
                mensaje = "Chofer creado con éxito."
            except IntegrityError:
                error = "Error al guardar. Verifica usuario y RUT."

    return render(request, "core/crear_chofer.html", {"mensaje": mensaje, "error": error})


@user_passes_test(es_admin_o_owner)
def editar_chofer_view(request, chofer_id):
    empresa = get_empresa(request)
    chofer = get_object_or_404_scoped(Chofer, empresa, lookup_field="perfil__empresa", id=chofer_id)
    mensaje = None

    if request.method == "POST":
        chofer.rut = request.POST.get("rut")
        chofer.telefono = request.POST.get("telefono")
        chofer.licencia = request.POST.get("licencia")
        chofer.patente = request.POST.get("patente")
        chofer.activo = request.POST.get("activo") == "on"
        chofer.save()
        mensaje = "Cambios guardados."

    return render(request, "core/editar_chofer.html", {"chofer": chofer, "mensaje": mensaje})


@user_passes_test(es_admin_o_owner)
@require_POST
def eliminar_chofer_view(request, chofer_id):
    empresa = get_empresa(request)
    chofer = get_object_or_404_scoped(Chofer, empresa, lookup_field="perfil__empresa", id=chofer_id)
    usuario = chofer.perfil.user
    usuario.delete()
    return redirect("lista_choferes")

# =========================================================
# CLIENTES (OWNER + ADMIN)
# =========================================================
@user_passes_test(es_admin_o_owner)
def lista_clientes_view(request):
    empresa = get_empresa(request)
    clientes_qs = Cliente.objects.filter(empresa=empresa).order_by("nombre")
    paginator = Paginator(clientes_qs, PAGINA_TAMANO)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "core/lista_clientes.html", {"clientes": page_obj, "page_obj": page_obj})


@user_passes_test(es_admin_o_owner)
def crear_cliente_view(request):
    mensaje = None
    error = None
    empresa = get_empresa(request)

    if request.method == "POST":
        rut = request.POST.get("rut")
        nombre = request.POST.get("nombre")
        direccion = request.POST.get("direccion")
        comuna = request.POST.get("comuna")
        ciudad = request.POST.get("ciudad")
        telefono = request.POST.get("telefono")
        email = request.POST.get("email")

        if Cliente.objects.filter(empresa=empresa, rut=rut).exists():
            error = f"Ya existe un cliente con el RUT {rut}."
        else:
            cliente = Cliente.objects.create(
                empresa=empresa,
                rut=rut, nombre=nombre, direccion=direccion,
                comuna=comuna, ciudad=ciudad, telefono=telefono, email=email
            )
            mensaje = "Cliente creado correctamente."
            from .geocoding import geocodificar_cliente
            if not geocodificar_cliente(cliente):
                mensaje += (
                    " No se pudo ubicar la dirección automáticamente; "
                    "revisa que esté bien escrita para que la ruta pueda optimizarse."
                )

    return render(request, "core/crear_cliente.html", {"mensaje": mensaje, "error": error})


@user_passes_test(es_admin_o_owner)
def editar_cliente_view(request, cliente_id):
    empresa = get_empresa(request)
    cliente = get_object_or_404_scoped(Cliente, empresa, id=cliente_id)
    mensaje = None

    if request.method == "POST":
        direccion_anterior = (cliente.direccion, cliente.comuna, cliente.ciudad)

        cliente.rut = request.POST.get("rut")
        cliente.nombre = request.POST.get("nombre")
        cliente.direccion = request.POST.get("direccion")
        cliente.comuna = request.POST.get("comuna")
        cliente.ciudad = request.POST.get("ciudad")
        cliente.telefono = request.POST.get("telefono")
        cliente.email = request.POST.get("email")
        cliente.activo = request.POST.get("activo") == "on"
        cliente.motivo_inactivo = request.POST.get("motivo_inactivo")

        if cliente.activo:
            cliente.motivo_inactivo = ""

        direccion_nueva = (cliente.direccion, cliente.comuna, cliente.ciudad)
        cliente.save()
        mensaje = "Cambios guardados."

        if direccion_nueva != direccion_anterior:
            from .geocoding import geocodificar_cliente
            if not geocodificar_cliente(cliente):
                mensaje += " No se pudo re-ubicar la nueva dirección automáticamente."

    return render(request, "core/editar_cliente.html", {"cliente": cliente, "mensaje": mensaje})


@user_passes_test(es_admin_o_owner)
@require_POST
def desactivar_cliente_view(request, cliente_id):
    empresa = get_empresa(request)
    cliente = get_object_or_404_scoped(Cliente, empresa, id=cliente_id)
    cliente.activo = False
    if not cliente.motivo_inactivo:
        cliente.motivo_inactivo = "Inactivado manualmente."
    cliente.save()
    return redirect("lista_clientes")


@user_passes_test(es_owner)
@require_POST
def eliminar_cliente_view(request, cliente_id):
    empresa = get_empresa(request)
    cliente = get_object_or_404_scoped(Cliente, empresa, id=cliente_id)
    cliente.delete()
    return redirect("lista_clientes")

# =========================================================
# RUTAS (OWNER + ADMIN)
# =========================================================
@user_passes_test(es_admin_o_owner)
def lista_rutas_view(request):
    empresa = get_empresa(request)
    rutas_qs = Ruta.objects.filter(empresa=empresa).select_related(
        "chofer", "chofer__perfil__user"
    ).order_by("-fecha", "-creada_en")
    paginator = Paginator(rutas_qs, PAGINA_TAMANO)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "core/lista_rutas.html", {"rutas": page_obj, "page_obj": page_obj})


@user_passes_test(es_admin_o_owner)
def crear_ruta_view(request):
    mensaje = None
    error = None
    empresa = get_empresa(request)
    choferes = Chofer.objects.filter(perfil__empresa=empresa, activo=True).select_related("perfil__user")

    if request.method == "POST":
        nombre = request.POST.get("nombre")
        fecha = request.POST.get("fecha")
        chofer_id = request.POST.get("chofer_id")

        if not (nombre and fecha and chofer_id):
            error = "Todos los campos son obligatorios."
        else:
            try:
                chofer = Chofer.objects.get(id=chofer_id, perfil__empresa=empresa)
                ruta = Ruta.objects.create(nombre=nombre, fecha=fecha, chofer=chofer, empresa=empresa)
                return redirect("detalle_ruta", ruta_id=ruta.id)
            except Chofer.DoesNotExist:
                error = "El chofer seleccionado no existe."

    return render(request, "core/crear_ruta.html", {"mensaje": mensaje, "error": error, "choferes": choferes})


@user_passes_test(es_admin_o_owner)
def detalle_ruta_view(request, ruta_id):
    empresa = get_empresa(request)
    ruta = get_object_or_404_scoped(Ruta, empresa, id=ruta_id)
    paradas = ruta.paradas.select_related("cliente", "pedido").all()
    clientes_activos = Cliente.objects.filter(empresa=empresa, activo=True).order_by("nombre")
    pedidos_pendientes = Pedido.objects.filter(empresa=empresa, estado="PENDIENTE").select_related("cliente")
    return render(request, "core/detalle_ruta.html", {
        "ruta": ruta, "paradas": paradas, "clientes": clientes_activos,
        "pedidos_pendientes": pedidos_pendientes,
    })


@user_passes_test(es_admin_o_owner)
def agregar_parada_view(request, ruta_id):
    empresa = get_empresa(request)
    ruta = get_object_or_404_scoped(Ruta, empresa, id=ruta_id)

    if request.method == "POST":
        cliente_id = request.POST.get("cliente_id")
        orden = request.POST.get("orden")
        comentario = request.POST.get("comentario")

        if not cliente_id:
            return redirect("detalle_ruta", ruta_id=ruta.id)

        cliente = get_object_or_404_scoped(Cliente, empresa, id=cliente_id)

        if not orden:
            ultimo = ruta.paradas.order_by("-orden").first()
            orden = (ultimo.orden + 1) if ultimo else 1

        if ruta.paradas.filter(cliente=cliente).exists():
            return redirect("detalle_ruta", ruta_id=ruta.id)

        ParadaRuta.objects.create(
            ruta=ruta,
            cliente=cliente,
            orden=orden,
            comentario=comentario,
        )

    return redirect("detalle_ruta", ruta_id=ruta.id)


@user_passes_test(es_admin_o_owner)
@require_POST
def eliminar_parada_view(request, parada_id):
    empresa = get_empresa(request)
    parada = get_object_or_404_scoped(ParadaRuta, empresa, lookup_field="ruta__empresa", id=parada_id)
    ruta_id = parada.ruta.id
    parada.delete()
    return redirect("detalle_ruta", ruta_id=ruta_id)


@user_passes_test(es_admin_o_owner)
@require_POST
def toggle_parada_entregada_view(request, parada_id):
    empresa = get_empresa(request)
    parada = get_object_or_404_scoped(ParadaRuta, empresa, lookup_field="ruta__empresa", id=parada_id)

    # Toggle compatibilidad
    parada.entregado = not parada.entregado

    if parada.entregado:
        parada.estado_entrega = "ENTREGADO"
        parada.hora_entrega = timezone.now()
        parada.motivo_no_entrega = None
        parada.comentario_chofer = None
    else:
        parada.estado_entrega = "PENDIENTE"
        parada.hora_entrega = None
        parada.motivo_no_entrega = None
        parada.comentario_chofer = None

    parada.save()
    return redirect("detalle_ruta", ruta_id=parada.ruta.id)

@user_passes_test(es_admin_o_owner)
def cambiar_estado_ruta_view(request, ruta_id):
    empresa = get_empresa(request)
    ruta = get_object_or_404_scoped(Ruta, empresa, id=ruta_id)

    if request.method == "POST":
        nuevo_estado = request.POST.get("estado")
        if nuevo_estado in dict(Ruta.ESTADO_CHOICES).keys():
            ruta.estado = nuevo_estado
            ruta.save()

    return redirect("detalle_ruta", ruta_id=ruta.id)


@user_passes_test(es_admin_o_owner)
@require_POST
def optimizar_ruta_view(request, ruta_id):
    empresa = get_empresa(request)
    ruta = get_object_or_404_scoped(Ruta, empresa, id=ruta_id)

    from .optimizer import optimizar_paradas
    resultado = optimizar_paradas(ruta)

    if resultado.get("optimizado"):
        mensaje = f"Ruta optimizada: {resultado['cantidad']} paradas reordenadas."
        if resultado.get("sin_coordenadas"):
            mensaje += (
                f" {len(resultado['sin_coordenadas'])} cliente(s) sin coordenadas "
                "quedaron al final sin optimizar: " + ", ".join(resultado["sin_coordenadas"])
            )
    else:
        mensaje = resultado.get("motivo", "No fue posible optimizar la ruta.")

    messages.info(request, mensaje)

    return redirect("detalle_ruta", ruta_id=ruta.id)


def _actualizar_estado_ruta_por_paradas(ruta, progreso):
    """
    Reglas:
    - COMPLETADA: total > 0 y pendientes == 0 y no_entregadas == 0
    - EN_PROCESO: si hay entregadas o no_entregadas (y no está completada)
    - PLANIFICADA: si todas están pendientes
    """
    if not ruta:
        return

    total = progreso.get("total", 0)
    entregadas = progreso.get("entregadas", 0)
    no_entregadas = progreso.get("no_entregadas", 0)
    pendientes = progreso.get("pendientes", 0)

    if total == 0:
        return

    # ✅ Caso ideal: todo entregado
    if pendientes == 0 and no_entregadas == 0:
        if ruta.estado != "COMPLETADA":
            ruta.estado = "COMPLETADA"
            ruta.save(update_fields=["estado", "actualizada_en"])
        return

    # Si ya está completada pero ahora cambió algo (revertir), la bajamos a EN_PROCESO
    if ruta.estado == "COMPLETADA" and (pendientes > 0 or no_entregadas > 0):
        ruta.estado = "EN_PROCESO"
        ruta.save(update_fields=["estado", "actualizada_en"])
        return

    # Si hay movimiento (algo marcado), ponemos EN_PROCESO (sin pisar CANCELADA)
    if ruta.estado != "CANCELADA":
        if entregadas > 0 or no_entregadas > 0:
            if ruta.estado != "EN_PROCESO":
                ruta.estado = "EN_PROCESO"
                ruta.save(update_fields=["estado", "actualizada_en"])
        else:
            # Todo pendiente
            if ruta.estado != "PLANIFICADA":
                ruta.estado = "PLANIFICADA"
                ruta.save(update_fields=["estado", "actualizada_en"])


# =========================================================
# PANEL DEL CHOFER
# =========================================================
@user_passes_test(es_chofer)
def chofer_ruta_hoy_view(request):
    hoy = timezone.localdate()
    chofer = get_object_or_404(Chofer, perfil__user=request.user)
    empresa = chofer.perfil.empresa

    ruta = Ruta.objects.filter(chofer=chofer, fecha=hoy, activa=True).order_by("-creada_en").first()

    paradas = []
    paradas_ui = []
    maps_url = ""
    aviso_maps = ""
    progreso = {"total": 0, "entregadas": 0, "no_entregadas": 0, "pendientes": 0}
    siguiente_parada_id = None
    porcentaje_entregadas = 0

    origen_fijo = empresa.direccion_origen_completa() or "Origen no configurado"

    if ruta:
        paradas = ruta.paradas.select_related("cliente").order_by("orden")

        # ✅ Progreso de ruta (según estado_entrega)
        progreso = {
            "total": paradas.count(),
            "entregadas": paradas.filter(estado_entrega="ENTREGADO").count(),
            "no_entregadas": paradas.filter(estado_entrega="NO_ENTREGADO").count(),
            "pendientes": paradas.filter(estado_entrega="PENDIENTE").count(),
        }

        # ✅ Porcentaje para la barra (evita widthratio en template)
        if progreso["total"] > 0:
            porcentaje_entregadas = int((progreso["entregadas"] * 100) / progreso["total"])
        else:
            porcentaje_entregadas = 0

        # ✅ Actualiza estado de ruta automáticamente según progreso
        _actualizar_estado_ruta_por_paradas(ruta, progreso)

        # ✅ Siguiente parada (primera pendiente)
        siguiente_parada_id = (
            paradas.filter(estado_entrega="PENDIENTE")
            .order_by("orden")
            .values_list("id", flat=True)
            .first()
        )

        direcciones = []
        for p in paradas:
            cli = p.cliente
            partes = [cli.direccion]
            if cli.comuna:
                partes.append(cli.comuna)
            if cli.ciudad:
                partes.append(cli.ciudad)
            partes.append("Chile")
            direccion_completa = ", ".join([x for x in partes if x])
            direcciones.append(direccion_completa)

            maps_to = "https://www.google.com/maps/dir/?api=1&destination=" + quote_plus(direccion_completa)

            paradas_ui.append({
                "parada": p,
                "direccion": direccion_completa,
                "maps_to": maps_to,
            })

        # Ruta completa: origen fijo -> waypoints clientes -> destino fijo
        if len(direcciones) == 0:
            maps_url = ""
        elif len(direcciones) <= MAX_WAYPOINTS_MAPS:
            base = "https://www.google.com/maps/dir/?api=1"
            origin = origen_fijo
            destination = origen_fijo
            waypoints = direcciones[:]

            params = f"&origin={quote_plus(origin)}&destination={quote_plus(destination)}"
            params += f"&waypoints={quote_plus('|'.join(waypoints))}"
            params += "&travelmode=driving"
            maps_url = base + params
        else:
            maps_url = ""
            aviso_maps = (
                f"Esta ruta tiene {len(direcciones)} paradas y Google Maps solo admite "
                f"{MAX_WAYPOINTS_MAPS} puntos en un enlace. Divide la ruta o navega "
                "parada por parada con el botón 'Ir a cliente' de cada una."
            )

    return render(request, "core/chofer_ruta.html", {
        "ruta": ruta,
        "paradas": paradas,
        "paradas_ui": paradas_ui,
        "hoy": hoy,
        "maps_url": maps_url,
        "aviso_maps": aviso_maps,
        "origen_fijo": origen_fijo,
        "progreso": progreso,
        "porcentaje_entregadas": porcentaje_entregadas,
        "siguiente_parada_id": siguiente_parada_id,
    })


@user_passes_test(es_chofer)
@require_POST
def chofer_marcar_parada_view(request, parada_id):
    parada = get_object_or_404(ParadaRuta, id=parada_id)

    chofer = get_object_or_404(Chofer, perfil__user=request.user)
    if parada.ruta.chofer != chofer:
        return redirect("chofer_ruta_hoy")

    accion = request.POST.get("accion")  # ENTREGADO | NO_ENTREGADO | REVERTIR
    motivo = (request.POST.get("motivo_no_entrega") or "").strip()
    comentario_chofer = (request.POST.get("comentario_chofer") or "").strip()

    if accion == "ENTREGADO":
        parada.estado_entrega = "ENTREGADO"
        parada.entregado = True  # compatibilidad
        parada.hora_entrega = timezone.now()
        parada.motivo_no_entrega = None
        parada.comentario_chofer = None

    elif accion == "NO_ENTREGADO":
        # motivo obligatorio para NO_ENTREGADO
        if not motivo:
            return redirect("chofer_ruta_hoy")

        parada.estado_entrega = "NO_ENTREGADO"
        parada.entregado = False  # compatibilidad
        parada.hora_entrega = timezone.now()
        parada.motivo_no_entrega = motivo
        parada.comentario_chofer = comentario_chofer if comentario_chofer else None

    elif accion == "REVERTIR":
        parada.estado_entrega = "PENDIENTE"
        parada.entregado = False  # compatibilidad
        parada.hora_entrega = None
        parada.motivo_no_entrega = None
        parada.comentario_chofer = None

    parada.save()

    # Actualiza el estado de la ruta después de guardar la parada
    ruta = parada.ruta
    paradas = ruta.paradas.all()
    progreso = {
        "total": paradas.count(),
        "entregadas": paradas.filter(estado_entrega="ENTREGADO").count(),
        "no_entregadas": paradas.filter(estado_entrega="NO_ENTREGADO").count(),
        "pendientes": paradas.filter(estado_entrega="PENDIENTE").count(),
    }
    _actualizar_estado_ruta_por_paradas(ruta, progreso)

    return redirect("chofer_ruta_hoy")

# =========================================================
# PRODUCTOS (catálogo, OWNER + ADMIN)
# =========================================================
@user_passes_test(es_admin_o_owner)
def lista_productos_view(request):
    empresa = get_empresa(request)
    productos = Producto.objects.filter(empresa=empresa)
    return render(request, "core/lista_productos.html", {"productos": productos})


@user_passes_test(es_admin_o_owner)
def crear_producto_view(request):
    mensaje = None
    error = None
    empresa = get_empresa(request)

    if request.method == "POST":
        nombre = request.POST.get("nombre")
        descripcion = request.POST.get("descripcion")
        precio = request.POST.get("precio")
        unidad = request.POST.get("unidad") or "unidad"
        stock_disponible = request.POST.get("stock_disponible") or 0

        if not (nombre and precio):
            error = "Nombre y precio son obligatorios."
        else:
            try:
                Producto.objects.create(
                    empresa=empresa,
                    nombre=nombre,
                    descripcion=descripcion,
                    precio=precio,
                    unidad=unidad,
                    stock_disponible=stock_disponible,
                )
                mensaje = "Producto creado correctamente."
            except (ValueError, TypeError):
                error = "Precio o stock inválido."

    return render(request, "core/crear_producto.html", {"mensaje": mensaje, "error": error})


@user_passes_test(es_admin_o_owner)
def editar_producto_view(request, producto_id):
    empresa = get_empresa(request)
    producto = get_object_or_404_scoped(Producto, empresa, id=producto_id)
    mensaje = None

    if request.method == "POST":
        producto.nombre = request.POST.get("nombre")
        producto.descripcion = request.POST.get("descripcion")
        producto.precio = request.POST.get("precio")
        producto.unidad = request.POST.get("unidad") or "unidad"
        producto.stock_disponible = request.POST.get("stock_disponible") or 0
        producto.disponible = request.POST.get("disponible") == "on"
        producto.save()
        mensaje = "Cambios guardados."

    return render(request, "core/editar_producto.html", {"producto": producto, "mensaje": mensaje})

# =========================================================
# CATÁLOGO Y CARRITO (armado por admin/vendedor para un cliente)
# =========================================================
@user_passes_test(es_admin_o_owner)
def catalogo_view(request):
    empresa = get_empresa(request)
    clientes = Cliente.objects.filter(empresa=empresa, activo=True).order_by("nombre")
    productos = Producto.objects.filter(empresa=empresa, disponible=True)

    carrito = Carrito(request)
    cliente_actual = None
    if carrito.cliente_id:
        cliente_actual = Cliente.objects.filter(empresa=empresa, id=carrito.cliente_id).first()

    return render(request, "core/catalogo.html", {
        "clientes": clientes,
        "productos": productos,
        "cliente_actual": cliente_actual,
        "cantidad_items_carrito": len(carrito.datos["items"]),
    })


@user_passes_test(es_admin_o_owner)
@require_POST
def seleccionar_cliente_carrito_view(request):
    empresa = get_empresa(request)
    cliente_id = request.POST.get("cliente_id")
    cliente = get_object_or_404_scoped(Cliente, empresa, id=cliente_id)

    carrito = Carrito(request)
    carrito.iniciar_para_cliente(cliente.id)
    return redirect("catalogo")


@user_passes_test(es_admin_o_owner)
@require_POST
def carrito_agregar_view(request, producto_id):
    empresa = get_empresa(request)
    producto = get_object_or_404_scoped(Producto, empresa, id=producto_id)

    carrito = Carrito(request)
    if not carrito.cliente_id:
        return redirect("catalogo")

    cantidad = request.POST.get("cantidad") or 1
    try:
        cantidad = int(cantidad)
    except ValueError:
        cantidad = 1

    carrito.agregar(producto.id, cantidad)
    return redirect("catalogo")


@user_passes_test(es_admin_o_owner)
def carrito_view(request):
    empresa = get_empresa(request)
    carrito = Carrito(request)

    cliente = None
    if carrito.cliente_id:
        cliente = Cliente.objects.filter(empresa=empresa, id=carrito.cliente_id).first()

    items = carrito.items(empresa)
    total = carrito.total(empresa)

    return render(request, "core/carrito.html", {
        "cliente": cliente,
        "items": items,
        "total": total,
    })


@user_passes_test(es_admin_o_owner)
@require_POST
def carrito_actualizar_view(request, producto_id):
    carrito = Carrito(request)
    cantidad = request.POST.get("cantidad") or 0
    try:
        cantidad = int(cantidad)
    except ValueError:
        cantidad = 0
    carrito.actualizar_cantidad(producto_id, cantidad)
    return redirect("carrito")


@user_passes_test(es_admin_o_owner)
@require_POST
def carrito_quitar_view(request, producto_id):
    carrito = Carrito(request)
    carrito.quitar(producto_id)
    return redirect("carrito")


@user_passes_test(es_admin_o_owner)
@require_POST
def carrito_vaciar_view(request):
    carrito = Carrito(request)
    carrito.vaciar()
    return redirect("carrito")


@user_passes_test(es_admin_o_owner)
@require_POST
def carrito_confirmar_view(request):
    empresa = get_empresa(request)
    carrito = Carrito(request)

    if not carrito.cliente_id or carrito.esta_vacio():
        return redirect("carrito")

    cliente = get_object_or_404_scoped(Cliente, empresa, id=carrito.cliente_id)
    items = carrito.items(empresa)

    pedido = Pedido.objects.create(empresa=empresa, cliente=cliente, creado_por=request.user)
    for item in items:
        PedidoItem.objects.create(
            pedido=pedido,
            producto=item["producto"],
            cantidad=item["cantidad"],
            precio_unitario=item["producto"].precio,
        )
    pedido.recalcular_total()

    carrito.vaciar()
    return redirect("detalle_pedido", pedido_id=pedido.id)

# =========================================================
# PEDIDOS (OWNER + ADMIN)
# =========================================================
@user_passes_test(es_admin_o_owner)
def lista_pedidos_view(request):
    empresa = get_empresa(request)
    pedidos_qs = Pedido.objects.filter(empresa=empresa).select_related("cliente")

    estado = request.GET.get("estado")
    if estado in dict(Pedido.ESTADO_CHOICES).keys():
        pedidos_qs = pedidos_qs.filter(estado=estado)

    paginator = Paginator(pedidos_qs, PAGINA_TAMANO)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "core/lista_pedidos.html", {
        "pedidos": page_obj, "page_obj": page_obj, "estado_filtro": estado,
    })


@user_passes_test(es_admin_o_owner)
def detalle_pedido_view(request, pedido_id):
    empresa = get_empresa(request)
    pedido = get_object_or_404_scoped(Pedido, empresa, id=pedido_id)
    items = pedido.items.select_related("producto")
    return render(request, "core/detalle_pedido.html", {"pedido": pedido, "items": items})


@user_passes_test(es_admin_o_owner)
@require_POST
def agregar_pedido_a_ruta_view(request, ruta_id):
    empresa = get_empresa(request)
    ruta = get_object_or_404_scoped(Ruta, empresa, id=ruta_id)
    pedido_id = request.POST.get("pedido_id")
    pedido = get_object_or_404_scoped(Pedido, empresa, id=pedido_id)

    if pedido.estado != "PENDIENTE":
        return redirect("detalle_ruta", ruta_id=ruta.id)

    if ruta.paradas.filter(cliente=pedido.cliente).exists():
        return redirect("detalle_ruta", ruta_id=ruta.id)

    ultimo = ruta.paradas.order_by("-orden").first()
    orden = (ultimo.orden + 1) if ultimo else 1

    ParadaRuta.objects.create(ruta=ruta, cliente=pedido.cliente, orden=orden, pedido=pedido)
    pedido.estado = "ASIGNADO"
    pedido.save(update_fields=["estado"])

    return redirect("detalle_ruta", ruta_id=ruta.id)

# =========================================================
# STAFF LOGIVISIR: revisar solicitudes, validar pago, aprovisionar cuenta
# =========================================================
TEMP_PASSWORD_CHARS = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789!@#$%"


def _generar_username(nombre_empresa):
    base = slugify(nombre_empresa)[:20].replace("-", "") or "empresa"
    username = base
    sufijo = 1
    while User.objects.filter(username=username).exists():
        sufijo += 1
        username = f"{base}{sufijo}"
    return username


@user_passes_test(es_staff_logivisir)
def lista_solicitudes_view(request):
    solicitudes = SolicitudCuenta.objects.all()
    estado = request.GET.get("estado")
    if estado in dict(SolicitudCuenta.ESTADO_CHOICES).keys():
        solicitudes = solicitudes.filter(estado=estado)
    return render(request, "core/staff_lista_solicitudes.html", {
        "solicitudes": solicitudes, "estado_filtro": estado,
    })


@user_passes_test(es_staff_logivisir)
def detalle_solicitud_view(request, solicitud_id):
    solicitud = get_object_or_404(SolicitudCuenta, id=solicitud_id)
    return render(request, "core/staff_detalle_solicitud.html", {"solicitud": solicitud})


@user_passes_test(es_staff_logivisir)
@require_POST
def marcar_pago_validado_view(request, solicitud_id):
    solicitud = get_object_or_404(SolicitudCuenta, id=solicitud_id)
    if solicitud.estado == "NUEVA":
        solicitud.estado = "PAGO_VALIDADO"
        solicitud.save(update_fields=["estado"])
        messages.success(request, "Pago marcado como validado.")
    return redirect("detalle_solicitud", solicitud_id=solicitud.id)


@user_passes_test(es_staff_logivisir)
@require_POST
def crear_cuenta_solicitud_view(request, solicitud_id):
    solicitud = get_object_or_404(SolicitudCuenta, id=solicitud_id)

    if solicitud.empresa_creada_id:
        messages.info(request, "Esta solicitud ya tiene una cuenta creada.")
        return redirect("detalle_solicitud", solicitud_id=solicitud.id)

    if solicitud.estado != "PAGO_VALIDADO":
        messages.error(request, "Primero debes marcar el pago como validado.")
        return redirect("detalle_solicitud", solicitud_id=solicitud.id)

    username = _generar_username(solicitud.nombre_empresa)
    temp_password = get_random_string(14, allowed_chars=TEMP_PASSWORD_CHARS)

    usuario = User.objects.create_user(
        username=username,
        password=temp_password,
        email=solicitud.email_contacto,
        first_name=solicitud.nombre_contacto,
    )
    empresa = Empresa.objects.create(nombre=solicitud.nombre_empresa, owner=usuario)
    PerfilUsuario.objects.create(
        user=usuario, empresa=empresa, rol="OWNER", debe_cambiar_password=True,
    )

    solicitud.empresa_creada = empresa
    solicitud.estado = "CUENTA_CREADA"
    solicitud.save(update_fields=["empresa_creada", "estado"])

    login_url = request.build_absolute_uri(reverse("login"))
    send_mail(
        subject="Tu cuenta de LogiVisir Solutions está lista",
        message=(
            f"Hola {solicitud.nombre_contacto},\n\n"
            f"Validamos tu pago y creamos tu cuenta para {solicitud.nombre_empresa}.\n\n"
            f"Ingresa en: {login_url}\n"
            f"Usuario: {username}\n"
            f"Contraseña temporal: {temp_password}\n\n"
            "Por seguridad, te pediremos cambiarla en tu primer inicio de sesión.\n\n"
            "Equipo LogiVisir Solutions"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[solicitud.email_contacto],
        fail_silently=True,
    )

    messages.success(request, f"Cuenta creada y credenciales enviadas a {solicitud.email_contacto}.")
    return redirect("detalle_solicitud", solicitud_id=solicitud.id)


@user_passes_test(es_staff_logivisir)
@require_POST
def rechazar_solicitud_view(request, solicitud_id):
    solicitud = get_object_or_404(SolicitudCuenta, id=solicitud_id)
    motivo = (request.POST.get("motivo") or "").strip()

    solicitud.estado = "RECHAZADA"
    if motivo:
        nota = f"Rechazada: {motivo}"
        solicitud.notas_internas = f"{solicitud.notas_internas}\n{nota}" if solicitud.notas_internas else nota
    solicitud.save(update_fields=["estado", "notas_internas"])

    messages.info(request, "Solicitud rechazada.")
    return redirect("detalle_solicitud", solicitud_id=solicitud.id)
