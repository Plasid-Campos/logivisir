"""
Importación de clientes desde Excel (.xlsx) o CSV.

Las PYMEs ya tienen su cartera en una planilla (a veces 400 o 1.200
clientes): pasarla a mano cliente por cliente no es realista. El flujo es:

1. Subir el archivo (o descargar la plantilla de LogiVisir).
2. Revisar: LogiVisir reconoce las columnas por su nombre («Razón social»,
   «Domicilio», «Fono»...), y el usuario puede corregirlas. Se muestra qué
   filas entran, cuáles se omiten por estar repetidas y cuáles tienen errores.
3. Importar: se guardan todos de una vez, sin ubicar.
4. Ubicar en el mapa por lotes: Nominatim admite una consulta por segundo,
   así que la página de resultado va pidiendo lotes cortos mientras el usuario
   la tiene abierta. Si la cierra, se retoma desde el listado de clientes.

Las filas leídas se guardan en la sesión entre el paso 1 y el 3; no se
guarda el archivo en el servidor.
"""
import csv
import io
import re
import time
import unicodedata
from datetime import date, datetime

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .cuentas import normalizar_rut
from .models import Cliente
from .tenancy import get_empresa
from .views import es_admin_o_owner

MAX_BYTES = 5 * 1024 * 1024
MAX_FILAS = 3000
MAX_COLUMNAS = 40
FILAS_VISTA_PREVIA = 40
CLAVE_SESION = "importacion_clientes"
CLAVE_RESULTADO = "importacion_clientes_resultado"

# Ubicación por lotes: cada pedido del navegador trabaja como máximo unos
# segundos, para no dejar esperando al resto de la página (el plan gratis de
# PythonAnywhere atiende de a una petición), y entre consultas a Nominatim
# se respeta más de un segundo, aunque haya dos pestañas ubicando a la vez.
LOTE_SEGUNDOS = 4
INTERVALO_NOMINATIM = 1.1
CLAVE_CANDADO = "geocodificacion-candado"
CLAVE_ULTIMA_CONSULTA = "geocodificacion-ultima"

CAMPOS = [
    # (clave, etiqueta, obligatorio)
    ("nombre", "Nombre", True),
    ("direccion", "Dirección", True),
    ("comuna", "Comuna", False),
    ("ciudad", "Ciudad", False),
    ("telefono", "Teléfono", False),
    ("email", "Correo", False),
    ("rut", "RUT", False),
    ("tipo", "Tipo", False),
]
ETIQUETAS = {clave: etiqueta for clave, etiqueta, _ in CAMPOS}

# Nombres de columna habituales, del más al menos preciso. Se comparan sin
# tildes ni mayúsculas.
SINONIMOS = {
    "nombre": [
        "nombre", "nombre cliente", "nombre del cliente", "cliente", "nombre fantasia",
        "fantasia", "razon social", "local", "negocio", "establecimiento", "nombre local",
    ],
    "direccion": [
        "direccion", "direccion de despacho", "direccion despacho", "direccion de entrega",
        "direccion entrega", "domicilio", "calle", "dir",
    ],
    "comuna": ["comuna", "comuna despacho"],
    "ciudad": ["ciudad", "localidad"],
    "telefono": ["telefono", "fono", "celular", "movil", "whatsapp", "tel", "telefono contacto"],
    "email": ["correo", "email", "e mail", "mail", "correo electronico"],
    "rut": ["rut", "rut cliente", "run", "rut empresa"],
    "tipo": ["tipo", "tipo cliente", "tipo de cliente"],
}


class ArchivoInvalido(Exception):
    pass


# ---------------------------------------------------------------------------
# Lectura del archivo
# ---------------------------------------------------------------------------
def _normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "").replace(".", "")).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-z0-9]+", " ", texto.lower())
    return texto.strip()


def _celda(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))  # 912345678.0 -> 912345678 (teléfonos, números de calle)
    if isinstance(valor, datetime):
        return valor.strftime("%d-%m-%Y")
    if isinstance(valor, date):
        return valor.strftime("%d-%m-%Y")
    return re.sub(r"\s+", " ", str(valor)).strip()


def _recortar(filas):
    """Quita filas vacías del final y columnas vacías de la derecha."""
    filas = [fila[:MAX_COLUMNAS] for fila in filas]
    while filas and not any(filas[-1]):
        filas.pop()
    ancho = max((max((i + 1 for i, v in enumerate(f) if v), default=0) for f in filas), default=0)
    return [f[:ancho] + [""] * (ancho - len(f[:ancho])) for f in filas]


