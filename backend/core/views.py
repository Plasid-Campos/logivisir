from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.utils import timezone
from django.views.decorators.http import require_POST
from urllib.parse import quote_plus

from .models import (
    PerfilUsuario,
    Chofer,
    Cliente,
    Ruta,
    ParadaRuta,
)

# =========================================================
# CONFIG
# =========================================================
ORIGEN_FIJO = "Salesianos 768, San Miguel, Chile"
MAX_WAYPOINTS_MAPS = 20  # evita que Maps falle

# =========================================================
# HOME / LANDING
# =========================================================
def home_view(request):
    return render(request, "core/home.html")

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

            if next_url:
                return redirect(next_url)

            if perfil and perfil.rol == "CHOFER":
                return redirect("chofer_ruta_hoy")

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

# =========================================================
# DASHBOARD
# =========================================================
@login_required
def dashboard_view(request):
    perfil = getattr(request.user, "perfilusuario", None)

    clientes_activos = Cliente.objects.filter(activo=True).count()
    choferes_activos = Chofer.objects.filter(activo=True).count()

    hoy = timezone.localdate()
    rutas_hoy_qs = Ruta.objects.filter(fecha=hoy, activa=True)

    rutas_pendientes = rutas_hoy_qs.exclude(estado="COMPLETADA").count()

    return render(request, "core/dashboard.html", {
        "perfil": perfil,
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
@user_passes_test(es_owner)
def crear_usuario_view(request):
    mensaje = None
    error = None

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        nombre = request.POST.get("nombre")
        apellido = request.POST.get("apellido")
        rol = request.POST.get("rol")
        email = request.POST.get("email")

        if User.objects.filter(username=username).exists():
            error = f"El nombre de usuario '{username}' ya existe. Elige otro."
        else:
            user = User.objects.create_user(
                username=username,
                password=password,
                first_name=nombre,
                last_name=apellido,
                email=email,
            )
            PerfilUsuario.objects.create(user=user, rol=rol)
            mensaje = f"Usuario '{username}' creado correctamente."

    return render(request, "core/crear_usuario.html", {"mensaje": mensaje, "error": error})

# =========================================================
# CHOFERES (OWNER + ADMIN)
# =========================================================
@user_passes_test(es_admin_o_owner)
def lista_choferes_view(request):
    choferes = Chofer.objects.select_related("perfil", "perfil__user").all()
    return render(request, "core/lista_choferes.html", {"choferes": choferes})


@user_passes_test(es_admin_o_owner)
def crear_chofer_view(request):
    mensaje = None
    error = None

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
        else:
            try:
                user = User.objects.create_user(
                    username=username,
                    password=password,
                    first_name=nombre,
                    last_name=apellido,
                    email=email,
                )
                perfil = PerfilUsuario.objects.create(user=user, rol="CHOFER")
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
    chofer = get_object_or_404(Chofer, id=chofer_id)
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
def eliminar_chofer_view(request, chofer_id):
    chofer = get_object_or_404(Chofer, id=chofer_id)
    usuario = chofer.perfil.user
    usuario.delete()
    return redirect("lista_choferes")

# =========================================================
# CLIENTES (OWNER + ADMIN)
# =========================================================
@user_passes_test(es_admin_o_owner)
def lista_clientes_view(request):
    clientes = Cliente.objects.all().order_by("nombre")
    return render(request, "core/lista_clientes.html", {"clientes": clientes})


@user_passes_test(es_admin_o_owner)
def crear_cliente_view(request):
    mensaje = None
    error = None

    if request.method == "POST":
        rut = request.POST.get("rut")
        nombre = request.POST.get("nombre")
        direccion = request.POST.get("direccion")
        comuna = request.POST.get("comuna")
        ciudad = request.POST.get("ciudad")
        telefono = request.POST.get("telefono")
        email = request.POST.get("email")

        if Cliente.objects.filter(rut=rut).exists():
            error = f"Ya existe un cliente con el RUT {rut}."
        else:
            Cliente.objects.create(
                rut=rut, nombre=nombre, direccion=direccion,
                comuna=comuna, ciudad=ciudad, telefono=telefono, email=email
            )
            mensaje = "Cliente creado correctamente."

    return render(request, "core/crear_cliente.html", {"mensaje": mensaje, "error": error})


@user_passes_test(es_admin_o_owner)
def editar_cliente_view(request, cliente_id):
    cliente = get_object_or_404(Cliente, id=cliente_id)
    mensaje = None

    if request.method == "POST":
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

        cliente.save()
        mensaje = "Cambios guardados."

    return render(request, "core/editar_cliente.html", {"cliente": cliente, "mensaje": mensaje})


@user_passes_test(es_admin_o_owner)
def desactivar_cliente_view(request, cliente_id):
    cliente = get_object_or_404(Cliente, id=cliente_id)
    cliente.activo = False
    if not cliente.motivo_inactivo:
        cliente.motivo_inactivo = "Inactivado manualmente."
    cliente.save()
    return redirect("lista_clientes")


@user_passes_test(es_owner)
def eliminar_cliente_view(request, cliente_id):
    cliente = get_object_or_404(Cliente, id=cliente_id)
    cliente.delete()
    return redirect("lista_clientes")

# =========================================================
# RUTAS (OWNER + ADMIN)
# =========================================================
@user_passes_test(es_admin_o_owner)
def lista_rutas_view(request):
    rutas = Ruta.objects.select_related("chofer", "chofer__perfil__user").order_by("-fecha", "-creada_en")
    return render(request, "core/lista_rutas.html", {"rutas": rutas})


@user_passes_test(es_admin_o_owner)
def crear_ruta_view(request):
    mensaje = None
    error = None
    choferes = Chofer.objects.filter(activo=True).select_related("perfil__user")

    if request.method == "POST":
        nombre = request.POST.get("nombre")
        fecha = request.POST.get("fecha")
        chofer_id = request.POST.get("chofer_id")

        if not (nombre and fecha and chofer_id):
            error = "Todos los campos son obligatorios."
        else:
            try:
                chofer = Chofer.objects.get(id=chofer_id)
                ruta = Ruta.objects.create(nombre=nombre, fecha=fecha, chofer=chofer)
                return redirect("detalle_ruta", ruta_id=ruta.id)
            except Chofer.DoesNotExist:
                error = "El chofer seleccionado no existe."

    return render(request, "core/crear_ruta.html", {"mensaje": mensaje, "error": error, "choferes": choferes})


@user_passes_test(es_admin_o_owner)
def detalle_ruta_view(request, ruta_id):
    ruta = get_object_or_404(Ruta, id=ruta_id)
    paradas = ruta.paradas.select_related("cliente").all()
    clientes_activos = Cliente.objects.filter(activo=True).order_by("nombre")
    return render(request, "core/detalle_ruta.html", {"ruta": ruta, "paradas": paradas, "clientes": clientes_activos})


@user_passes_test(es_admin_o_owner)
def agregar_parada_view(request, ruta_id):
    ruta = get_object_or_404(Ruta, id=ruta_id)

    if request.method == "POST":
        cliente_id = request.POST.get("cliente_id")
        orden = request.POST.get("orden")
        comentario = request.POST.get("comentario")

        if not cliente_id:
            return redirect("detalle_ruta", ruta_id=ruta.id)

        cliente = get_object_or_404(Cliente, id=cliente_id)

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
def eliminar_parada_view(request, parada_id):
    parada = get_object_or_404(ParadaRuta, id=parada_id)
    ruta_id = parada.ruta.id
    parada.delete()
    return redirect("detalle_ruta", ruta_id=ruta_id)


@user_passes_test(es_admin_o_owner)
def toggle_parada_entregada_view(request, parada_id):
    parada = get_object_or_404(ParadaRuta, id=parada_id)

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
    ruta = get_object_or_404(Ruta, id=ruta_id)

    if request.method == "POST":
        nuevo_estado = request.POST.get("estado")
        if nuevo_estado in dict(Ruta.ESTADO_CHOICES).keys():
            ruta.estado = nuevo_estado
            ruta.save()

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

    ruta = Ruta.objects.filter(chofer=chofer, fecha=hoy, activa=True).order_by("-creada_en").first()

    paradas = []
    paradas_ui = []
    maps_url = ""
    progreso = {"total": 0, "entregadas": 0, "no_entregadas": 0, "pendientes": 0}
    siguiente_parada_id = None
    porcentaje_entregadas = 0  # ✅ nuevo

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
        if 1 <= len(direcciones) <= MAX_WAYPOINTS_MAPS:
            base = "https://www.google.com/maps/dir/?api=1"
            origin = ORIGEN_FIJO
            destination = ORIGEN_FIJO
            waypoints = direcciones[:]

            params = f"&origin={quote_plus(origin)}&destination={quote_plus(destination)}"
            params += f"&waypoints={quote_plus('|'.join(waypoints))}"
            params += "&travelmode=driving"
            maps_url = base + params
        else:
            maps_url = ""

    return render(request, "core/chofer_ruta.html", {
        "ruta": ruta,
        "paradas": paradas,
        "paradas_ui": paradas_ui,
        "hoy": hoy,
        "maps_url": maps_url,
        "origen_fijo": ORIGEN_FIJO,
        "progreso": progreso,
        "porcentaje_entregadas": porcentaje_entregadas,  # ✅ nuevo
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
            # Sin mensajes todavía (no importaste messages). Simple: volver.
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
