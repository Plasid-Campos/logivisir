# LogiVisir

**Plataforma web multi-tenant para planificar y optimizar el reparto diario de una pyme.**
Reemplaza la planilla Excel y el "¿quién va primero?" mental por rutas ordenadas
automáticamente, un panel para el chofer y trazabilidad de cada entrega.

Construida con **Django + Django REST Framework**. Proyecto de título de la carrera de
Ingeniería en Informática (INACAP), nacido del problema real de reparto de *Panadería
Macarrón*.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-5.2-092E20?logo=django&logoColor=white)
![Tests](https://img.shields.io/badge/tests-73%20passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-blue)

---

## El problema

Una panadería (o cualquier negocio de reparto) despacha a decenas de clientes al día.
Sin una herramienta, el orden de las paradas lo arma una persona "a ojo", nadie sabe
dónde va el chofer, y las entregas fallidas se pierden en un grupo de WhatsApp.

LogiVisir resuelve eso con tres piezas:

1. **Optimización de rutas** — dado el punto de origen y los clientes de una ruta,
   calcula un orden de visita corto usando distancias reales de calle.
2. **Panel del chofer** — una vista móvil con la ruta del día, navegación a Google Maps
   y marcado de cada entrega (con foto y motivo si no se pudo entregar).
3. **Analítica de ventas** — ingresos por mes y comuna, mejores clientes y segmentación
   automática de clientes (VIP / Frecuente / Ocasional / En riesgo).

---

## Características

**Operación**
- Multi-tenant: varias empresas en una misma instancia, con datos totalmente aislados.
- Roles: Dueño, Administrador y Chofer, cada uno con su propia navegación y permisos.
- Clientes con geocodificación automática de la dirección (Nominatim / OpenStreetMap),
  con reintento sin el sufijo de unidad ("Local 3", "Depto 12"...) cuando el primer
  intento falla.
- Rutas con estados (Planificada → En proceso → Completada) y paradas ordenables.
- Catálogo de productos, carrito y pedidos; los pedidos se asignan a paradas de ruta.

**Motor de optimización de rutas** (`core/optimizer.py`)
- Problema del viajante (TSP): heurística de **vecino más cercano** para construir una
  primera ruta + mejora local **2-opt** hasta alcanzar un óptimo local.
- Distancias de **red vial real** vía OSRM (Open Source Routing Machine sobre
  OpenStreetMap); si OSRM no responde (sin internet, timeout, fuera de cobertura),
  cae automáticamente a distancia geográfica (haversine) sin bloquear la operación.
- Reporta los kilómetros antes/después y el ahorro logrado.

**Panel del chofer**
- Vista de la ruta de hoy y previsualización de la de mañana.
- Marcado de entrega con foto (prueba de entrega) o registro del motivo de no entrega.
- Aviso por correo al chofer cuando se le asigna una ruta, y al cliente según el estado.

**Analítica y segmentación** (`core/analytics.py`)
- Ingresos totales, ticket promedio, ingresos pendientes; series por mes y por comuna.
- **Segmentación RFM (Recencia / Frecuencia / Monto) con K-Means** (scikit-learn):
  agrupa a los clientes y nombra cada grupo por un score de sus centroides, para que
  "VIP" sea siempre el segmento con mejor combinación real de RFM.
- Exportación a CSV para seguir el análisis en Power BI u otra herramienta.

**Seguridad**
- Todo queryset y `get_object_or_404` pasa por un helper de tenant (`core/tenancy.py`);
  se corrigió una vulnerabilidad IDOR de acceso entre empresas.
- Cambio de contraseña obligatorio en el primer ingreso de usuarios creados por un admin.
- Secretos y credenciales solo por variables de entorno; nada en el código.

---

## Stack

| Capa | Tecnología |
|---|---|
| Backend | Python 3.12, Django 5.2, Django REST Framework |
| Datos | SQLite (dev), Django ORM, migraciones |
| Optimización | Implementación propia (vecino más cercano + 2-opt), OSRM |
| Geocodificación | Nominatim / OpenStreetMap |
| Analítica | scikit-learn (K-Means), NumPy |
| Frontend | Plantillas de Django + Bootstrap 5 |
| Correo | SMTP (Gmail) con backend de consola como respaldo |

---

## Correr en local

Requisitos: Python 3.12 y `pip`.

```bash
git clone https://github.com/Plasid-Campos/logivisir.git
cd logivisir/backend

python -m venv venv
# Windows:
venv\Scripts\activate
# Linux / macOS:
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env          # y edita DJANGO_SECRET_KEY

python manage.py migrate
python manage.py seed_demo    # datos de demostración ficticios
python manage.py runserver
```

Abre <http://127.0.0.1:8000/> y entra en **Iniciar sesión** con alguno de los usuarios
que crea `seed_demo` (contraseña `demo12345` en todos):

| Usuario | Rol | Qué ve |
|---|---|---|
| `owner_demo` | Dueño | Panel completo, rutas, clientes, analítica |
| `admin_demo` | Administrador | Operación diaria |
| `chofer_demo` | Chofer | Panel de reparto del día |

> `seed_demo` usa nombres, direcciones y coordenadas **inventados** (comunas de
> Santiago). Con `--reset` borra la empresa demo y la vuelve a crear.

---

## Tests

```bash
python manage.py test
```

73 tests que cubren el optimizador de rutas, el aislamiento multi-tenant, pedidos,
solicitudes de cuenta, la analítica RFM y las vistas.

---

## Estructura

```
backend/
  api_rutas/        # configuración del proyecto Django
  core/
    models.py       # Empresa, Cliente, Chofer, Ruta, ParadaRuta, Producto, Pedido...
    views.py        # vistas (operación, chofer, catálogo, analítica, staff)
    optimizer.py    # TSP: vecino más cercano + 2-opt + OSRM
    geocoding.py    # direcciones -> lat/lon (Nominatim)
    analytics.py    # ingresos, ranking y segmentación RFM con K-Means
    tenancy.py      # aislamiento por empresa (tenant)
    notifications.py# correos a chofer y cliente
    cart.py         # carrito en sesión
    tests/          # 73 tests
    management/commands/
      seed_demo.py            # datos de demostración
      importar_clientes_excel.py
      regeocodificar_clientes.py
```

---

## Estado y próximos pasos

Funciona de punta a punta. Ideas pendientes:

- Mapa interactivo de la ruta optimizada (hoy es una tabla ordenada).
- API REST completa para una app móvil del chofer (hoy el panel es server-rendered).
- Ventanas horarias por cliente en el optimizador.
- Migrar a PostgreSQL y despliegue con contenedores.

---

## Autor

**Alejandro Campos Salas** — Analista Programador, estudiante de Ingeniería en
Informática (INACAP).
[github.com/Plasid-Campos](https://github.com/Plasid-Campos)

## Licencia

MIT — ver [LICENSE](LICENSE).