def _leer_xlsx(contenido):
    import openpyxl

    try:
        libro = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    except Exception:
        raise ArchivoInvalido(
            "No pudimos abrir el archivo como Excel. Si es un .xls antiguo, ábrelo en Excel y "
            "guárdalo como «Libro de Excel (.xlsx)», o expórtalo como CSV."
        )
    hojas = {}
    try:
        for hoja in libro.worksheets:
            filas = []
            for fila in hoja.iter_rows(values_only=True):
                filas.append([_celda(v) for v in fila])
                if len(filas) > MAX_FILAS + 20:
                    raise ArchivoInvalido(
                        f"La hoja «{hoja.title}» tiene más de {MAX_FILAS:,} filas. ".replace(",", ".")
                        + "Divide el archivo en partes e impórtalas por separado."
                    )
            filas = _recortar(filas)
            if filas:
                hojas[hoja.title] = filas
    finally:
        libro.close()
    return hojas


def _leer_csv(contenido):
    for codificacion in ("utf-8-sig", "cp1252"):
        try:
            texto = contenido.decode(codificacion)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ArchivoInvalido("No pudimos leer el texto del archivo CSV.")
    muestra = texto[:5000]
    try:
        separador = csv.Sniffer().sniff(muestra, delimiters=";,\t|").delimiter
    except csv.Error:
        separador = ";" if muestra.count(";") > muestra.count(",") else ","
    filas = [[_celda(v) for v in fila] for fila in csv.reader(io.StringIO(texto), delimiter=separador)]
    if len(filas) > MAX_FILAS + 20:
        raise ArchivoInvalido(
            f"El archivo tiene más de {MAX_FILAS:,} filas. ".replace(",", ".")
            + "Divídelo en partes e impórtalas por separado."
        )
    filas = _recortar(filas)
    return {"CSV": filas} if filas else {}


def leer_archivo(archivo):
    """Devuelve {nombre_hoja: [[celdas como texto], ...]}."""
    nombre = (archivo.name or "").lower()
    if archivo.size > MAX_BYTES:
        raise ArchivoInvalido("El archivo pesa más de 5 MB. Deja solo las columnas de clientes o divídelo en partes.")
    contenido = archivo.read()
    if nombre.endswith((".xlsx", ".xlsm")):
        hojas = _leer_xlsx(contenido)
    elif nombre.endswith((".csv", ".txt")):
        hojas = _leer_csv(contenido)
    elif nombre.endswith(".xls"):
        raise ArchivoInvalido(
            "Los archivos .xls (Excel 97-2003) no se pueden leer directamente. Ábrelo en Excel y "
            "guárdalo como «Libro de Excel (.xlsx)», o expórtalo como CSV."
        )
    else:
        raise ArchivoInvalido("Sube un archivo Excel (.xlsx) o CSV. Desde Google Sheets: Archivo › Descargar › .xlsx.")
    if not hojas:
        raise ArchivoInvalido("El archivo no tiene datos.")
    return hojas


# ---------------------------------------------------------------------------
# Reconocer columnas
# ---------------------------------------------------------------------------
def _puntaje_columna(titulo, campo):
    """Menor es mejor; None si el título no corresponde al campo."""
    titulo = _normalizar(titulo)
    if not titulo:
        return None
    palabras = set(titulo.split())
    for i, sinonimo in enumerate(SINONIMOS[campo]):
        if titulo == sinonimo:
            return i
    for i, sinonimo in enumerate(SINONIMOS[campo]):
        if len(sinonimo) > 3 and set(sinonimo.split()) <= palabras:
            return 100 + i
    return None


def _parece_dato(celda):
    """Una celda con números o @ casi nunca es un título de columna."""
    return bool(re.search(r"\d|@", celda or ""))


