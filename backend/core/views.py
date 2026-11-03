import csv
import os
import re

from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone
from datetime import date, timedelta
from django.utils.crypto import get_random_string
from django.utils.text import slugify
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from urllib.parse import quote_plus, urlencode

from . import analytics
from .maps import MAX_WAYPOINTS, armar_tramos
from .geocoding import geocodificar_direccion
from .notifications import (
    avisar_ruta_actualizada, avisar_ruta_asignada, avisar_ruta_quitada, fecha_legible,
)
from .cuentas import (
    acusar_recibo_solicitud, avisar_cambio_password, enviar_bienvenida, validar_email_nuevo_usuario,
    datos_transferencia, normalizar_rut,
)
from .models import (
    PerfilUsuario,
    Chofer,
    Cliente,
    Ruta,
    ParadaRuta,
    Pedido,
    Empresa,
    Notificacion,
    SolicitudCuenta,
    Pago,
)
from .tenancy import get_empresa, get_object_or_404_scoped
from . import membresias, primeros_pasos

# =========================================================
# CONFIG
# =========================================================
PAGINA_TAMANO = 25

# =========================================================
# HOME / LANDING
# =========================================================
def home_view(request):
    return render(request, "core/home.html", {
        "planes": membresias.planes_publicos(),
        "funciones_comunes": membresias.FUNCIONES_TODOS_LOS_PLANES,
        "faqs": PREGUNTAS_FRECUENTES,
    })


# Respuestas honestas a las dudas típicas de quien todavía no nos conoce.
PREGUNTAS_FRECUENTES = (
    ("¿Necesito saber de computación para usarlo?",
     "No. Si usas WhatsApp y Google Maps, puedes usar LogiVisir. Al entrar por primera vez "
     "te guiamos paso a paso para crear tu primera ruta."),
    ("¿Cuánto me demoro en empezar?",
     "Validamos tu pago y creamos tu cuenta en menos de 24 horas hábiles. Con tus clientes "
     "cargados, tu primera ruta optimizada sale en minutos."),
    ("¿Mis choferes necesitan instalar algo?",
     "No. Cada chofer entra desde el navegador de su celular con su propio usuario, ve solo "
     "su ruta del día y abre cada parada en Google Maps."),
    ("¿Quién puede ver mis datos?",
     "Solo las personas de tu empresa. Cada empresa tiene su propio espacio aislado y el "
     "equipo LogiVisir no ve tus clientes, pedidos ni rutas: solo los datos de tu membresía."),
    ("¿Cómo pago mi plan?",
     "Por transferencia bancaria con un código de referencia único. Subes el comprobante, "
     "lo validamos y activamos tu cuenta. Puedes pagar 1, 3, 6 o 12 meses."),
    ("¿Funciona fuera de Santiago?",
     "Sí. Las distancias salen del mapa abierto OpenStreetMap, que cubre todo Chile."),
    ("¿Avisa a mis clientes cuando va el chofer?",
     "Todavía no. Hoy los avisos llegan a tu equipo (dueño, administrador y chofer). "
     "El aviso al cliente final está en nuestro plan de trabajo."),
    ("¿Puedo cambiar de plan más adelante?",
     "Sí. Escríbenos cuando tu operación crezca y ajustamos tu plan sin perder tu "
     "historial de clientes ni de rutas."),
)

# =========================================================
# SOLICITUD DE CUENTA (venta del servicio, público)
# =========================================================
PLANES_VALIDOS = dict(SolicitudCuenta.PLAN_CHOICES).keys()


CAMPOS_SOLICITUD = (
    "nombre_empresa", "rut_empresa", "rubro", "direccion", "comuna", "ciudad",
    "nombre_contacto", "telefono_contacto", "email_contacto", "mensaje",
)
EXTENSIONES_COMPROBANTE = (".pdf", ".jpg", ".jpeg", ".png")
MAX_COMPROBANTE_MB = 5
SESION_SOLICITUDES = "solicitudes_enviadas"


def _error_comprobante(archivo):
    if not archivo:
        return "Adjunta el comprobante de la transferencia."
    if os.path.splitext(archivo.name)[1].lower() not in EXTENSIONES_COMPROBANTE:
        return "El comprobante debe ser PDF, JPG o PNG."
    if archivo.size > MAX_COMPROBANTE_MB * 1024 * 1024:
        return f"El comprobante no puede pesar más de {MAX_COMPROBANTE_MB} MB."
    return None


def _guardar_comprobante(solicitud, archivo):
    if solicitud.comprobante:
        solicitud.comprobante.delete(save=False)
    solicitud.comprobante = archivo
    solicitud.comprobante_subido_en = timezone.now()
    solicitud.save(update_fields=["comprobante", "comprobante_subido_en"])


def solicitar_cuenta_view(request):
    error = None
    plan_preseleccionado = request.GET.get("plan", "")
    if plan_preseleccionado not in PLANES_VALIDOS:
        plan_preseleccionado = ""
    datos = {campo: "" for campo in CAMPOS_SOLICITUD}
    datos["ciudad"] = "Santiago"

    if request.method == "POST":
        datos = {campo: (request.POST.get(campo) or "").strip() for campo in CAMPOS_SOLICITUD}
        plan_solicitado = request.POST.get("plan_solicitado")
        plan_preseleccionado = plan_solicitado if plan_solicitado in PLANES_VALIDOS else ""
        rut = normalizar_rut(datos["rut_empresa"])

        obligatorios = ("nombre_empresa", "rut_empresa", "direccion", "comuna",
                        "nombre_contacto", "telefono_contacto", "email_contacto")
        if not all(datos[c] for c in obligatorios):
            error = "Completa los datos de la empresa (nombre, RUT, dirección y comuna) y los de contacto."
        elif plan_solicitado not in PLANES_VALIDOS:
            error = "Selecciona un plan válido."
        elif rut is None:
            error = "El RUT de la empresa no es válido. Revisa el número y el dígito verificador."
        elif Empresa.objects.filter(rut_empresa=rut).exists():
            error = "Ya existe una empresa registrada con ese RUT. Si ya eres cliente, inicia sesión."
        else:
            try:
                validate_email(datos["email_contacto"])
            except ValidationError:
                error = "Revisa el correo electrónico."
        if error is None:
            solicitud = SolicitudCuenta.objects.create(
                nombre_empresa=datos["nombre_empresa"], rut_empresa=rut, rubro=datos["rubro"],
                direccion=datos["direccion"], comuna=datos["comuna"], ciudad=datos["ciudad"] or "Santiago",
                nombre_contacto=datos["nombre_contacto"], telefono_contacto=datos["telefono_contacto"],
                email_contacto=datos["email_contacto"], plan_solicitado=plan_solicitado,
                mensaje=datos["mensaje"],
            )
            # Solo quien envió la solicitud (o el equipo) puede ver su confirmación.
            enviadas = request.session.get(SESION_SOLICITUDES, [])
            request.session[SESION_SOLICITUDES] = (enviadas + [solicitud.id])[-10:]
            acusar_recibo_solicitud(solicitud, request)
            return redirect("solicitud_confirmacion", solicitud_id=solicitud.id)

    return render(request, "core/solicitar_cuenta.html", {
        "error": error,
        "plan_preseleccionado": plan_preseleccionado,
        "planes": SolicitudCuenta.PLAN_CHOICES,
        "datos": datos,
    })


def solicitud_confirmacion_view(request, solicitud_id):
    es_propia = solicitud_id in request.session.get(SESION_SOLICITUDES, [])
    if not (es_propia or request.user.is_staff):
        raise Http404
    solicitud = get_object_or_404(SolicitudCuenta, id=solicitud_id)
    error = None
    if request.method == "POST" and solicitud.estado == "NUEVA":
        archivo = request.FILES.get("comprobante")
        error = _error_comprobante(archivo)
        if error is None:
            _guardar_comprobante(solicitud, archivo)
            messages.success(request, "Recibimos tu comprobante. Te avisaremos por correo cuando validemos el pago.")
            return redirect("solicitud_confirmacion", solicitud_id=solicitud.id)
    return render(request, "core/solicitud_confirmacion.html", {
        "solicitud": solicitud,
        "pago": datos_transferencia(),
        "monto": membresias.PRECIOS_PLAN.get(solicitud.plan_solicitado, 0),
        "error": error,
    })


def subir_comprobante_view(request):
    """
    Para quien cerró la página de confirmación: identifica su solicitud con el
    código SOL y el correo con que la envió (ambos deben coincidir).
    """
    error = None
    codigo = (request.POST.get("codigo") or request.GET.get("codigo") or "").strip().upper()
    email = (request.POST.get("email") or "").strip()
    if request.method == "POST":
        numero = re.sub(r"\D", "", codigo)
        solicitud = SolicitudCuenta.objects.filter(
            id=int(numero) if numero else 0, email_contacto__iexact=email,
        ).first()
        if solicitud is None:
            error = "No encontramos una solicitud con ese código y ese correo."
        elif solicitud.estado != "NUEVA":
            error = "Esta solicitud ya fue revisada; no necesitas subir el comprobante."
        else:
            error = _error_comprobante(request.FILES.get("comprobante"))
            if error is None:
                _guardar_comprobante(solicitud, request.FILES["comprobante"])
                return render(request, "core/subir_comprobante.html", {"listo": True, "solicitud": solicitud})
    return render(request, "core/subir_comprobante.html", {"error": error, "codigo": codigo, "email": email})

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
        if usuario is None:
            # authenticate no distingue "clave mala" de "cuenta desactivada":
            # si la clave es correcta pero la cuenta esta inactiva, se explica.
            inactivo = User.objects.filter(username=username, is_active=False).first()
            if inactivo and inactivo.check_password(password or ""):
                mensaje_error = "Tu cuenta está desactivada. Habla con el dueño de tu empresa para reactivarla."
                return render(request, "core/login.html", {"mensaje_error": mensaje_error, "next": next_url})
        if usuario is not None:
            perfil = getattr(usuario, "perfilusuario", None)

            # Empresa suspendida por LogiVisir (ej: plan impago): sus
            # usuarios no entran hasta que el staff la reactive.
            if perfil and not usuario.is_staff and not perfil.empresa.activa:
                mensaje_error = (
                    "La cuenta de tu empresa está suspendida. "
                    "Contacta a LogiVisir Solutions para reactivarla."
                )
                return render(request, "core/login.html", {"mensaje_error": mensaje_error, "next": next_url})

            login(request, usuario)

            # Cuentas recien aprovisionadas por el staff deben cambiar su
            # password temporal antes de hacer cualquier otra cosa. Este
            # chequeo va antes de mirar next_url a proposito, para que no
            # se pueda saltar con un ?next= manual.
            if perfil and perfil.debe_cambiar_password:
                return redirect("cambiar_password_obligatorio")

            # Solo rutas internas: un ?next= hacia otro dominio permitiria
            # usar el login de LogiVisir para redirigir a un sitio falso.
            if next_url and url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
            ):
                return redirect(next_url)

            # El equipo LogiVisir no es un tenant: siempre entra a su propio
            # panel, aunque la cuenta tambien figure como usuario de una empresa.
            if usuario.is_staff:
                return redirect("staff_panel")

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
# Los roles de empresa (OWNER, ADMIN, CHOFER) nunca aplican al equipo
# LogiVisir: aunque una cuenta del staff figure como usuario de una empresa,
# no puede ver sus clientes, rutas, pedidos ni choferes (privacidad).
def es_owner(user):
    if user.is_staff:
        return False
    try:
        return user.perfilusuario.rol == "OWNER"
    except Exception:
        return False


