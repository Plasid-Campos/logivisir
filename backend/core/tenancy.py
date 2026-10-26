"""
Helper unico para aislar datos por Empresa (tenant). Toda vista que toque
Chofer/Cliente/Ruta/ParadaRuta debe pasar por get_empresa() y filtrar/scoping
sus querysets y get_object_or_404 con este patron, en vez de checks ad hoc.
"""
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404


def get_empresa(request):
    """Devuelve la Empresa del usuario autenticado o corta con 403."""
    perfil = getattr(request.user, "perfilusuario", None)
    empresa = getattr(perfil, "empresa", None)
    if empresa is None:
        raise PermissionDenied("Tu usuario no tiene una empresa asociada.")
    if not empresa.activa:
        # Cubre sesiones abiertas antes de que LogiVisir suspendiera la empresa
        raise PermissionDenied("La cuenta de tu empresa está suspendida.")
    return empresa


def get_object_or_404_scoped(model, empresa, lookup_field="empresa", **kwargs):
    """
    get_object_or_404 pero forzando que el registro pertenezca a `empresa`.
    `lookup_field` permite scoping via relacion (p.ej. "perfil__empresa"
    para Chofer, que no tiene FK directa a Empresa).
    """
    kwargs[lookup_field] = empresa
    return get_object_or_404(model, **kwargs)