def detectar_encabezado(filas):
    """
    Índice de la fila de títulos (la que más títulos conocidos tiene entre las
    10 primeras), o None si la planilla parte directo con los datos.
    """
    mejor, mejor_puntaje = None, 0
    for i, fila in enumerate(filas[:10]):
        # Los títulos van antes que los clientes: al llegar a la primera fila
        # con datos (una dirección, un correo, un teléfono) se deja de buscar.
        # Así un cliente llamado «Sin dirección» no se toma por fila de títulos.
        if _es_fila_de_datos(fila):
            break
        puntajes = [
            min(p for p in (_puntaje_columna(celda, campo) for celda in fila) if p is not None)
            for campo in SINONIMOS
            if any(_puntaje_columna(celda, campo) is not None for celda in fila)
        ]
        puntaje = len(puntajes)
        exactos = sum(1 for p in puntajes if p < 100)
        # Un solo título parecido («Cliente regular») no basta: hace falta uno
        # exacto o al menos dos reconocidos, y más títulos que datos.
        if (
            puntaje > mejor_puntaje and (exactos or puntaje >= 2)
            and sum(1 for c in fila if _parece_dato(c)) < puntaje
        ):
            mejor, mejor_puntaje = i, puntaje
    if mejor is not None:
        return mejor
    primera = _primera_fila_con_datos(filas)
    if primera is None or any(_parece_direccion(c) or "@" in c for c in filas[primera]):
        return None  # sin títulos: la primera fila ya es un cliente
    return primera     # títulos que no reconocemos («Cod», «Local», «Ubicación»...)


def _es_fila_de_datos(fila):
    llenas = [c for c in fila if c]
    return len(llenas) >= 2 and any(
        (_parece_direccion(c) or "@" in c or _parece_telefono(c))
        and not any(_puntaje_columna(c, campo) is not None for campo in SINONIMOS)  # «Dirección 2» es un título
        for c in llenas
    )


def _primera_fila_con_datos(filas):
    return next((i for i, fila in enumerate(filas) if sum(1 for c in fila if c) >= 2), None)


def inicio_de_datos(filas, fila_titulos):
    if fila_titulos is not None:
        return fila_titulos + 1
    return _primera_fila_con_datos(filas) or 0


def detectar_mapeo(titulos):
    """{campo: índice de columna} con la mejor coincidencia por campo, sin repetir columnas."""
    candidatos = []
    for campo in SINONIMOS:
        for j, titulo in enumerate(titulos):
            puntaje = _puntaje_columna(titulo, campo)
            if puntaje is not None:
                candidatos.append((puntaje, campo, j))
    mapeo, usadas = {}, set()
    for _, campo, j in sorted(candidatos):
        if campo not in mapeo and j not in usadas:
            mapeo[campo] = j
            usadas.add(j)
    return mapeo


