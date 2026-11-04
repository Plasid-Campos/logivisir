"""
Contenido del chat de ayuda del sitio público. Es un chat guiado: las
respuestas las escribimos nosotros, así que nunca inventa precios ni
funciones. Los montos salen de membresias.py para que no se desalineen.
"""
from django.urls import reverse

from . import membresias
from .templatetags.formato import clp


def _precio(codigo):
    return f"${clp(membresias.PRECIOS_PLAN[codigo])}"


def temas():
    """Cada tema: id, botón, palabras clave, mensajes (burbujas) y sugerencias siguientes."""
    solicitar = reverse("solicitar_cuenta")
    return [
        {
            "id": "que_es",
            "boton": "¿Qué es LogiVisir?",
            "claves": ["que es", "que hace", "logivisir", "sirve", "para que", "funciona la plataforma", "software"],
            "mensajes": [
                "Te lo cuento corto: LogiVisir es una plataforma web para negocios que reparten, como panaderías y distribuidoras.",
                "Tú cargas tus clientes y los pedidos del día, y LogiVisir arma la ruta en el orden que menos kilómetros recorre. Tu chofer la ve en su celular y marca cada entrega con foto.",
                "Y tú, desde el panel, ves qué se entregó y qué no, sin llamar a nadie.",
            ],
            "siguientes": ["optimizacion", "roles", "precios"],
        },
        {
            "id": "optimizacion",
            "boton": "¿Cómo ordena las rutas?",
            "claves": ["optimiza", "optimizacion", "ruta", "orden", "kilometro", "km", "algoritmo", "calle", "mapa", "ahorro", "ahorra"],
            "mensajes": [
                "Buena pregunta 🙂 Primero mide la distancia real por calle entre tu local y cada cliente, usando el mapa abierto OpenStreetMap.",
                "Con esas distancias arma un primer orden yendo siempre al cliente más cercano, y después lo pule: prueba dar vuelta tramos de la ruta y se queda con el cambio si el recorrido baja.",
                "Un ejemplo real: con 16 entregas en San Miguel y comunas vecinas, el orden en que llegaron los pedidos sumaba 84,5 km. Ordenadas por LogiVisir fueron 38,3 km.",
                "Ojo: tu ahorro depende de cómo planificas hoy. Si ya armas buenas rutas a mano, la diferencia será menor, pero te ahorras el tiempo de armarlas.",
            ],
            "siguientes": ["chofer", "limites", "precios"],
        },
        {
            "id": "roles",
            "boton": "¿Quién ve qué?",
            "claves": ["rol", "roles", "dueno", "administrador", "admin", "usuario", "usuarios", "permiso", "quien ve", "equipo"],
            "mensajes": [
                "Hay tres tipos de usuario en tu empresa:",
                "👤 Dueño: ve todo y además administra los usuarios (crea administradores y choferes, desactiva accesos).",
                "🗂️ Administrador: maneja la operación del día: clientes, pedidos, rutas y analítica.",
                "🚚 Chofer: ve solo su ruta, en orden, y marca cada parada como entregada (con foto) o no entregada (con el motivo).",
            ],
            "siguientes": ["chofer", "privacidad", "precios"],
        },
        {
            "id": "chofer",
            "boton": "¿El chofer necesita una app?",
            "claves": ["instalar", "app", "aplicacion", "celular", "telefono", "descargar", "chofer", "conductor", "repartidor", "google maps", "waze"],
            "mensajes": [
                "No necesita tiendas de aplicaciones. Entra desde el navegador de su celular con su usuario y clave, y si quiere toca «Instalar app»: queda el ícono de LogiVisir en su pantalla, como una app.",
                "Ve sus paradas en orden y con un toque abre Google Maps para navegar. Al llegar marca «Entregado» y saca una foto, o «No entregado» y elige el motivo.",
                "Crear un chofer te toma menos de un minuto: nombre, apellido y correo. El usuario y la clave temporal se generan solos.",
            ],
            "siguientes": ["roles", "contratar"],
        },
        {
            "id": "precios",
            "boton": "¿Cuánto cuesta?",
            "claves": ["precio", "precios", "cuesta", "costo", "valor", "plan", "planes", "pagar", "mensual", "cobran", "barato", "caro", "tarifa"],
            "mensajes": [
                "Es un precio fijo mensual por empresa: no cobramos por chofer ni por usuario.",
                f"• Básico: {_precio('BASICO')} al mes, pensado para 1 a 2 vehículos.\n"
                f"• Pro: {_precio('PRO')} al mes, para 3 a 6 vehículos (el más elegido).\n"
                f"• Empresarial: {_precio('EMPRESARIAL')} al mes, para 7 vehículos o más.",
                "Todos los planes traen todas las funciones. Lo que cambia es el tamaño sugerido y el soporte: el Pro y el Empresarial incluyen la carga inicial de tus clientes, y el Empresarial suma capacitación y soporte dedicado.",
            ],
            "siguientes": ["contratar", "que_incluye"],
        },
        {
            "id": "que_incluye",
            "boton": "¿Qué incluye cada plan?",
            "claves": ["incluye", "funciones", "diferencia", "basico", "pro", "empresarial", "trae"],
            "mensajes": [
                "Todos los planes incluyen: rutas optimizadas con calles reales, panel móvil del chofer con foto o motivo, analítica y segmentación de clientes, avisos en la plataforma y por correo, usuarios dueño, administrador y chofer, y exportación a CSV.",
                "La diferencia está en el acompañamiento: soporte por correo en el Básico, soporte prioritario y carga inicial de clientes en el Pro, y además capacitación y soporte dedicado en el Empresarial.",
            ],
            "siguientes": ["precios", "contratar"],
        },
        {
            "id": "contratar",
            "boton": "¿Cómo contrato?",
            "claves": ["contratar", "contrato", "empezar", "comenzar", "cuenta", "solicitar", "registr", "inscrib", "transferencia", "comprobante", "activar", "demora", "cuanto tarda"],
            "mensajes": [
                "Son 4 pasos:",
                "1️⃣ Llenas «Solicita tu cuenta» con los datos de tu negocio y el plan (toma unos 3 minutos).\n"
                "2️⃣ Te mostramos los datos para transferir y un código de referencia.\n"
                "3️⃣ Subes el comprobante y validamos el pago.\n"
                "4️⃣ Te llegan tus accesos por correo, en menos de 24 horas hábiles.",
                "Puedes pagar 1, 3, 6 o 12 meses. Al entrar por primera vez, el panel te guía paso a paso hasta tu primera ruta.",
            ],
            "accion": {"texto": "Solicitar mi cuenta", "url": solicitar},
            "siguientes": ["precios", "privacidad"],
        },
        {
            "id": "privacidad",
            "boton": "¿Qué pasa con mis datos?",
            "claves": ["dato", "datos", "privacidad", "seguridad", "seguro", "confidencial", "quien ve mis", "competencia", "vender", "comparten"],
            "mensajes": [
                "Esto nos importa mucho 🔒 Cada empresa tiene su propio espacio: tus clientes, choferes y rutas nunca se mezclan con los de otra empresa.",
                "Y algo que no es común: nuestro propio equipo no ve tu operación. Solo vemos los datos de tu membresía (plan, pagos y usuarios), nunca tus clientes, pedidos ni rutas.",
                "Además, LogiVisir no maneja tus precios ni tus ventas, y puedes exportar tus despachos a CSV cuando quieras.",
            ],
            "siguientes": ["que_es", "contratar"],
        },
        {
            "id": "limites",
            "boton": "¿Qué no hace todavía?",
            "claves": ["no hace", "limit", "todavia", "falta", "gps", "en vivo", "tiempo real", "ventana", "horario", "sms", "whatsapp al cliente", "avisa al cliente", "varios vehiculos", "camiones", "api", "integracion"],
            "mensajes": [
                "Te lo digo con honestidad, para que decidas bien. Hoy LogiVisir todavía no:",
                "• avisa a tu cliente final por SMS o WhatsApp cuando va el chofer;\n"
                "• muestra el GPS del chofer en vivo;\n"
                "• respeta horarios de recepción de cada cliente al ordenar;\n"
                "• reparte automáticamente los pedidos entre varios vehículos (cada ruta se arma para un chofer);\n"
                "• se conecta por API con otros sistemas (exporta a CSV).",
                "Varias de estas cosas están en nuestro plan de trabajo. Si alguna es clave para ti, cuéntanos.",
            ],
            "siguientes": ["optimizacion", "humano"],
        },
        {
            "id": "cobertura",
            "boton": "¿Funciona en mi ciudad?",
            "claves": ["ciudad", "region", "santiago", "valparaiso", "concepcion", "regiones", "fuera de", "chile", "comuna", "cobertura"],
            "mensajes": [
                "Sí. Las distancias salen de OpenStreetMap, que cubre todo Chile, así que funciona en cualquier ciudad.",
                "Lo único importante es que las direcciones de tus clientes estén bien escritas; si alguna no se ubica, LogiVisir te avisa para corregirla.",
            ],
            "siguientes": ["precios", "contratar"],
        },
        {
            "id": "humano",
            "boton": "Hablar con una persona",
            "claves": ["persona", "humano", "hablar", "contacto", "telefono de ustedes", "llamar", "ejecutivo", "vendedor", "ayuda", "duda"],
            "mensajes": [
                "¡Claro! Escríbenos y te respondemos personalmente.",
            ],
            "contacto": True,
            "siguientes": ["contratar"],
        },
    ]


def datos_widget(contacto_email="", contacto_whatsapp=""):
    return {
        "saludo": [
            "¡Hola! 👋 Soy el asistente de LogiVisir.",
            "Puedo contarte cómo funciona, cuánto cuesta o cómo empezar. Elige un tema o escríbeme tu pregunta.",
        ],
        "inicio": ["que_es", "optimizacion", "precios", "contratar", "privacidad", "limites"],
        "temas": temas(),
        "no_entendi": [
            "Mmm, esa no la tengo clara 🤔 Prueba con alguno de estos temas, o escríbenos directamente.",
        ],
        "contacto": {
            "email": contacto_email,
            "whatsapp": "".join(c for c in contacto_whatsapp if c.isdigit()),
            "solicitar": reverse("solicitar_cuenta"),
        },
    }