def es_admin_o_owner(user):
    if user.is_staff:
        return False
    try:
        return user.perfilusuario.rol in ("ADMIN", "OWNER")
    except Exception:
        return False


def es_chofer(user):
    if user.is_staff:
        return False
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
            avisar_cambio_password(request.user, request)

            if perfil and perfil.rol == "CHOFER":
                return redirect("chofer_ruta_hoy")
            return redirect("dashboard")

    return render(request, "core/cambiar_password_obligatorio.html", {"error": error})

# =========================================================
# DASHBOARD
# =========================================================
@login_required
def dashboard_view(request):
    if request.user.is_staff:
        return redirect("staff_panel")
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
        "guia": primeros_pasos.resumen(empresa),
        "resumen": {
            "clientes_activos": clientes_activos,
            "choferes_activos": choferes_activos,
            "rutas_hoy": rutas_hoy_qs.count(),
            "rutas_hoy_pendientes": rutas_pendientes,
        }
    })

@login_required
def ayuda_view(request):
    """Guía de uso de las empresas; el equipo LogiVisir tiene su propio panel."""
    if request.user.is_staff:
        return redirect("staff_panel")
    return render(request, "core/ayuda.html")


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
        elif validar_email_nuevo_usuario(email):
            error = validar_email_nuevo_usuario(email)
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
                email=email.strip(),
            )
            # La clave la eligio el dueño: el usuario debe cambiarla al entrar
            PerfilUsuario.objects.create(user=user, rol=rol, empresa=empresa, debe_cambiar_password=True)
            enviar_bienvenida(user, empresa, request)
            mensaje = (
                f"Usuario '{username}' creado. Le enviamos un correo de bienvenida; "
                "deberá cambiar la contraseña en su primer ingreso."
            )

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
    """
    Alta rápida: basta nombre, apellido y correo. El usuario y la clave
    temporal se generan solos y se muestran una vez en pantalla para que el
    dueño se los entregue al chofer (la clave nunca viaja por correo).
    """
    empresa = get_empresa(request)
    error = None
    creado = None
    datos = {}

    if request.method == "POST":
        datos = {k: (request.POST.get(k) or "").strip() for k in (
            "nombre", "apellido", "email", "rut", "telefono", "licencia", "patente", "username", "password",
        )}
        username = datos["username"] or _generar_username_persona(datos["nombre"], datos["apellido"])
        password = datos["password"] or get_random_string(10, allowed_chars=TEMP_PASSWORD_CHARS)

        if not datos["nombre"] or not datos["apellido"]:
            error = "Escribe el nombre y el apellido del chofer."
        elif User.objects.filter(username=username).exists():
            error = f"El nombre de usuario '{username}' ya existe. Usa otro."
        elif datos["rut"] and Chofer.objects.filter(rut=datos["rut"]).exists():
            error = f"Ya existe un chofer con el RUT {datos['rut']}."
        elif validar_email_nuevo_usuario(datos["email"]):
            error = validar_email_nuevo_usuario(datos["email"])
        elif datos["password"]:
            try:
                validate_password(password)
            except ValidationError as e:
                error = " ".join(e.messages)

        if not error:
            try:
                with transaction.atomic():
                    user = User.objects.create_user(
                        username=username, password=password,
                        first_name=datos["nombre"], last_name=datos["apellido"], email=datos["email"],
                    )
                    perfil = PerfilUsuario.objects.create(
                        user=user, rol="CHOFER", empresa=empresa, debe_cambiar_password=True,
                    )
                    Chofer.objects.create(
                        perfil=perfil, rut=datos["rut"] or None, telefono=datos["telefono"],
                        licencia=datos["licencia"], patente=datos["patente"],
                    )
                enviar_bienvenida(user, empresa, request)
                creado = {
                    "nombre": user.get_full_name(), "username": username,
                    "clave": None if datos["password"] else password,
                }
                datos = {}
            except IntegrityError:
                error = "Error al guardar. Verifica usuario y RUT."

    return render(request, "core/crear_chofer.html", {"error": error, "creado": creado, "datos": datos})


def _generar_username_persona(nombre, apellido):
    """manuel.castro, manuel.castro2, ... (sin tildes ni espacios)."""
    base = ".".join(p for p in (slugify(nombre).split("-")[0], slugify(apellido).split("-")[0]) if p)[:24] or "chofer"
    username, sufijo = base, 1
    while User.objects.filter(username=username).exists():
        sufijo += 1
        username = f"{base}{sufijo}"
    return username


@user_passes_test(es_admin_o_owner)
def editar_chofer_view(request, chofer_id):
    empresa = get_empresa(request)
    chofer = get_object_or_404_scoped(Chofer, empresa, lookup_field="perfil__empresa", id=chofer_id)
    mensaje = None

    if request.method == "POST":
        chofer.rut = (request.POST.get("rut") or "").strip() or None
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

    # Con rutas no se puede borrar (las rutas protegen al chofer) ni se debe:
    # se perderia el historial de entregas. Se desactiva.
    if chofer.rutas.exists():
        _desactivar_usuario(chofer.perfil)
        messages.warning(
            request,
            "El chofer tiene rutas registradas, así que se desactivó en vez de borrarse: "
            "ya no puede ingresar ni recibir rutas, pero su historial se conserva.",
        )
    else:
        chofer.perfil.user.delete()
        messages.success(request, "Chofer eliminado.")
    return redirect("lista_choferes")

# =========================================================
# CLIENTES (OWNER + ADMIN)
# =========================================================
@user_passes_test(es_admin_o_owner)
def lista_clientes_view(request):
    empresa = get_empresa(request)
    clientes_qs = Cliente.objects.filter(empresa=empresa).order_by("nombre")

    q = (request.GET.get("q") or "").strip()
    comuna = (request.GET.get("comuna") or "").strip()
    tipo = (request.GET.get("tipo") or "").strip()
    estado = (request.GET.get("estado") or "").strip()
    ubicacion = (request.GET.get("ubicacion") or "").strip()

    if q:
        clientes_qs = clientes_qs.filter(
            Q(nombre__icontains=q) | Q(direccion__icontains=q) | Q(rut__icontains=q)
        )
    if comuna:
        clientes_qs = clientes_qs.filter(comuna=comuna)
    if tipo in dict(Cliente.TIPO_CHOICES).keys():
        clientes_qs = clientes_qs.filter(tipo_cliente=tipo)
    if estado == "activos":
        clientes_qs = clientes_qs.filter(activo=True)
    elif estado == "inactivos":
        clientes_qs = clientes_qs.filter(activo=False)
    # CU-02 (2b): los clientes sin coordenadas quedan al final de las rutas
    # sin optimizar, asi que deben poder encontrarse y corregirse.
    if ubicacion == "sin":
        clientes_qs = clientes_qs.filter(SIN_UBICACION)
    elif ubicacion == "con":
        clientes_qs = clientes_qs.exclude(SIN_UBICACION)

    comunas_disponibles = (
        Cliente.objects.filter(empresa=empresa)
        .exclude(comuna="")
        .exclude(comuna__isnull=True)
        .order_by("comuna")
        .values_list("comuna", flat=True)
        .distinct()
    )

    paginator = Paginator(clientes_qs, PAGINA_TAMANO)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "core/lista_clientes.html", {
        "clientes": page_obj,
        "page_obj": page_obj,
        "comunas_disponibles": comunas_disponibles,
        "tipos_cliente": Cliente.TIPO_CHOICES,
        "filtro_q": q,
        "filtro_comuna": comuna,
        "filtro_tipo": tipo,
        "filtro_estado": estado,
        "filtro_ubicacion": ubicacion,
        "total_filtrado": clientes_qs.count(),
        "activos_sin_ubicacion": Cliente.objects.filter(empresa=empresa, activo=True).filter(SIN_UBICACION).count(),
        "reubicar_lote": REUBICAR_LOTE,
    })


@user_passes_test(es_admin_o_owner)
def crear_cliente_view(request):
    """
    Alta rápida: nombre, dirección y comuna a la vista; el resto es opcional.
    «Guardar y agregar otro» deja el formulario listo para el siguiente,
    recordando comuna, ciudad y tipo (lo normal es cargar varios seguidos).
    """
    error = None
    empresa = get_empresa(request)
    datos = {"ciudad": empresa.ciudad_origen or "", "tipo_cliente": "NORMAL"}
    recien = None

    if request.method == "POST":
        datos = {k: (request.POST.get(k) or "").strip() for k in (
            "rut", "nombre", "direccion", "comuna", "ciudad", "telefono", "email", "tipo_cliente",
        )}
        if datos["tipo_cliente"] not in dict(Cliente.TIPO_CHOICES):
            datos["tipo_cliente"] = "NORMAL"
        rut = datos["rut"] or None

        if not datos["nombre"] or not datos["direccion"]:
            error = "Escribe al menos el nombre y la dirección del cliente."
        elif rut and Cliente.objects.filter(empresa=empresa, rut=rut).exists():
            error = f"Ya existe un cliente con el RUT {rut}."
        else:
            cliente = Cliente.objects.create(
                empresa=empresa, rut=rut, nombre=datos["nombre"], direccion=datos["direccion"],
                comuna=datos["comuna"] or None, ciudad=datos["ciudad"] or None,
                telefono=datos["telefono"] or None, email=datos["email"] or None,
                tipo_cliente=datos["tipo_cliente"],
            )
            from .geocoding import geocodificar_cliente
            ubicado = geocodificar_cliente(cliente)
            if request.POST.get("accion") == "otro":
                recien = {"cliente": cliente, "ubicado": ubicado}
                datos = {k: datos[k] for k in ("comuna", "ciudad", "tipo_cliente")}
            else:
                if ubicado:
                    messages.success(request, f"{cliente.nombre} quedó guardado y ubicado en el mapa.")
                else:
                    messages.warning(
                        request,
                        f"{cliente.nombre} quedó guardado, pero no pudimos ubicar la dirección. "
                        "Revísala para que la ruta pueda optimizarse.",
                    )
                return redirect("lista_clientes")

    comunas = (
        Cliente.objects.filter(empresa=empresa).exclude(comuna__isnull=True).exclude(comuna="")
        .values_list("comuna", flat=True).distinct().order_by("comuna")
    )
    return render(request, "core/crear_cliente.html", {
        "error": error, "datos": datos, "recien": recien,
        "tipos_cliente": Cliente.TIPO_CHOICES, "comunas": list(comunas),
    })