# ---------------------------------------------------------------------------
# Reconocer columnas por su contenido (planillas sin títulos o con títulos
# que no conocemos): se mira una muestra de valores de cada columna.
# ---------------------------------------------------------------------------
COMUNAS = {_normalizar(c) for c in (
    "Santiago", "Cerrillos", "Cerro Navia", "Conchalí", "El Bosque", "Estación Central", "Huechuraba",
    "Independencia", "La Cisterna", "La Florida", "La Granja", "La Pintana", "La Reina", "Las Condes",
    "Lo Barnechea", "Lo Espejo", "Lo Prado", "Macul", "Maipú", "Ñuñoa", "Pedro Aguirre Cerda",
    "Peñalolén", "Providencia", "Pudahuel", "Quilicura", "Quinta Normal", "Recoleta", "Renca",
    "San Joaquín", "San Miguel", "San Ramón", "Vitacura", "Puente Alto", "Pirque", "San José de Maipo",
    "Colina", "Lampa", "Tiltil", "San Bernardo", "Buin", "Calera de Tango", "Paine", "Melipilla",
    "Talagante", "Peñaflor", "Padre Hurtado", "El Monte", "Isla de Maipo", "Curacaví",
    "Valparaíso", "Viña del Mar", "Concepción", "Talcahuano", "Rancagua", "Talca", "Temuco",
    "La Serena", "Coquimbo", "Antofagasta", "Iquique", "Arica", "Puerto Montt", "Chillán",
    "Valdivia", "Osorno", "Los Ángeles", "Copiapó", "Calama", "Punta Arenas", "Quilpué", "Villa Alemana",
)}
_LETRAS = re.compile(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{2,}")


def _parece_direccion(celda):
    return bool(celda and "@" not in celda and _LETRAS.search(celda) and re.search(r"\d", celda))


_PALABRAS_CALLE = {
    "av", "avda", "avenida", "calle", "pasaje", "psje", "pje", "camino", "ruta", "pob", "poblacion",
    "villa", "block", "depto", "dpto", "local", "of", "oficina", "parcela", "km", "n", "nro", "general",
    "gral", "san", "santa", "los", "las", "el", "la", "del", "de",
}


def _puntaje_direccion(valores):
    """
    Fracción de valores con forma de dirección, con un pequeño extra cuando
    traen palabras de calle («Av.», «Pasaje»...) o una numeración de 3 o más
    dígitos: así «Gran Avenida 4400» le gana a un nombre como «Minimarket 2».
    """
    if not valores:
        return 0
    total = 0
    for v in valores:
        if not _parece_direccion(v):
            continue
        total += 1
        if set(_normalizar(v).split()) & _PALABRAS_CALLE:
            total += 0.2
        if re.search(r"\d{3,}", v):
            total += 0.2
    return total / len(valores)


def _parece_telefono(celda):
    limpio = re.sub(r"[\s+()\-.]", "", celda or "")
    return limpio.isdigit() and 8 <= len(limpio) <= 12


def _parece_rut(celda):
    return "-" in (celda or "") and normalizar_rut(celda) is not None


def _parece_correo(celda):
    if "@" not in (celda or ""):
        return False
    try:
        validate_email(celda)
        return True
    except ValidationError:
        return False


def _fraccion(valores, condicion):
    return sum(1 for v in valores if condicion(v)) / len(valores) if valores else 0


def adivinar_por_contenido(filas_datos, ancho, campos, usadas=()):
    """{campo: columna} para los campos pedidos, mirando solo columnas libres."""
    muestras = {
        j: [f[j] for f in filas_datos[:300] if j < len(f) and f[j]]
        for j in range(ancho) if j not in usadas
    }
    muestras = {j: v for j, v in muestras.items() if v}
    mapeo = {}

    def tomar(campo, puntaje, minimo):
        if campo not in campos or not muestras:
            return
        j, valor = max(((j, puntaje(v)) for j, v in muestras.items()), key=lambda x: (x[1], -x[0]))
        if valor >= minimo:
            mapeo[campo] = j
            del muestras[j]

    tomar("email", lambda v: _fraccion(v, _parece_correo), 0.6)
    tomar("rut", lambda v: _fraccion(v, _parece_rut), 0.6)
    tomar("telefono", lambda v: _fraccion(v, _parece_telefono), 0.6)
    tomar("direccion", _puntaje_direccion, 0.6)
    tomar("comuna", lambda v: _fraccion(v, lambda c: _normalizar(c) in COMUNAS), 0.5)
    tomar("tipo", lambda v: _fraccion(v, lambda c: any(p in _normalizar(c) for p in ("deliv", "regular", "domicil", "normal"))), 0.6)
    if "nombre" in campos and muestras:
        # El nombre: la primera columna (de izquierda a derecha) de textos
        # distintos entre sí, que no son números ni códigos.
        for j in sorted(muestras):
            v = muestras[j]
            textos = _fraccion(v, lambda c: bool(_LETRAS.search(c)) and "@" not in c)
            distintos = len(set(v)) / len(v)
            largo = sum(len(c) for c in v) / len(v)
            if textos >= 0.8 and (distintos >= 0.6 or len(v) < 5) and largo >= 4:
                mapeo["nombre"] = j
                break
    return mapeo


def estructura(filas):
    """
    Lo que LogiVisir entiende de una hoja: dónde están los títulos (o si no
    hay), desde qué fila parten los clientes y qué columna tiene cada dato.
    """
    fila_titulos = detectar_encabezado(filas)
    inicio = inicio_de_datos(filas, fila_titulos)
    ancho = max((len(f) for f in filas), default=0)
    titulos = filas[fila_titulos] if fila_titulos is not None else [""] * ancho
    mapeo = detectar_mapeo(titulos)
    faltan = [c for c in SINONIMOS if c not in mapeo and c != "ciudad"]
    por_contenido = adivinar_por_contenido(filas[inicio:], ancho, faltan, usadas=set(mapeo.values()))
    mapeo.update(por_contenido)
    return {
        "fila_titulos": fila_titulos, "inicio": inicio, "titulos": titulos, "ancho": ancho,
        "mapeo": mapeo, "por_contenido": set(por_contenido),
    }


# ---------------------------------------------------------------------------
# Validar filas
# ---------------------------------------------------------------------------
def _clave_cliente(nombre, direccion):
    return (_normalizar(nombre), _normalizar(direccion))


def _tipo(texto):
    t = _normalizar(texto)
    return "DELIVERY" if any(p in t for p in ("deliv", "domicil", "particular")) else "NORMAL"


def analizar(filas, inicio, mapeo, empresa):
    """
    Revisa cada fila y la clasifica en: nueva, repetida (ya existe en la
    empresa o aparece antes en el mismo archivo) o con error. Devuelve un
    dict con las listas y los datos listos para crear.
    """
    existentes_clave = {
        _clave_cliente(n, d) for n, d in Cliente.objects.filter(empresa=empresa).values_list("nombre", "direccion")
    }
    existentes_rut = {
        normalizar_rut(r) or r
        for r in Cliente.objects.filter(empresa=empresa).exclude(rut__isnull=True).exclude(rut="").values_list("rut", flat=True)
    }
    ciudad_defecto = empresa.ciudad_origen or ""

    def valor(fila, campo):
        j = mapeo.get(campo)
        return fila[j].strip() if j is not None and j < len(fila) else ""

    resultado = {"nuevos": [], "repetidos": [], "errores": [], "avisos": 0, "filas": []}
    vistos_clave, vistos_rut = set(), set()

    for i, fila in enumerate(filas[inicio:], start=inicio + 1):
        if not any(fila):
            continue
        datos = {campo: valor(fila, campo) for campo in SINONIMOS}
        avisos = []
        errores = []

        if not datos["nombre"]:
            errores.append("falta el nombre")
        if not datos["direccion"]:
            errores.append("falta la dirección")

        rut = None
        if datos["rut"]:
            rut = normalizar_rut(datos["rut"])
            if rut is None:
                avisos.append(f"RUT «{datos['rut']}» no válido: se deja en blanco")

        email = datos["email"] or None
        if email:
            try:
                validate_email(email)
            except ValidationError:
                avisos.append(f"correo «{email}» no válido: se deja en blanco")
                email = None

        telefono = datos["telefono"] or None
        if telefono and len(telefono) > 20:
            avisos.append("teléfono demasiado largo: se deja en blanco")
            telefono = None

        for campo, largo in (("nombre", 120), ("direccion", 200), ("comuna", 100), ("ciudad", 100)):
            if len(datos[campo]) > largo:
                datos[campo] = datos[campo][:largo].strip()
                avisos.append(f"{ETIQUETAS[campo].lower()} recortado a {largo} caracteres")

        estado, motivo = "nuevo", ""
        if errores:
            estado, motivo = "error", "; ".join(errores).capitalize()
        else:
            clave = _clave_cliente(datos["nombre"], datos["direccion"])
            if rut and rut in existentes_rut or clave in existentes_clave:
                estado, motivo = "repetido", "Ya está en tus clientes"
            elif rut and rut in vistos_rut or clave in vistos_clave:
                estado, motivo = "repetido", "Aparece más arriba en el archivo"
            vistos_clave.add(clave)
            if rut:
                vistos_rut.add(rut)

        registro = {
            "fila": i,
            "estado": estado,
            "motivo": motivo,
            "avisos": avisos,
            "nombre": datos["nombre"],
            "direccion": datos["direccion"],
            "comuna": datos["comuna"],
            "ciudad": datos["ciudad"] or ciudad_defecto,
            "telefono": telefono,
            "email": email,
            "rut": rut,
            "tipo": _tipo(datos["tipo"]),
        }
        resultado["filas"].append(registro)
        if estado == "nuevo":
            resultado["nuevos"].append(registro)
            resultado["avisos"] += bool(avisos)
        elif estado == "repetido":
            resultado["repetidos"].append(registro)
        else:
            resultado["errores"].append(registro)
    return resultado


def crear_clientes(empresa, nuevos):
    clientes = [
        Cliente(
            empresa=empresa, nombre=r["nombre"], direccion=r["direccion"],
            comuna=r["comuna"] or None, ciudad=r["ciudad"] or None,
            telefono=r["telefono"], email=r["email"], rut=r["rut"],
            tipo_cliente=r["tipo"], ubicacion_pendiente=True,
        )
        for r in nuevos
    ]
    with transaction.atomic():
        creados = Cliente.objects.bulk_create(clientes, batch_size=200)
    return [c.id for c in creados]


# ---------------------------------------------------------------------------
# Ubicar en el mapa por lotes
# ---------------------------------------------------------------------------
def _copiar_ubicacion_conocida(cliente):
    """Si otro cliente de la empresa ya está ubicado en la misma dirección, reutiliza sus coordenadas."""
    gemelo = (
        Cliente.objects.filter(
            empresa_id=cliente.empresa_id, geocodificado=True,
            direccion__iexact=cliente.direccion, comuna__iexact=cliente.comuna or "",
        )
        .exclude(id=cliente.id)
        .exclude(latitud__isnull=True)
        .first()
    )
    if gemelo is None:
        return False
    cliente.latitud, cliente.longitud, cliente.geocodificado = gemelo.latitud, gemelo.longitud, True
    return True


def _esperar_turno_nominatim():
    ultima = cache.get(CLAVE_ULTIMA_CONSULTA)
    if ultima:
        espera = INTERVALO_NOMINATIM - (time.monotonic() - ultima)
        if 0 < espera <= INTERVALO_NOMINATIM:
            time.sleep(espera)
    cache.set(CLAVE_ULTIMA_CONSULTA, time.monotonic(), 60)


def ubicar_lote(empresa, segundos=LOTE_SEGUNDOS):
    """Ubica clientes pendientes de la empresa durante unos segundos. Devuelve cuántos procesó."""
    from .geocoding import geocodificar_direccion

    inicio = time.monotonic()
    procesados = 0
    pendientes = Cliente.objects.filter(empresa=empresa, ubicacion_pendiente=True).order_by("id")
    for cliente in pendientes.iterator():
        if procesados and time.monotonic() - inicio > segundos:
            break
        if not _copiar_ubicacion_conocida(cliente):
            _esperar_turno_nominatim()
            coordenadas = geocodificar_direccion(cliente.direccion, cliente.comuna, cliente.ciudad)
            if coordenadas:
                cliente.latitud, cliente.longitud = coordenadas
                cliente.geocodificado = True
            else:
                cliente.latitud = cliente.longitud = None
                cliente.geocodificado = False
        cliente.ubicacion_pendiente = False
        cliente.save(update_fields=["latitud", "longitud", "geocodificado", "ubicacion_pendiente"])
        procesados += 1
    return procesados


def _estado_ubicacion(empresa, ids=None):
    qs = Cliente.objects.filter(empresa=empresa)
    if ids:
        qs = qs.filter(id__in=ids)
        total = len(ids)
    else:
        total = None
    pendientes = qs.filter(ubicacion_pendiente=True).count()
    ubicados = qs.filter(ubicacion_pendiente=False, geocodificado=True).count() if ids else None
    sin_ubicar = qs.filter(ubicacion_pendiente=False, geocodificado=False).count() if ids else None
    return {"total": total, "pendientes": pendientes, "ubicados": ubicados, "sin_ubicar": sin_ubicar}


# ---------------------------------------------------------------------------
# Vistas
# ---------------------------------------------------------------------------
def _entero(texto, defecto=None):
    try:
        return int(texto)
    except (TypeError, ValueError):
        return defecto


def _mapeo_desde(datos, ancho, automatico):
    """Lee el mapeo elegido por el usuario (col_<campo>=índice o vacío); si no eligió, el automático."""
    if not any(f"col_{c}" in datos for c in SINONIMOS):
        return automatico
    mapeo = {}
    for campo in SINONIMOS:
        j = _entero(datos.get(f"col_{campo}"))
        if j is not None and 0 <= j < ancho:
            mapeo[campo] = j
    return mapeo


def _letra_columna(j):
    letras = ""
    j += 1
    while j:
        j, resto = divmod(j - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def _estructura_elegida(filas, datos):
    """La estructura automática, con la corrección del usuario sobre la fila de títulos."""
    auto = estructura(filas)
    eleccion = datos.get("titulos")
    if eleccion == "no" and auto["fila_titulos"] is not None:
        # Misma hoja, pero leída como si la primera fila ya fuera un cliente.
        primera = _primera_fila_con_datos(filas) or 0
        ancho = auto["ancho"]
        mapeo = adivinar_por_contenido(filas[primera:], ancho, [c for c in SINONIMOS if c != "ciudad"])
        return {"fila_titulos": None, "inicio": primera, "titulos": [""] * ancho, "ancho": ancho,
                "mapeo": mapeo, "por_contenido": set(mapeo)}
    if eleccion == "si" and auto["fila_titulos"] is None:
        primera = _primera_fila_con_datos(filas) or 0
        titulos = filas[primera] if filas else []
        mapeo = detectar_mapeo(titulos)
        faltan = [c for c in SINONIMOS if c not in mapeo and c != "ciudad"]
        extra = adivinar_por_contenido(filas[primera + 1:], auto["ancho"], faltan, usadas=set(mapeo.values()))
        mapeo.update(extra)
        return {"fila_titulos": primera, "inicio": primera + 1, "titulos": titulos, "ancho": auto["ancho"],
                "mapeo": mapeo, "por_contenido": set(extra)}
    return auto


def _preparar_revision(request, empresa, datos):
    guardado = request.session.get(CLAVE_SESION)
    hojas = guardado["hojas"]
    nombres = list(hojas)
    misma_hoja = datos.get("hoja") in hojas
    hoja = datos.get("hoja") if misma_hoja else guardado.get("hoja_sugerida", nombres[0])
    filas = hojas[hoja]
    est = _estructura_elegida(filas, datos if misma_hoja else {})
    mapeo = _mapeo_desde(datos, est["ancho"], est["mapeo"]) if misma_hoja else est["mapeo"]
    falta = [ETIQUETAS[c] for c, _, obligatorio in CAMPOS if obligatorio and c not in mapeo]
    analisis = analizar(filas, est["inicio"], mapeo, empresa) if not falta else None
    datos_filas = filas[est["inicio"]:]
    columnas = []
    for j in range(est["ancho"]):
        titulo = est["titulos"][j] if j < len(est["titulos"]) else ""
        columnas.append({
            "indice": j,
            "titulo": titulo or f"Columna {_letra_columna(j)}",
            "ejemplo": next((f[j] for f in datos_filas if j < len(f) and f[j]), ""),
        })
    return {
        "archivo": guardado["archivo"], "hojas": nombres, "hoja": hoja,
        "con_titulos": est["fila_titulos"] is not None,
        "fila_titulos": est["fila_titulos"] + 1 if est["fila_titulos"] is not None else None,
        "columnas": columnas, "campos": [
            {"clave": c, "etiqueta": e, "obligatorio": o, "columna": mapeo.get(c),
             "por_contenido": c in est["por_contenido"] and mapeo.get(c) == est["mapeo"].get(c)}
            for c, e, o in CAMPOS
        ],
        "mapeo": mapeo, "falta": falta, "analisis": analisis,
        "vista_previa": analisis["filas"][:FILAS_VISTA_PREVIA] if analisis else [],
    }


def _hoja_sugerida(hojas):
    """La hoja donde mejor se reconocen nombre y dirección (o la primera)."""
    def puntaje(nombre):
        filas = hojas[nombre]
        mapeo = estructura(filas)["mapeo"] if filas else {}
        return (("nombre" in mapeo) + ("direccion" in mapeo), len(mapeo), len(filas))
    return max(hojas, key=puntaje)


@user_passes_test(es_admin_o_owner)
def importar_clientes_view(request):
    empresa = get_empresa(request)

    if request.method == "POST" and request.POST.get("accion") == "importar":
        if CLAVE_SESION not in request.session:
            messages.warning(request, "La importación expiró. Vuelve a subir el archivo.")
            return redirect("importar_clientes")
        revision = _preparar_revision(request, empresa, request.POST)
        if revision["falta"]:
            messages.error(request, "Indica qué columna tiene el nombre y cuál la dirección.")
            return redirect(reverse("importar_clientes") + "?revisar=1")
        analisis = revision["analisis"]
        ids = crear_clientes(empresa, analisis["nuevos"])
        del request.session[CLAVE_SESION]
        request.session[CLAVE_RESULTADO] = {
            "archivo": revision["archivo"], "ids": ids,
            "repetidos": len(analisis["repetidos"]), "errores": len(analisis["errores"]),
        }
        return redirect("importar_clientes_resultado")

    if request.method == "POST":
        archivo = request.FILES.get("archivo")
        if not archivo:
            return render(request, "core/importar_clientes.html", {"error": "Elige un archivo para subir."})
        try:
            hojas = leer_archivo(archivo)
        except ArchivoInvalido as e:
            return render(request, "core/importar_clientes.html", {"error": str(e)})
        request.session[CLAVE_SESION] = {
            "archivo": archivo.name, "hojas": hojas, "hoja_sugerida": _hoja_sugerida(hojas),
        }
        return redirect(reverse("importar_clientes") + "?revisar=1")

    if request.GET.get("cancelar"):
        request.session.pop(CLAVE_SESION, None)
        return redirect("importar_clientes")

    if request.GET.get("revisar") and CLAVE_SESION in request.session:
        return render(request, "core/importar_clientes_revisar.html", _preparar_revision(request, empresa, request.GET))

    return render(request, "core/importar_clientes.html", {
        "pendientes": Cliente.objects.filter(empresa=empresa, ubicacion_pendiente=True).count(),
        "max_filas": MAX_FILAS,
    })


@user_passes_test(es_admin_o_owner)
def importar_clientes_resultado_view(request):
    empresa = get_empresa(request)
    resultado = request.session.get(CLAVE_RESULTADO) or {}
    ids = resultado.get("ids") or []
    estado = _estado_ubicacion(empresa, ids)
    if not resultado and not estado["pendientes"]:
        return redirect("lista_clientes")
    return render(request, "core/importar_clientes_resultado.html", {
        "resultado": resultado, "creados": len(ids), "estado": estado,
        "minutos": max(1, round(estado["pendientes"] * 1.5 / 60)),
    })


@user_passes_test(es_admin_o_owner)
@require_POST
def ubicar_importados_view(request):
    empresa = get_empresa(request)
    ids = (request.session.get(CLAVE_RESULTADO) or {}).get("ids") or []
    # Una sola tanda a la vez en todo el servidor: así dos pestañas (o dos
    # empresas) no superan juntas el límite de Nominatim.
    if not cache.add(CLAVE_CANDADO, 1, LOTE_SEGUNDOS * 4):
        return JsonResponse({"ocupado": True, **_estado_ubicacion(empresa, ids)})
    try:
        procesados = ubicar_lote(empresa)
    finally:
        cache.delete(CLAVE_CANDADO)
    return JsonResponse({"ocupado": False, "procesados": procesados, **_estado_ubicacion(empresa, ids)})


@user_passes_test(es_admin_o_owner)
def plantilla_clientes_view(request):
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.title = "Clientes"
    hoja.append(["Nombre", "Dirección", "Comuna", "Ciudad", "Teléfono", "Correo", "RUT", "Tipo"])
    hoja.append(["Almacén Doña Rosa", "Gran Avenida 4400", "San Miguel", "Santiago", "+56 9 1234 5678", "", "", "Cliente regular"])
    hoja.append(["Minimarket El Sol", "Av. Pajaritos 2150, local 3", "Maipú", "Santiago", "", "contacto@elsol.cl", "76.543.210-3", "Cliente regular"])
    hoja.append(["María González", "Los Aromos 345", "La Florida", "Santiago", "+56 9 8765 4321", "", "", "Delivery a domicilio"])
    for celda in hoja[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="1D4ED8")
    for columna, ancho in zip("ABCDEFGH", (28, 34, 16, 14, 18, 26, 14, 22)):
        hoja.column_dimensions[columna].width = ancho
    hoja.freeze_panes = "A2"
    tipos = DataValidation(type="list", formula1='"Cliente regular,Delivery a domicilio"', allow_blank=True)
    hoja.add_data_validation(tipos)
    tipos.add("H2:H3001")

    ayuda = libro.create_sheet("Instrucciones")
    for linea in (
        "Cómo llenar la planilla de clientes para LogiVisir",
        "",
        "Obligatorios: Nombre y Dirección (calle y número). El resto es opcional.",
        "Comuna ayuda a ubicar bien la dirección en el mapa: inclúyela siempre que puedas.",
        "Si la ciudad queda en blanco, se usa la ciudad de tu empresa.",
        "Tipo: «Cliente regular» o «Delivery a domicilio» (en blanco = regular).",
        "Borra las filas de ejemplo antes de importar.",
        "También puedes subir tu propia planilla: LogiVisir reconoce columnas como",
        "«Razón social», «Domicilio», «Fono» o «Correo electrónico», y tú confirmas antes de importar.",
    ):
        ayuda.append([linea])
    ayuda["A1"].font = Font(bold=True, size=13)
    ayuda.column_dimensions["A"].width = 100

    salida = io.BytesIO()
    libro.save(salida)
    respuesta = HttpResponse(
        salida.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    respuesta["Content-Disposition"] = 'attachment; filename="plantilla_clientes_logivisir.xlsx"'
    return respuesta
