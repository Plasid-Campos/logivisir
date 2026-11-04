"""
LogiVisir como aplicación instalable (PWA).

El chofer instala el sitio en su teléfono desde el navegador («Instalar
LogiVisir» en Android, «Agregar a inicio» en iPhone) y queda un ícono que
abre su ruta a pantalla completa, sin pasar por tiendas de aplicaciones.

El service worker no guarda páginas con datos de la empresa: solo deja en
caché una página «sin conexión» para mostrar cuando no hay señal. Así nadie
ve rutas viejas ni datos de otra sesión en un teléfono compartido.
"""
import json

from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.views.decorators.cache import cache_control

# Subir la versión cuando cambie lo que el service worker guarda en caché.
VERSION_CACHE = "logivisir-v1"
INICIO_APP = "/app/"


def app_inicio_view(request):
    """Lo que abre el ícono instalado: cada rol a su pantalla."""
    if not request.user.is_authenticated:
        return redirect(f"/login/?next={INICIO_APP}")
    if request.user.is_staff:
        return redirect("staff_panel")
    perfil = getattr(request.user, "perfilusuario", None)
    if perfil and perfil.rol == "CHOFER":
        return redirect("chofer_ruta_hoy")
    return redirect("dashboard")


def datos_manifiesto():
    return {
        "name": "LogiVisir",
        "short_name": "LogiVisir",
        "description": "Rutas de reparto optimizadas: el chofer ve su ruta del día y navega cada parada.",
        "lang": "es-CL",
        "id": INICIO_APP,
        "start_url": INICIO_APP,
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#ffffff",
        "theme_color": "#0b1220",
        "icons": [
            {"src": static("core/img/marca/app-icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": static("core/img/marca/app-icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": static("core/img/marca/app-icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }


@cache_control(max_age=3600)
def manifest_view(request):
    return HttpResponse(
        json.dumps(datos_manifiesto(), ensure_ascii=False, indent=2),
        content_type="application/manifest+json; charset=utf-8",
    )


@cache_control(no_cache=True)
def service_worker_view(request):
    # Se sirve desde la raíz (/sw.js) para que pueda atender todo el sitio.
    return render(
        request, "core/pwa/sw.js",
        {"version": VERSION_CACHE, "icono": static("core/img/marca/app-icon-192.png")},
        content_type="application/javascript; charset=utf-8",
    )


def offline_view(request):
    return render(request, "core/pwa/offline.html", {"icono": static("core/img/marca/app-icon-192.png")})