@user_passes_test(es_admin_o_owner)
def editar_cliente_view(request, cliente_id):
    empresa = get_empresa(request)
    cliente = get_object_or_404_scoped(Cliente, empresa, id=cliente_id)
    mensaje = None
    error = None

    if request.method == "POST":
        try:
            coordenadas_manuales = _leer_coordenadas(request.POST.get("coordenadas"))
        except ValueError as e:
            error = str(e)
            return render(request, "core/editar_cliente.html", {
                "cliente": cliente, "error": error, "tipos_cliente": Cliente.TIPO_CHOICES,
                "mapa": _urls_mapa(cliente.latitud, cliente.longitud),
            })
        direccion_anterior = (cliente.direccion, cliente.comuna, cliente.ciudad)

        cliente.rut = (request.POST.get("rut") or "").strip() or None
        cliente.nombre = request.POST.get("nombre")
        cliente.direccion = request.POST.get("direccion")
        cliente.comuna = request.POST.get("comuna")
        cliente.ciudad = request.POST.get("ciudad")
        cliente.telefono = request.POST.get("telefono")
        cliente.email = request.POST.get("email")
        cliente.activo = request.POST.get("activo") == "on"
        cliente.motivo_inactivo = request.POST.get("motivo_inactivo")

        tipo_cliente = request.POST.get("tipo_cliente")
        if tipo_cliente in dict(Cliente.TIPO_CHOICES).keys():
            cliente.tipo_cliente = tipo_cliente

        if cliente.activo:
            cliente.motivo_inactivo = ""

        direccion_nueva = (cliente.direccion, cliente.comuna, cliente.ciudad)
        cliente.save()
        mensaje = "Cambios guardados."

        if coordenadas_manuales:
            cliente.latitud, cliente.longitud = coordenadas_manuales
            cliente.geocodificado = True
            cliente.save(update_fields=["latitud", "longitud", "geocodificado"])
            mensaje += " Ubicación fijada con las coordenadas que indicaste."
        elif direccion_nueva != direccion_anterior:
            from .geocoding import geocodificar_cliente
            if not geocodificar_cliente(cliente):
                mensaje += " No se pudo ubicar la nueva dirección en el mapa: pega sus coordenadas desde Google Maps."

    return render(request, "core/editar_cliente.html", {
        "cliente": cliente, "mensaje": mensaje, "error": error, "tipos_cliente": Cliente.TIPO_CHOICES,
        "mapa": _urls_mapa(cliente.latitud, cliente.longitud),
    })


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

    # Pedidos y paradas protegen al cliente: borrarlo fallaria y perderia el
    # historial de despachos. Con historial, se desactiva.
    if cliente.pedidos.exists() or ParadaRuta.objects.filter(cliente=cliente).exists():
        cliente.activo = False
        cliente.motivo_inactivo = "Desactivado al intentar eliminarlo (tiene historial de despachos)."
        cliente.save(update_fields=["activo", "motivo_inactivo"])
        messages.warning(
            request,
            f"{cliente.nombre} tiene pedidos o entregas registradas, así que se desactivó en vez de "
            "borrarse: no aparecerá para nuevos pedidos, pero su historial se conserva.",
        )
    else:
        cliente.delete()
        messages.success(request, "Cliente eliminado.")
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
    hoy = timezone.localdate()

    if request.method == "POST":
        nombre = request.POST.get("nombre")
        fecha = request.POST.get("fecha")
        chofer_id = request.POST.get("chofer_id")

        if not (nombre and fecha and chofer_id):
            error = "Todos los campos son obligatorios."
        else:
            try:
                fecha_parseada = date.fromisoformat(fecha)
            except ValueError:
                fecha_parseada = None

            if not fecha_parseada:
                error = "La fecha no es válida."
            elif fecha_parseada < hoy:
                error = f"La fecha no puede ser anterior a hoy ({hoy.strftime('%d-%m-%Y')})."
            else:
                try:
                    chofer = Chofer.objects.get(id=chofer_id, perfil__empresa=empresa)
                    ruta = Ruta.objects.create(nombre=nombre, fecha=fecha_parseada, chofer=chofer, empresa=empresa)

                    resultado_email = avisar_ruta_asignada(ruta, request)
                    if resultado_email.get("enviado"):
                        messages.info(request, "Se avisó al chofer en la plataforma y por correo.")
                    else:
                        messages.info(request, "Se avisó al chofer en la plataforma.")

                    return redirect("detalle_ruta", ruta_id=ruta.id)
                except Chofer.DoesNotExist:
                    error = "El chofer seleccionado no existe."

    return render(request, "core/crear_ruta.html", {
        "mensaje": mensaje, "error": error, "choferes": choferes, "hoy": hoy,
    })


@user_passes_test(es_admin_o_owner)
def detalle_ruta_view(request, ruta_id):
    empresa = get_empresa(request)
    ruta = get_object_or_404_scoped(Ruta, empresa, id=ruta_id)
    paradas = ruta.paradas.select_related("cliente", "pedido").all()
    clientes_activos = Cliente.objects.filter(empresa=empresa, activo=True).order_by("nombre")
    pedidos_pendientes = Pedido.objects.filter(empresa=empresa, estado="PENDIENTE").select_related("cliente")
    clientes_json = list(clientes_activos.values("id", "nombre", "comuna", "tipo_cliente"))
    return render(request, "core/detalle_ruta.html", {
        "ruta": ruta, "paradas": paradas, "clientes": clientes_activos,
        "pedidos_pendientes": pedidos_pendientes, "clientes_json": clientes_json,
    })


@user_passes_test(es_admin_o_owner)
def armar_ruta_view(request):
    """
    La ruta del día en una sola pantalla: chofer, fecha y pedidos pendientes
    marcados. Al guardar crea las paradas, optimiza y avisa al chofer.
    """
    empresa = get_empresa(request)
    hoy = timezone.localdate()
    choferes = list(
        Chofer.objects.filter(perfil__empresa=empresa, activo=True).select_related("perfil__user")
        .order_by("perfil__user__first_name")
    )
    pendientes = list(
        Pedido.objects.filter(empresa=empresa, estado="PENDIENTE", cliente__activo=True)
        .select_related("cliente").order_by("cliente__comuna", "cliente__nombre", "creado_en")
    )
    error = None
    elegidos = {p.id for p in pendientes}
    fecha_txt = hoy.isoformat()
    chofer_id = str(choferes[0].id) if len(choferes) == 1 else ""
    nombre = ""

    if request.method == "POST":
        chofer_id = request.POST.get("chofer_id") or ""
        fecha_txt = request.POST.get("fecha") or ""
        nombre = (request.POST.get("nombre") or "").strip()
        elegidos = {int(x) for x in request.POST.getlist("pedidos") if x.isdigit()}
        chofer = next((c for c in choferes if str(c.id) == chofer_id), None)
        try:
            fecha = date.fromisoformat(fecha_txt)
        except ValueError:
            fecha = None

        seleccion = [p for p in pendientes if p.id in elegidos]
        if chofer is None:
            error = "Elige el chofer que hará la ruta."
        elif fecha is None or fecha < hoy:
            error = "Elige una fecha de hoy en adelante."
        elif not seleccion:
            error = "Marca al menos un pedido para la ruta."
        else:
            with transaction.atomic():
                ruta = Ruta.objects.create(
                    empresa=empresa, chofer=chofer, fecha=fecha,
                    nombre=nombre or f"Reparto {fecha.strftime('%d-%m')}",
                )
                clientes_vistos, repetidos = set(), 0
                for orden, pedido in enumerate(seleccion, start=1):
                    if pedido.cliente_id in clientes_vistos:
                        repetidos += 1  # una parada por cliente; el otro pedido sigue pendiente
                        continue
                    clientes_vistos.add(pedido.cliente_id)
                    ParadaRuta.objects.create(ruta=ruta, cliente=pedido.cliente, orden=orden, pedido=pedido)
                    pedido.estado = "ASIGNADO"
                    pedido.save(update_fields=["estado"])

            from .optimizer import optimizar_paradas
            resultado = optimizar_paradas(ruta)
            partes = [f"Ruta creada con {len(clientes_vistos)} paradas."]
            if resultado.get("optimizado"):
                ruta.km_antes = resultado["km_antes"]
                ruta.km_despues = resultado["km_despues"]
                ruta.optimizada_en = timezone.now()
                ruta.save(update_fields=["km_antes", "km_despues", "optimizada_en"])
                if resultado.get("ahorro_km") is not None:
                    partes.append(
                        f"Optimizada: {resultado['km_antes']} km → {resultado['km_despues']} km "
                        f"({resultado['ahorro_pct']}% menos)."
                    )
                else:
                    partes.append("Paradas ordenadas por el camino más corto.")
                if resultado.get("sin_coordenadas"):
                    partes.append(
                        "Sin ubicación en el mapa (quedaron al final): " + ", ".join(resultado["sin_coordenadas"]) + "."
                    )
            else:
                partes.append(resultado.get("motivo", "No se pudo optimizar todavía."))
            if repetidos:
                partes.append(f"{repetidos} pedido(s) del mismo cliente quedaron pendientes para otra ruta.")
            envio = avisar_ruta_asignada(ruta, request)
            partes.append("Avisamos al chofer" + (" en la plataforma y por correo." if envio.get("enviado") else " en la plataforma."))
            messages.success(request, " ".join(partes))
            return redirect("detalle_ruta", ruta_id=ruta.id)

    return render(request, "core/armar_ruta.html", {
        "choferes": choferes, "pendientes": pendientes, "elegidos": elegidos,
        "fecha": fecha_txt, "hoy": hoy, "manana": hoy + timedelta(days=1),
        "chofer_id": chofer_id, "nombre": nombre, "error": error,
        "sin_origen": empresa.latitud_origen is None,
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
        avisar_ruta_actualizada(ruta, f"se agregó {cliente.nombre}.")

    return redirect("detalle_ruta", ruta_id=ruta.id)


@user_passes_test(es_admin_o_owner)
@require_POST
def eliminar_parada_view(request, parada_id):
    empresa = get_empresa(request)
    parada = get_object_or_404_scoped(ParadaRuta, empresa, lookup_field="ruta__empresa", id=parada_id)
    ruta = parada.ruta
    nombre_cliente = parada.cliente.nombre
    pedido = parada.pedido
    parada.delete()

    # El pedido sale de la ruta: vuelve a quedar disponible para asignarlo
    if pedido and pedido.estado == "ASIGNADO":
        pedido.estado = "PENDIENTE"
        pedido.save(update_fields=["estado"])

    avisar_ruta_actualizada(ruta, f"se quitó {nombre_cliente}.")
    return redirect("detalle_ruta", ruta_id=ruta.id)


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
    _sincronizar_pedido_con_parada(parada)
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

            if nuevo_estado == "EN_PROCESO":
                from .notifications import notificar_pedido_en_camino
                resultado = notificar_pedido_en_camino(ruta)
                if resultado["enviado"] and resultado["enviados"] > 0:
                    messages.info(request, f"Se notificó por correo a {resultado['enviados']} cliente(s).")

    return redirect("detalle_ruta", ruta_id=ruta.id)


@user_passes_test(es_admin_o_owner)
@require_POST
def optimizar_ruta_view(request, ruta_id):
    empresa = get_empresa(request)
    ruta = get_object_or_404_scoped(Ruta, empresa, id=ruta_id)

    from .optimizer import optimizar_paradas
    resultado = optimizar_paradas(ruta)

    if resultado.get("optimizado"):
        ruta.km_antes = resultado["km_antes"]
        ruta.km_despues = resultado["km_despues"]
        ruta.optimizada_en = timezone.now()
        ruta.save(update_fields=["km_antes", "km_despues", "optimizada_en"])
        avisar_ruta_actualizada(ruta, "se reordenaron las paradas.")
        fuente = "distancia real de calle" if resultado.get("por_red_vial") else "línea recta (sin conexión a OSRM)"
        mensaje = f"Ruta optimizada: {resultado['cantidad']} paradas reordenadas (usando {fuente})."
        if resultado.get("ahorro_km") is not None:
            mensaje += (
                f" Recorrido estimado: {resultado['km_antes']} km → {resultado['km_despues']} km "
                f"(-{resultado['ahorro_km']} km, {resultado['ahorro_pct']}% menos)."
            )
        if resultado.get("sin_coordenadas"):
            mensaje += (
                f" {len(resultado['sin_coordenadas'])} cliente(s) sin coordenadas "
                "quedaron al final sin optimizar: " + ", ".join(resultado["sin_coordenadas"])
            )
    else:
        mensaje = resultado.get("motivo", "No fue posible optimizar la ruta.")

    messages.info(request, mensaje)

    return redirect("detalle_ruta", ruta_id=ruta.id)


def _sincronizar_pedido_con_parada(parada):
    """
    El pedido asociado a una parada debe reflejar el resultado de la entrega:
    la analitica solo cuenta como despacho los pedidos ENTREGADO, asi que si
    no se sincroniza aqui las entregas reales nunca llegan a los despachos ni
    a la segmentacion de clientes. Si la entrega se revierte o falla, el pedido vuelve
    a ASIGNADO (sigue en la ruta).
    """
    pedido = parada.pedido
    if not pedido or pedido.estado == "CANCELADO":
        return

    nuevo_estado = "ENTREGADO" if parada.estado_entrega == "ENTREGADO" else "ASIGNADO"
    if pedido.estado != nuevo_estado:
        pedido.estado = nuevo_estado
        pedido.save(update_fields=["estado"])


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

                from .notifications import notificar_pedido_en_camino
                notificar_pedido_en_camino(ruta)
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
    # ?fecha=AAAA-MM-DD abre cualquier ruta del chofer (p. ej. desde un aviso);
    # ?dia=manana se mantiene para el boton "Mañana".
    fecha_objetivo = hoy + timedelta(days=1) if request.GET.get("dia") == "manana" else hoy
    try:
        fecha_objetivo = date.fromisoformat(request.GET.get("fecha", "")) or fecha_objetivo
    except ValueError:
        pass
    es_hoy = fecha_objetivo == hoy

    chofer = get_object_or_404(Chofer, perfil__user=request.user)
    empresa = chofer.perfil.empresa

    ruta = Ruta.objects.filter(chofer=chofer, fecha=fecha_objetivo, activa=True).order_by("-creada_en").first()

    paradas = []
    paradas_ui = []
    maps_tramos = []
    navegacion_desde_ubicacion = False
    progreso = {"total": 0, "entregadas": 0, "no_entregadas": 0, "pendientes": 0}
    siguiente_parada_id = None
    porcentaje_entregadas = 0

    origen_fijo = empresa.direccion_origen_completa() if empresa.direccion_origen else None

    if ruta:
        paradas = ruta.paradas.select_related("cliente", "pedido").order_by("orden")

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

        if es_hoy:
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
            if cli.ciudad and cli.ciudad != cli.comuna:
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

        # Navegacion en Google Maps solo con lo que falta: si la ruta no ha
        # empezado sale de la panaderia; si ya hubo entregas, sale de la
        # ubicacion actual del chofer. Siempre termina en la panaderia, y se
        # parte en tramos para no pasar el limite de paradas de Google Maps.
        pendientes = [
            (item["parada"].orden, item["direccion"])
            for item in paradas_ui
            if item["parada"].estado_entrega == "PENDIENTE"
        ]
        navegacion_desde_ubicacion = progreso["entregadas"] + progreso["no_entregadas"] > 0
        maps_tramos = armar_tramos(
            pendientes, origen_empresa=origen_fijo, desde_origen=not navegacion_desde_ubicacion,
        )

    return render(request, "core/chofer_ruta.html", {
        "ruta": ruta,
        "paradas": paradas,
        "paradas_ui": paradas_ui,
        "hoy": hoy,
        "fecha_objetivo": fecha_objetivo,
        "es_hoy": es_hoy,
        "es_manana": fecha_objetivo == hoy + timedelta(days=1),
        "etiqueta_dia": "de hoy" if es_hoy else (
            "de mañana" if fecha_objetivo == hoy + timedelta(days=1)
            else "del " + fecha_legible(fecha_objetivo).removeprefix("el ")
        ),
        "maps_tramos": maps_tramos,
        "navegacion_desde_ubicacion": navegacion_desde_ubicacion,
        "max_waypoints_maps": MAX_WAYPOINTS,
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

    if parada.ruta.fecha != timezone.localdate():
        messages.warning(request, "Solo puedes marcar entregas de la ruta de hoy.")
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
        foto = request.FILES.get("foto_entrega")
        if foto:
            parada.foto_entrega = foto

    elif accion == "NO_ENTREGADO":
        # motivo obligatorio para NO_ENTREGADO
        if not motivo:
            return redirect("chofer_ruta_hoy")

        parada.estado_entrega = "NO_ENTREGADO"
        parada.entregado = False  # compatibilidad
        parada.hora_entrega = timezone.now()
        parada.motivo_no_entrega = motivo
        parada.comentario_chofer = comentario_chofer if comentario_chofer else None
        parada.foto_entrega = None

    elif accion == "REVERTIR":
        parada.estado_entrega = "PENDIENTE"
        parada.entregado = False  # compatibilidad
        parada.hora_entrega = None
        parada.motivo_no_entrega = None
        parada.comentario_chofer = None
        parada.foto_entrega = None

    parada.save()
    _sincronizar_pedido_con_parada(parada)

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
# NUEVO PEDIDO (OWNER + ADMIN): cliente + que se despacha
# =========================================================
# LogiVisir solo optimiza el reparto, asi que un pedido no lleva productos con
# precio ni montos: basta con saber a quien hay que ir y que se le lleva.
NOTA_PEDIDO_MAX = 500


@user_passes_test(es_admin_o_owner)
def crear_pedido_view(request):
    empresa = get_empresa(request)
    clientes = Cliente.objects.filter(empresa=empresa, activo=True).order_by("nombre")
    error = None
    nota = ""
    cliente_inicial = clientes.filter(id=request.GET.get("cliente")).first() if request.GET.get("cliente", "").isdigit() else None

    if request.method == "POST":
        nota = (request.POST.get("nota") or "").strip()
        cliente_id = request.POST.get("cliente_id")
        cliente = Cliente.objects.filter(empresa=empresa, activo=True, id=cliente_id).first() if cliente_id else None

        if cliente is None:
            error = "Elige un cliente de la lista."
        elif len(nota) > NOTA_PEDIDO_MAX:
            error = f"La descripción no puede superar {NOTA_PEDIDO_MAX} caracteres."
        else:
            pedido = Pedido.objects.create(
                empresa=empresa, cliente=cliente, nota=nota, creado_por=request.user,
            )
            messages.success(request, f"Pedido #{pedido.id} creado para {cliente.nombre}.")
            return redirect("detalle_pedido", pedido_id=pedido.id)

    return render(request, "core/crear_pedido.html", {
        "clientes_json": list(clientes.values("id", "nombre", "comuna", "tipo_cliente")),
        "error": error,
        "nota": nota,
        "nota_max": NOTA_PEDIDO_MAX,
        "cliente_inicial": cliente_inicial,
    })

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
    paradas = pedido.paradas_pedido.select_related("ruta").order_by("-ruta__fecha")
    return render(request, "core/detalle_pedido.html", {
        "pedido": pedido, "paradas": paradas, "motivo_max": MOTIVO_CANCELACION_MAX,
    })


MOTIVO_CANCELACION_MAX = 200


def _rutas_pendientes_del_pedido(pedido):
    """Rutas donde el pedido todavia espera ser entregado."""
    return Ruta.objects.filter(
        paradas__pedido=pedido, paradas__estado_entrega="PENDIENTE",
    ).distinct()


@user_passes_test(es_admin_o_owner)
def editar_pedido_view(request, pedido_id):
    """
    CU-03: corregir un pedido antes de entregarlo. Mientras esta PENDIENTE se
    puede cambiar el cliente y lo que se lleva; ya ASIGNADO a una ruta solo lo
    que se lleva (cambiar el cliente moveria la parada a otra direccion), y
    el chofer recibe un aviso.
    """
    empresa = get_empresa(request)
    pedido = get_object_or_404_scoped(Pedido, empresa, id=pedido_id)
    if not pedido.editable:
        messages.warning(request, f"El pedido está {pedido.get_estado_display().lower()}: ya no se puede modificar.")
        return redirect("detalle_pedido", pedido_id=pedido.id)

    puede_cambiar_cliente = pedido.estado == "PENDIENTE"
    error = None
    nota = pedido.nota

    if request.method == "POST":
        nota = (request.POST.get("nota") or "").strip()
        cliente = pedido.cliente
        if puede_cambiar_cliente:
            cliente_id = request.POST.get("cliente_id")
            cliente = Cliente.objects.filter(empresa=empresa, activo=True, id=cliente_id).first() if cliente_id else None

        if cliente is None:
            error = "Elige un cliente de la lista."
        elif len(nota) > NOTA_PEDIDO_MAX:
            error = f"La descripción no puede superar {NOTA_PEDIDO_MAX} caracteres."
        else:
            cambio_nota = nota != pedido.nota
            pedido.cliente = cliente
            pedido.nota = nota
            pedido.save(update_fields=["cliente", "nota"])
            if cambio_nota:
                for ruta in _rutas_pendientes_del_pedido(pedido):
                    avisar_ruta_actualizada(ruta, f"cambió lo que se lleva a {cliente.nombre}.")
            messages.success(request, f"Pedido #{pedido.id} actualizado.")
            return redirect("detalle_pedido", pedido_id=pedido.id)

    clientes = Cliente.objects.filter(empresa=empresa, activo=True).order_by("nombre")
    return render(request, "core/editar_pedido.html", {
        "pedido": pedido,
        "puede_cambiar_cliente": puede_cambiar_cliente,
        "clientes_json": list(clientes.values("id", "nombre", "comuna", "tipo_cliente")),
        "error": error,
        "nota": nota,
        "nota_max": NOTA_PEDIDO_MAX,
    })


@user_passes_test(es_admin_o_owner)
@require_POST
def cancelar_pedido_view(request, pedido_id):
    """
    CU-03: cancelar un pedido que aun no se entrega. Si estaba en una ruta,
    su parada pendiente sale de ella y el chofer recibe un aviso. Las
    paradas ya marcadas como no entregadas se conservan como historial.
    """
    empresa = get_empresa(request)
    pedido = get_object_or_404_scoped(Pedido, empresa, id=pedido_id)
    if not pedido.editable:
        messages.warning(request, f"El pedido está {pedido.get_estado_display().lower()}: no se puede cancelar.")
        return redirect("detalle_pedido", pedido_id=pedido.id)

    motivo = (request.POST.get("motivo") or "").strip()[:MOTIVO_CANCELACION_MAX]
    rutas = list(_rutas_pendientes_del_pedido(pedido))
    pedido.paradas_pedido.filter(estado_entrega="PENDIENTE").delete()

    pedido.estado = "CANCELADO"
    pedido.cancelado_en = timezone.now()
    pedido.cancelado_por = request.user
    pedido.motivo_cancelacion = motivo
    pedido.save(update_fields=["estado", "cancelado_en", "cancelado_por", "motivo_cancelacion"])

    for ruta in rutas:
        avisar_ruta_actualizada(ruta, f"se canceló el pedido de {pedido.cliente.nombre}: ya no hay que ir.")

    texto = f"Pedido #{pedido.id} cancelado."
    if rutas:
        texto += " Se quitó de " + ", ".join(r.nombre for r in rutas) + " y se avisó al chofer."
    messages.success(request, texto)
    return redirect("detalle_pedido", pedido_id=pedido.id)


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
    avisar_ruta_actualizada(ruta, f"se agregó el pedido de {pedido.cliente.nombre}.")

    return redirect("detalle_ruta", ruta_id=ruta.id)


# =========================================================
# ANALITICA DE DESPACHOS / SEGMENTACION RF (OWNER + ADMIN)
# =========================================================
def _csv_response(filename):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    # BOM: sin esto Excel/Power BI en Windows no detectan UTF-8 y los
    # nombres/comunas con tilde o "ñ" salen corruptos.
    response.write("﻿")
    return response


@user_passes_test(es_admin_o_owner)
def analitica_view(request):
    empresa = get_empresa(request)

    resumen = analytics.resumen_despachos(empresa)
    mensuales = analytics.despachos_por_mes(empresa, meses=12)
    por_comuna = analytics.despachos_por_comuna(empresa)
    top = analytics.top_clientes(empresa, limite=10)
    segmentacion = analytics.segmentar_clientes(empresa)

    # claves sin espacios porque las plantillas Django no pueden acceder a
    # `dict.En riesgo` (el lookup por punto no soporta espacios en el nombre)
    conteo_segmentos = {s.replace(" ", "_"): 0 for s in analytics.SEGMENTOS_ORDEN}
    segmento_por_cliente = {}
    for c in segmentacion["clientes"]:
        segmento_por_cliente[c["cliente_id"]] = c["segmento"]
        if c["segmento"]:
            conteo_segmentos[c["segmento"].replace(" ", "_")] += 1

    for c in top:
        c["segmento"] = segmento_por_cliente.get(c["cliente_id"])

    max_mes = max((f["despachos"] for f in mensuales), default=0)
    max_comuna = max((f["despachos"] for f in por_comuna), default=0)

    return render(request, "core/analitica.html", {
        "resumen": resumen,
        "despachos_mensuales": mensuales,
        "despachos_comuna": por_comuna,
        "max_mes": max_mes,
        "max_comuna": max_comuna,
        "top_clientes": top,
        "segmentacion": segmentacion,
        "conteo_segmentos": conteo_segmentos,
        "rf_min_clientes": analytics.RF_MIN_CLIENTES,
    })


@user_passes_test(es_admin_o_owner)
def exportar_segmentacion_csv_view(request):
    empresa = get_empresa(request)
    segmentacion = analytics.segmentar_clientes(empresa)

    fecha = timezone.localdate().isoformat()
    response = _csv_response(f"segmentacion_clientes_empresa{empresa.id}_{fecha}.csv")

    writer = csv.writer(response)
    writer.writerow(["cliente_id", "nombre", "comuna", "recencia_dias",
                     "frecuencia_despachos", "cluster_id", "segmento"])
    for c in segmentacion["clientes"]:
        writer.writerow([
            c["cliente_id"], c["nombre"], c["comuna"], c["recencia_dias"],
            c["frecuencia"],
            c["cluster_id"] if c["cluster_id"] is not None else "",
            c["segmento"] or "Sin segmentar",
        ])
    return response


@user_passes_test(es_admin_o_owner)
def exportar_despachos_mensuales_csv_view(request):
    empresa = get_empresa(request)
    filas = analytics.despachos_por_mes(empresa, meses=24)

    fecha = timezone.localdate().isoformat()
    response = _csv_response(f"despachos_mensuales_empresa{empresa.id}_{fecha}.csv")

    writer = csv.writer(response)
    writer.writerow(["mes", "despachos", "clientes_atendidos"])
    for f in filas:
        writer.writerow([f["mes"].strftime("%Y-%m"), f["despachos"], f["clientes"]])
    return response


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
def staff_comprobante_view(request, solicitud_id):
    solicitud = get_object_or_404(SolicitudCuenta, id=solicitud_id)
    if not solicitud.comprobante:
        raise Http404
    nombre = f"comprobante_{solicitud.codigo_referencia}{os.path.splitext(solicitud.comprobante.name)[1]}"
    return FileResponse(solicitud.comprobante.open("rb"), filename=nombre)


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
    rut = solicitud.rut_empresa or None
    if rut and Empresa.objects.filter(rut_empresa=rut).exists():
        rut = None  # el RUT ya lo usa otra empresa; el equipo lo revisa en la ficha
    empresa = Empresa.objects.create(
        nombre=solicitud.nombre_empresa, owner=usuario, plan=solicitud.plan_solicitado,
        rut_empresa=rut,
        # Dirección de salida propuesta: el dueño la confirma en el mapa (menú Empresa).
        direccion_origen=solicitud.direccion or None,
        comuna_origen=solicitud.comuna or None,
        ciudad_origen=solicitud.ciudad or None,
    )
    # El pago ya fue validado: queda registrado y define el primer mes de servicio.
    membresias.registrar_pago(
        empresa, plan=solicitud.plan_solicitado,
        monto=membresias.PRECIOS_PLAN[solicitud.plan_solicitado],
        fecha_pago=timezone.localdate(), meses=1, medio="TRANSFERENCIA",
        referencia=solicitud.codigo_referencia, notas="Pago de la solicitud de cuenta",
        usuario=request.user,
    )
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


# =========================================================
# STAFF LOGIVISIR: empresas clientes (ficha y acceso)
# =========================================================
# El equipo LogiVisir administra a quien contrata el servicio, no el negocio
# de cada empresa: estas vistas muestran plan, contacto, estado y usuarios,
# y NUNCA consultan Cliente, Ruta, Pedido ni Chofer de la empresa. Es un
# limite de privacidad (Ley 19.628/21.719): los datos de los clientes finales
# pertenecen a la empresa, no a LogiVisir.
ROLES_CREABLES_STAFF = ("OWNER", "ADMIN")
DIAS_AVISO_VENCIMIENTO = 15


ORDEN_ROLES = {"OWNER": 0, "ADMIN": 1, "CHOFER": 2}


def _ordenar_por_rol(perfiles):
    """Activos primero; luego dueño, administradores y choferes; por fecha de creación."""
    return sorted(perfiles, key=lambda p: (not p.user.is_active, ORDEN_ROLES.get(p.rol, 9), p.user.date_joined))


def _plan_de_empresa(empresa):
    return empresa.get_plan_display() if empresa.plan else "Sin plan registrado"


def _estado_membresia(empresa, hoy=None):
    """Vigente, por vencer (15 días o menos), vencida o sin fecha registrada."""
    if not empresa.suscripcion_vence:
        return "sin_fecha"
    dias = (empresa.suscripcion_vence - (hoy or timezone.localdate())).days
    if dias < 0:
        return "vencida"
    if dias <= DIAS_AVISO_VENCIMIENTO:
        return "por_vencer"
    return "vigente"


@user_passes_test(es_staff_logivisir)
def staff_lista_empresas_view(request):
    empresas = Empresa.objects.select_related("owner").annotate(
        num_usuarios=Count("perfiles", distinct=True),
    ).order_by("nombre")

    estado = request.GET.get("estado")
    if estado == "activas":
        empresas = empresas.filter(activa=True)
    elif estado == "suspendidas":
        empresas = empresas.filter(activa=False)

    filas = [
        {"empresa": e, "plan": _plan_de_empresa(e), "num_usuarios": e.num_usuarios,
         "membresia": _estado_membresia(e)}
        for e in empresas
    ]
    return render(request, "core/staff_lista_empresas.html", {
        "filas": filas, "estado_filtro": estado,
    })


@user_passes_test(es_staff_logivisir)
def staff_detalle_empresa_view(request, empresa_id):
    empresa = get_object_or_404(Empresa.objects.select_related("owner"), id=empresa_id)
    usuarios = _ordenar_por_rol(PerfilUsuario.objects.filter(empresa=empresa).select_related("user"))
    return render(request, "core/staff_detalle_empresa.html", {
        "empresa": empresa,
        "plan": _plan_de_empresa(empresa),
        "solicitud": empresa.solicitud_origen.first(),
        "usuarios": usuarios,
        "roles_creables": [r for r in PerfilUsuario.ROL_CHOICES if r[0] in ROLES_CREABLES_STAFF],
        "membresia": _estado_membresia(empresa),
        "planes": Empresa.PLAN_CHOICES,
        "dueno_es_staff": empresa.owner.is_staff,
        "pagos": empresa.pagos.select_related("registrado_por", "anulado_por"),
        "medios": Pago.MEDIO_CHOICES,
        "meses_permitidos": membresias.MESES_PERMITIDOS,
        "precios": membresias.PRECIOS_PLAN,
        "hoy": timezone.localdate(),
    })


@user_passes_test(es_staff_logivisir)
@require_POST
def staff_registrar_pago_view(request, empresa_id):
    empresa = get_object_or_404(Empresa, id=empresa_id)
    volver = redirect("staff_detalle_empresa", empresa_id=empresa.id)
    plan = request.POST.get("plan")
    medio = request.POST.get("medio")
    try:
        meses = int(request.POST.get("meses") or 1)
        monto = int((request.POST.get("monto") or "").replace(".", "").strip())
        fecha_pago = date.fromisoformat(request.POST.get("fecha_pago") or "")
    except ValueError:
        messages.error(request, "Revisa el monto y la fecha del pago.")
        return volver
    if (plan not in membresias.PRECIOS_PLAN or medio not in dict(Pago.MEDIO_CHOICES)
            or meses not in membresias.MESES_PERMITIDOS or monto <= 0):
        messages.error(request, "Completa plan, meses, monto y medio de pago.")
        return volver
    if fecha_pago > timezone.localdate():
        messages.error(request, "La fecha del pago no puede ser futura.")
        return volver
    pago = membresias.registrar_pago(
        empresa, plan=plan, monto=monto, fecha_pago=fecha_pago, meses=meses, medio=medio,
        referencia=(request.POST.get("referencia") or "").strip()[:100],
        notas=(request.POST.get("notas") or "").strip()[:255],
        usuario=request.user, reactivar=request.POST.get("reactivar") == "1",
    )
    messages.success(
        request,
        f"Pago registrado: membresía {pago.get_plan_display()} hasta el {pago.periodo_hasta.strftime('%d-%m-%Y')}.",
    )
    return volver


@user_passes_test(es_staff_logivisir)
@require_POST
def staff_anular_pago_view(request, pago_id):
    pago = get_object_or_404(Pago.objects.select_related("empresa"), id=pago_id)
    motivo = (request.POST.get("motivo") or "").strip()
    if not motivo:
        messages.error(request, "Indica el motivo de la anulación.")
    elif membresias.anular_pago(pago, usuario=request.user, motivo=motivo[:200]):
        messages.warning(request, "Pago anulado. Queda en el historial con su motivo.")
    return redirect("staff_detalle_empresa", empresa_id=pago.empresa_id)


@user_passes_test(es_staff_logivisir)
def staff_pagos_view(request):
    pagos = Pago.objects.select_related("empresa", "registrado_por")
    empresa_id = request.GET.get("empresa") or ""
    mes = request.GET.get("mes") or ""  # formato AAAA-MM
    if empresa_id.isdigit():
        pagos = pagos.filter(empresa_id=empresa_id)
    else:
        empresa_id = ""
    if mes:
        try:
            desde = date.fromisoformat(f"{mes}-01")
            pagos = pagos.filter(fecha_pago__gte=desde, fecha_pago__lt=membresias.sumar_meses(desde, 1))
        except ValueError:
            mes = ""
    if request.GET.get("formato") == "csv":
        response = _csv_response("pagos_logivisir.csv")
        writer = csv.writer(response)
        writer.writerow(["Fecha de pago", "Empresa", "Plan", "Meses", "Período desde", "Período hasta",
                         "Monto (CLP)", "Medio", "Referencia", "Estado", "Registrado por"])
        for p in pagos:
            writer.writerow([p.fecha_pago.isoformat(), p.empresa.nombre, p.get_plan_display(), p.meses,
                             p.periodo_desde.isoformat(), p.periodo_hasta.isoformat(), p.monto,
                             p.get_medio_display(), p.referencia, "Anulado" if p.anulado else "Válido",
                             p.registrado_por.username if p.registrado_por else ""])
        return response
    validos = [p for p in pagos if not p.anulado]
    return render(request, "core/staff_pagos.html", {
        "pagos": pagos,
        "total": sum(p.monto for p in validos),
        "cantidad_validos": len(validos),
        "empresas": Empresa.objects.order_by("nombre"),
        "empresa_filtro": empresa_id,
        "mes_filtro": mes,
        "query": urlencode({k: v for k, v in (("empresa", empresa_id), ("mes", mes)) if v}),
    })


@user_passes_test(es_staff_logivisir)
@require_POST
def staff_membresia_empresa_view(request, empresa_id):
    empresa = get_object_or_404(Empresa, id=empresa_id)
    plan = request.POST.get("plan") or None
    vence_txt = (request.POST.get("suscripcion_vence") or "").strip()
    if plan and plan not in dict(Empresa.PLAN_CHOICES):
        messages.error(request, "Plan no válido.")
        return redirect("staff_detalle_empresa", empresa_id=empresa.id)
    try:
        vence = date.fromisoformat(vence_txt) if vence_txt else None
    except ValueError:
        messages.error(request, "La fecha de vencimiento no es válida.")
        return redirect("staff_detalle_empresa", empresa_id=empresa.id)
    empresa.plan = plan
    empresa.suscripcion_vence = vence
    empresa.save(update_fields=["plan", "suscripcion_vence"])
    messages.success(request, f"Membresía de {empresa.nombre} actualizada.")
    return redirect("staff_detalle_empresa", empresa_id=empresa.id)


# ---------------------------------------------------------
# Panel del equipo LogiVisir: datos del negocio SaaS
# ---------------------------------------------------------
# Solo cifras agregadas de uso del servicio (cantidad de rutas, km ahorrados,
# ingresos a la plataforma). Nunca se listan clientes, pedidos, rutas ni
# choferes de una empresa.
DIAS_USO = 30


def _km_ahorrados(rutas):
    total = 0.0
    for antes, despues in rutas.exclude(km_antes=None).exclude(km_despues=None).values_list("km_antes", "km_despues"):
        total += max(antes - despues, 0.0)
    return round(total, 1)


@user_passes_test(es_staff_logivisir)
def staff_panel_view(request):
    hoy = timezone.localdate()
    desde = timezone.now() - timedelta(days=DIAS_USO)
    empresas = list(Empresa.objects.select_related("owner").order_by("nombre"))

    filas = []
    conteo_membresia = {"vigente": 0, "por_vencer": 0, "vencida": 0, "sin_fecha": 0}
    conteo_plan = {etiqueta: 0 for _, etiqueta in Empresa.PLAN_CHOICES}
    conteo_plan["Sin plan registrado"] = 0
    ubicaciones = {}
    for e in empresas:
        rutas = Ruta.objects.filter(empresa=e)
        usuarios = User.objects.filter(perfilusuario__empresa=e)
        estado = _estado_membresia(e, hoy)
        conteo_membresia[estado] += 1
        conteo_plan[_plan_de_empresa(e)] += 1
        lugar = e.ciudad_origen or e.comuna_origen
        lugar = f"{e.comuna_origen}, {e.ciudad_origen}" if e.comuna_origen and e.ciudad_origen else (lugar or "Sin dirección registrada")
        ubicaciones[lugar] = ubicaciones.get(lugar, 0) + 1
        ultimo = usuarios.exclude(last_login=None).order_by("-last_login").values_list("last_login", flat=True).first()
        filas.append({
            "empresa": e,
            "plan": _plan_de_empresa(e),
            "membresia": estado,
            "lugar": lugar,
            "usuarios": usuarios.count(),
            "usuarios_activos_mes": usuarios.filter(last_login__gte=desde).count(),
            "ultimo_ingreso": ultimo,
            "rutas_mes": rutas.filter(creada_en__gte=desde).count(),
            "optimizaciones_mes": rutas.filter(optimizada_en__gte=desde).count(),
            "km_ahorrados": _km_ahorrados(rutas),
            "km_ahorrados_mes": _km_ahorrados(rutas.filter(optimizada_en__gte=desde)),
        })

    resumen = {
        "empresas": len(empresas),
        "activas": sum(1 for e in empresas if e.activa),
        "suspendidas": sum(1 for e in empresas if not e.activa),
        "solicitudes_nuevas": SolicitudCuenta.objects.filter(estado__in=("NUEVA", "PAGO_VALIDADO")).count(),
        "usuarios_activos_mes": sum(f["usuarios_activos_mes"] for f in filas),
        "rutas_mes": sum(f["rutas_mes"] for f in filas),
        "optimizaciones_mes": sum(f["optimizaciones_mes"] for f in filas),
        "km_ahorrados": round(sum(f["km_ahorrados"] for f in filas), 1),
        "km_ahorrados_mes": round(sum(f["km_ahorrados_mes"] for f in filas), 1),
    }
    inicio_mes = hoy.replace(day=1)
    ingresos = {
        "mrr": membresias.mrr(empresas, hoy),
        "mes_actual": membresias.ingresos_entre(inicio_mes, hoy),
        "morosas": conteo_membresia["vencida"],
        "ultimos_pagos": Pago.objects.filter(anulado=False).select_related("empresa")[:5],
    }
    por_mes = membresias.ingresos_por_mes(6, hoy)
    maximo = max([t for _, t in por_mes] + [1])
    ingresos["por_mes"] = [(m, t, round(t * 100 / maximo)) for m, t in por_mes]
    por_vencer = sorted(
        [f for f in filas if f["membresia"] in ("por_vencer", "vencida")],
        key=lambda f: f["empresa"].suscripcion_vence,
    )
    return render(request, "core/staff_panel.html", {
        "resumen": resumen,
        "filas": sorted(filas, key=lambda f: -f["km_ahorrados"]),
        "conteo_membresia": conteo_membresia,
        "conteo_plan": conteo_plan,
        "ubicaciones": sorted(ubicaciones.items(), key=lambda x: -x[1]),
        "por_vencer": por_vencer,
        "dias_uso": DIAS_USO,
        "dias_aviso": DIAS_AVISO_VENCIMIENTO,
        "ingresos": ingresos,
    })


@user_passes_test(es_staff_logivisir)
def staff_usuarios_view(request):
    """
    Usuarios de las empresas clientes, solo a pedido: primero se elige la
    empresa. Sin empresa elegida se muestran solo totales por rol.
    """
    empresas = Empresa.objects.order_by("nombre")
    resumen = []
    for e in empresas:
        perfiles = PerfilUsuario.objects.filter(empresa=e)
        resumen.append({
            "empresa": e,
            "duenos": perfiles.filter(rol="OWNER").count(),
            "admins": perfiles.filter(rol="ADMIN").count(),
            "choferes": perfiles.filter(rol="CHOFER").count(),
            "activos": perfiles.filter(user__is_active=True).count(),
            "inactivos": perfiles.filter(user__is_active=False).count(),
        })

    empresa = None
    perfiles = []
    empresa_id = request.GET.get("empresa")
    if empresa_id:
        empresa = get_object_or_404(Empresa, id=empresa_id)
        perfiles = PerfilUsuario.objects.filter(empresa=empresa).select_related("user")
        rol = request.GET.get("rol")
        if rol in dict(PerfilUsuario.ROL_CHOICES):
            perfiles = perfiles.filter(rol=rol)
        perfiles = _ordenar_por_rol(perfiles)
    return render(request, "core/staff_usuarios.html", {
        "empresas": empresas,
        "resumen": resumen,
        "empresa": empresa,
        "perfiles": perfiles,
        "rol_filtro": request.GET.get("rol") or "",
        "roles": PerfilUsuario.ROL_CHOICES,
    })


@user_passes_test(es_staff_logivisir)
@require_POST
def staff_cambiar_estado_empresa_view(request, empresa_id):
    empresa = get_object_or_404(Empresa, id=empresa_id)
    empresa.activa = not empresa.activa
    empresa.save(update_fields=["activa"])
    if empresa.activa:
        messages.success(request, f"{empresa.nombre} fue reactivada: sus usuarios ya pueden ingresar.")
    else:
        messages.warning(request, f"{empresa.nombre} fue suspendida: sus usuarios no podrán ingresar.")
    return redirect("staff_detalle_empresa", empresa_id=empresa.id)


@user_passes_test(es_staff_logivisir)
@require_POST
def staff_crear_usuario_empresa_view(request, empresa_id):
    empresa = get_object_or_404(Empresa, id=empresa_id)
    rol = request.POST.get("rol")
    nombre = (request.POST.get("nombre") or "").strip()
    email = (request.POST.get("email") or "").strip()

    if rol not in ROLES_CREABLES_STAFF or not nombre or not email:
        messages.error(request, "Completa nombre, correo y rol (Dueño o Administrador).")
        return redirect("staff_detalle_empresa", empresa_id=empresa.id)
    error_email = validar_email_nuevo_usuario(email)
    if error_email:
        messages.error(request, error_email)
        return redirect("staff_detalle_empresa", empresa_id=empresa.id)

    username = _generar_username(empresa.nombre)
    temp_password = get_random_string(14, allowed_chars=TEMP_PASSWORD_CHARS)
    usuario = User.objects.create_user(
        username=username, password=temp_password, email=email, first_name=nombre,
    )
    PerfilUsuario.objects.create(
        user=usuario, empresa=empresa, rol=rol, debe_cambiar_password=True,
    )
    if rol == "OWNER" and empresa.owner.is_staff:
        # La empresa pasa a tener un dueño propio en vez de una cuenta del equipo.
        empresa.owner = usuario
        empresa.save(update_fields=["owner"])
    _enviar_credenciales(request, usuario, empresa, temp_password)

    messages.success(
        request,
        f"Usuario {username} creado. Clave temporal (se pide cambiarla al primer ingreso): {temp_password}",
    )
    return redirect("staff_detalle_empresa", empresa_id=empresa.id)


@user_passes_test(es_staff_logivisir)
@require_POST
def staff_restablecer_clave_view(request, user_id):
    # Solo usuarios de empresas clientes: nunca otro miembro del staff.
    perfil = get_object_or_404(PerfilUsuario.objects.select_related("user", "empresa"), user_id=user_id)
    usuario = perfil.user

    temp_password = get_random_string(14, allowed_chars=TEMP_PASSWORD_CHARS)
    usuario.set_password(temp_password)
    usuario.save()
    perfil.debe_cambiar_password = True
    perfil.save(update_fields=["debe_cambiar_password"])
    _enviar_credenciales(request, usuario, perfil.empresa, temp_password)

    messages.success(
        request,
        f"Clave de {usuario.username} restablecida. Clave temporal: {temp_password}",
    )
    return redirect("staff_detalle_empresa", empresa_id=perfil.empresa_id)


def _enviar_credenciales(request, usuario, empresa, temp_password):
    if not usuario.email:
        return
    login_url = request.build_absolute_uri(reverse("login"))
    send_mail(
        subject="Tu acceso a LogiVisir Solutions",
        message=(
            f"Hola {usuario.first_name or usuario.username},\n\n"
            f"Tienes acceso a LogiVisir para {empresa.nombre}.\n\n"
            f"Ingresa en: {login_url}\n"
            f"Usuario: {usuario.username}\n"
            f"Contraseña temporal: {temp_password}\n\n"
            "Por seguridad, te pediremos cambiarla en tu primer inicio de sesión.\n\n"
            "Equipo LogiVisir Solutions"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[usuario.email],
        fail_silently=True,
    )


# =========================================================
# NOTIFICACIONES (campana del menu, todos los roles)
# =========================================================
@login_required
def lista_notificaciones_view(request):
    notificaciones = request.user.notificaciones.all()[:50]
    return render(request, "core/notificaciones.html", {"notificaciones": notificaciones})


@login_required
def abrir_notificacion_view(request, notificacion_id):
    # Solo las del propio usuario: get_object_or_404 con usuario=request.user
    notificacion = get_object_or_404(Notificacion, id=notificacion_id, usuario=request.user)
    if not notificacion.leida:
        notificacion.leida = True
        notificacion.save(update_fields=["leida"])
    destino = notificacion.url
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        return redirect(destino)
    return redirect("lista_notificaciones")


@login_required
@require_POST
def marcar_notificaciones_leidas_view(request):
    request.user.notificaciones.filter(leida=False).update(leida=True)
    return redirect(request.POST.get("volver") if url_has_allowed_host_and_scheme(
        request.POST.get("volver"), allowed_hosts={request.get_host()},
    ) else "lista_notificaciones")


# =========================================================
# CHOFER: todas mis rutas (proximas y recientes)
# =========================================================
@user_passes_test(es_chofer)
def chofer_mis_rutas_view(request):
    chofer = get_object_or_404(Chofer, perfil__user=request.user)
    hoy = timezone.localdate()
    rutas = Ruta.objects.filter(chofer=chofer, activa=True).annotate(
        num_paradas=Count("paradas"),
    )
    return render(request, "core/chofer_mis_rutas.html", {
        "proximas": rutas.filter(fecha__gte=hoy).order_by("fecha", "creada_en"),
        "recientes": rutas.filter(fecha__lt=hoy, fecha__gte=hoy - timedelta(days=14)).order_by("-fecha"),
        "hoy": hoy,
    })



# =========================================================
# MI CUENTA: cambiar contraseña y recuperación con aviso por correo
# =========================================================
class CambiarPasswordView(auth_views.PasswordChangeView):
    """Cambio voluntario de contraseña, para cualquier usuario con sesión."""
    template_name = "core/cambiar_password.html"

    def form_valid(self, form):
        respuesta = super().form_valid(form)  # tambien mantiene la sesion abierta
        perfil = getattr(self.request.user, "perfilusuario", None)
        if perfil and perfil.debe_cambiar_password:
            perfil.debe_cambiar_password = False
            perfil.save(update_fields=["debe_cambiar_password"])
        avisar_cambio_password(self.request.user, self.request)
        messages.success(self.request, "Contraseña actualizada. Te enviamos un correo de confirmación.")
        return respuesta

    def get_success_url(self):
        perfil = getattr(self.request.user, "perfilusuario", None)
        if perfil and perfil.rol == "CHOFER":
            return reverse("chofer_ruta_hoy")
        if perfil is None and self.request.user.is_staff:
            return reverse("staff_lista_empresas")
        return reverse("dashboard")


class RestablecerPasswordConfirmView(auth_views.PasswordResetConfirmView):
    """
    Paso final de "¿Olvidaste tu contraseña?": ademas de guardar la clave
    nueva, avisa por correo y deja de exigir el cambio obligatorio (la
    persona ya eligio su propia contraseña).
    """
    template_name = "core/password_reset_confirm.html"

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        usuario = form.user
        PerfilUsuario.objects.filter(user=usuario, debe_cambiar_password=True).update(debe_cambiar_password=False)
        avisar_cambio_password(usuario, self.request)
        return respuesta


# =========================================================
# CONFIGURACION DE LA EMPRESA: direccion de salida de las rutas
# =========================================================
# Sin esta direccion (y sus coordenadas) no se puede optimizar ninguna ruta,
# y el chofer no tiene punto de partida ni de regreso en Google Maps.
LIMITES_CHILE = {"lat": (-56.0, -17.0), "lon": (-110.0, -66.0)}  # incluye Isla de Pascua


def _leer_coordenadas(texto):
    """
    "-33.4942, -70.6445" (como las copia Google Maps) -> (lat, lon), o None
    si viene vacio. Lanza ValueError si el formato o el rango no sirven.
    """
    texto = (texto or "").strip()
    if not texto:
        return None
    partes = [p.strip() for p in texto.replace(";", ",").split(",")]
    try:
        if len(partes) != 2:
            raise ValueError
        lat, lon = float(partes[0]), float(partes[1])
    except ValueError:
        raise ValueError("Escribe las coordenadas como latitud, longitud (ej: -33.4942, -70.6445).")
    if not (LIMITES_CHILE["lat"][0] <= lat <= LIMITES_CHILE["lat"][1]
            and LIMITES_CHILE["lon"][0] <= lon <= LIMITES_CHILE["lon"][1]):
        raise ValueError("Esas coordenadas no están en Chile. Revisa que la latitud vaya primero.")
    return lat, lon


@user_passes_test(es_admin_o_owner)
def configurar_empresa_view(request):
    empresa = get_empresa(request)
    error = None

    if request.method == "POST":
        direccion = (request.POST.get("direccion_origen") or "").strip()
        comuna = (request.POST.get("comuna_origen") or "").strip()
        ciudad = (request.POST.get("ciudad_origen") or "").strip() or "Santiago"

        try:
            coordenadas_manuales = _leer_coordenadas(request.POST.get("coordenadas"))
        except ValueError as e:
            coordenadas_manuales = None
            error = str(e)

        if not error and not (direccion and comuna):
            error = "La dirección y la comuna son obligatorias."

        if not error:
            cambio_direccion = (
                direccion != (empresa.direccion_origen or "")
                or comuna != (empresa.comuna_origen or "")
                or ciudad != (empresa.ciudad_origen or "")
            )
            empresa.direccion_origen = direccion
            empresa.comuna_origen = comuna
            empresa.ciudad_origen = ciudad

            if coordenadas_manuales:
                empresa.latitud_origen, empresa.longitud_origen = coordenadas_manuales
                messages.success(request, "Dirección de salida guardada con las coordenadas que indicaste.")
            elif cambio_direccion or empresa.latitud_origen is None:
                resultado = geocodificar_direccion(direccion, comuna, ciudad)
                if resultado:
                    empresa.latitud_origen, empresa.longitud_origen = resultado
                    messages.success(
                        request,
                        "Dirección de salida guardada y ubicada en el mapa. Revisa que el punto sea el correcto.",
                    )
                else:
                    empresa.latitud_origen = empresa.longitud_origen = None
                    messages.warning(
                        request,
                        "Guardamos la dirección, pero no pudimos ubicarla en el mapa. Revisa que esté bien "
                        "escrita o pega las coordenadas desde Google Maps.",
                    )
            else:
                messages.success(request, "Datos guardados.")

            empresa.save(update_fields=[
                "direccion_origen", "comuna_origen", "ciudad_origen", "latitud_origen", "longitud_origen",
            ])
            return redirect("configurar_empresa")

    return render(request, "core/configurar_empresa.html", {
        "empresa": empresa,
        "error": error,
        "datos": request.POST if request.method == "POST" else None,
        "mapa": _urls_mapa(empresa.latitud_origen, empresa.longitud_origen),
    })


def _urls_mapa(lat, lon):
    """
    Enlaces del mapa armados en Python: en plantillas, con el idioma es-cl,
    los decimales salen con coma y rompen las URLs.
    """
    if lat is None or lon is None:
        return None
    bbox = f"{lon - 0.006:.6f},{lat - 0.004:.6f},{lon + 0.006:.6f},{lat + 0.004:.6f}"
    return {
        "coordenadas": f"{lat:.6f}, {lon:.6f}",
        "embed": (
            "https://www.openstreetmap.org/export/embed.html?"
            + urlencode({"bbox": bbox, "layer": "mapnik", "marker": f"{lat:.6f},{lon:.6f}"})
        ),
        "google": "https://www.google.com/maps/search/?" + urlencode({"api": 1, "query": f"{lat:.6f},{lon:.6f}"}),
    }



# =========================================================
# EDITAR RUTA (nombre, fecha y chofer)
# =========================================================
def _reglas_edicion_ruta(ruta):
    """
    - El nombre se puede cambiar siempre.
    - El chofer se puede cambiar aunque la ruta ya haya empezado (p. ej. se
      enfermo a mitad del reparto): el nuevo ve solo lo pendiente.
    - La fecha solo si la ruta no ha empezado: no se mueve de dia una ruta
      con entregas hechas.
    - Rutas pasadas, completadas o canceladas: solo el nombre (historial).
    """
    cerrada = ruta.estado in ("COMPLETADA", "CANCELADA") or ruta.fecha < timezone.localdate()
    empezada = ruta.paradas.exclude(estado_entrega="PENDIENTE").exists()
    return {
        "cerrada": cerrada,
        "empezada": empezada,
        "puede_cambiar_chofer": not cerrada,
        "puede_cambiar_fecha": not cerrada and not empezada,
    }


@user_passes_test(es_admin_o_owner)
def editar_ruta_view(request, ruta_id):
    empresa = get_empresa(request)
    ruta = get_object_or_404_scoped(Ruta, empresa, id=ruta_id)
    reglas = _reglas_edicion_ruta(ruta)
    hoy = timezone.localdate()
    choferes = Chofer.objects.filter(perfil__empresa=empresa, activo=True).select_related("perfil__user")
    error = None

    if request.method == "POST":
        nombre = (request.POST.get("nombre") or "").strip()
        nueva_fecha = ruta.fecha
        nuevo_chofer = ruta.chofer

        if not nombre:
            error = "El nombre de la ruta es obligatorio."

        if not error and reglas["puede_cambiar_fecha"]:
            try:
                nueva_fecha = date.fromisoformat(request.POST.get("fecha", ""))
            except ValueError:
                error = "La fecha no es válida."
            else:
                if nueva_fecha < hoy:
                    error = f"La fecha no puede ser anterior a hoy ({hoy.strftime('%d-%m-%Y')})."

        if not error and reglas["puede_cambiar_chofer"]:
            nuevo_chofer = choferes.filter(id=request.POST.get("chofer_id")).first()
            if nuevo_chofer is None:
                error = "Elige un chofer activo de tu empresa."

        if not error:
            chofer_anterior = ruta.chofer
            cambio_chofer = nuevo_chofer.id != chofer_anterior.id
            cambio_fecha = nueva_fecha != ruta.fecha
            cambio_nombre = nombre != ruta.nombre

            ruta.nombre, ruta.fecha, ruta.chofer = nombre, nueva_fecha, nuevo_chofer
            ruta.save()

            if cambio_chofer:
                avisar_ruta_quitada(ruta, chofer_anterior)
                avisar_ruta_asignada(ruta, request)
                messages.success(
                    request,
                    f"Ruta reasignada a {nuevo_chofer.perfil.user.get_full_name() or nuevo_chofer.perfil.user.username}. "
                    "Se avisó al chofer nuevo y al anterior.",
                )
            elif cambio_fecha or cambio_nombre:
                detalle = (
                    f"la fecha cambió a {fecha_legible(nueva_fecha).removeprefix('el ')}."
                    if cambio_fecha else f"el nombre cambió a {nombre}."
                )
                avisar_ruta_actualizada(ruta, detalle)
                messages.success(request, "Ruta actualizada. Se avisó al chofer.")
            else:
                messages.info(request, "No hubo cambios.")
            return redirect("detalle_ruta", ruta_id=ruta.id)

    return render(request, "core/editar_ruta.html", {
        "ruta": ruta,
        "choferes": choferes,
        "reglas": reglas,
        "hoy": hoy,
        "error": error,
    })


# =========================================================
# USUARIOS DE LA EMPRESA (solo el dueño): ver, desactivar, restablecer clave
# =========================================================
def _perfil_gestionable(request, user_id):
    """
    Perfil de un usuario de la misma empresa que el dueño puede gestionar:
    administradores y choferes. Nunca el propio dueño ni otra empresa (404).
    """
    empresa = get_empresa(request)
    return get_object_or_404(
        PerfilUsuario.objects.select_related("user", "empresa"),
        user_id=user_id, empresa=empresa, rol__in=("ADMIN", "CHOFER"),
    )


def _desactivar_usuario(perfil):
    """
    Desactivar en vez de borrar: el usuario no puede entrar (y su sesión
    abierta deja de valer), pero sus rutas y entregas quedan en el historial.
    """
    perfil.user.is_active = False
    perfil.user.save(update_fields=["is_active"])
    perfil.desactivado_en = timezone.now()
    perfil.save(update_fields=["desactivado_en"])
    Chofer.objects.filter(perfil=perfil).update(activo=False)


@user_passes_test(es_owner)
def lista_usuarios_view(request):
    empresa = get_empresa(request)
    perfiles = (
        PerfilUsuario.objects.filter(empresa=empresa)
        .select_related("user")
        .order_by("-user__is_active", "rol", "user__first_name", "user__username")
    )
    return render(request, "core/lista_usuarios.html", {"perfiles": perfiles})


@user_passes_test(es_owner)
@require_POST
def cambiar_estado_usuario_view(request, user_id):
    perfil = _perfil_gestionable(request, user_id)
    usuario = perfil.user
    nombre = usuario.get_full_name() or usuario.username

    if usuario.is_active:
        _desactivar_usuario(perfil)
        messages.warning(request, f"{nombre} quedó desactivado: ya no puede ingresar.")
        rutas_proximas = Ruta.objects.filter(
            chofer__perfil=perfil, fecha__gte=timezone.localdate(), activa=True,
        ).exclude(estado__in=("COMPLETADA", "CANCELADA"))
        if rutas_proximas.exists():
            nombres = ", ".join(r.nombre for r in rutas_proximas[:5])
            messages.error(
                request,
                f"{nombre} tiene {rutas_proximas.count()} ruta(s) próxima(s) sin terminar: {nombres}. "
                "Reasígnalas a otro chofer desde Editar ruta.",
            )
    else:
        usuario.is_active = True
        usuario.save(update_fields=["is_active"])
        perfil.desactivado_en = None
        perfil.save(update_fields=["desactivado_en"])
        Chofer.objects.filter(perfil=perfil).update(activo=True)
        messages.success(request, f"{nombre} fue reactivado y ya puede ingresar.")
    return redirect("lista_usuarios")


@user_passes_test(es_owner)
@require_POST
def restablecer_clave_usuario_view(request, user_id):
    perfil = _perfil_gestionable(request, user_id)
    usuario = perfil.user
    temp_password = get_random_string(14, allowed_chars=TEMP_PASSWORD_CHARS)
    usuario.set_password(temp_password)
    usuario.save()
    perfil.debe_cambiar_password = True
    perfil.save(update_fields=["debe_cambiar_password"])
    _enviar_credenciales(request, usuario, perfil.empresa, temp_password)

    messages.success(
        request,
        f"Clave de {usuario.username} restablecida. Clave temporal: {temp_password} "
        "(deberá cambiarla al ingresar; también se la enviamos por correo).",
    )
    return redirect("lista_usuarios")



# =========================================================
# CLIENTES SIN UBICACION: reintentar ubicarlos en el mapa
# =========================================================
SIN_UBICACION = Q(latitud__isnull=True) | Q(longitud__isnull=True) | Q(geocodificado=False)
# Nominatim pide como maximo 1 consulta por segundo: un lote chico por clic
# mantiene la pagina rapida y respeta su politica de uso.
REUBICAR_LOTE = 15


@user_passes_test(es_admin_o_owner)
@require_POST
def reubicar_cliente_view(request, cliente_id):
    empresa = get_empresa(request)
    cliente = get_object_or_404_scoped(Cliente, empresa, id=cliente_id)
    from .geocoding import geocodificar_cliente
    if geocodificar_cliente(cliente):
        messages.success(request, f"{cliente.nombre} quedó ubicado en el mapa.")
    else:
        messages.warning(
            request,
            f"No pudimos ubicar a {cliente.nombre}. Revisa su dirección o pega sus coordenadas en Editar.",
        )
    volver = request.POST.get("volver")
    if volver and url_has_allowed_host_and_scheme(volver, allowed_hosts={request.get_host()}):
        return redirect(volver)
    return redirect("lista_clientes")


@user_passes_test(es_admin_o_owner)
@require_POST
def reubicar_clientes_lote_view(request):
    import time
    from .geocoding import geocodificar_cliente

    empresa = get_empresa(request)
    pendientes = list(
        Cliente.objects.filter(empresa=empresa, activo=True).filter(SIN_UBICACION).order_by("id")[:REUBICAR_LOTE]
    )
    ubicados = 0
    for i, cliente in enumerate(pendientes):
        if i:
            time.sleep(1)  # politica de uso de Nominatim
        if geocodificar_cliente(cliente):
            ubicados += 1

    quedan = Cliente.objects.filter(empresa=empresa, activo=True).filter(SIN_UBICACION).count()
    messages.info(
        request,
        f"Se intentó ubicar a {len(pendientes)} cliente(s): {ubicados} quedaron en el mapa. "
        f"Quedan {quedan} sin ubicación"
        + (" — los que no se encuentran necesitan que revises la dirección o pegues sus coordenadas." if quedan else "."),
    )
    return redirect(f"{reverse('lista_clientes')}?ubicacion=sin")
