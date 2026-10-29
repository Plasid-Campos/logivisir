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
3. **Analítica de despachos** — despachos por mes y por comuna, clientes con más
   entregas y segmentación automática de clientes (VIP / Frecuente / Ocasional / En riesgo).

LogiVisir solo optimiza el reparto: **no maneja precios, ventas ni montos** del negocio
de sus empresas clientes.

---

## Características

**Operación**
- Multi-tenant: varias empresas en una misma instancia, con datos totalmente aislados.
- Roles de la empresa cliente: Dueño, Administrador y Chofer, cada uno con su propia
  navegación y permisos.
- El dueño gestiona sus usuarios (menú **Usuarios**): los ve, los desactiva o reactiva
  (sin borrar su historial) y les restablece la clave con una temporal.
- **Panel del equipo LogiVisir**, separado de las empresas: lista de empresas clientes
  (plan, contacto, estado, usuarios), alta de usuarios, restablecer claves y
  suspender/reactivar el servicio. Por privacidad, el equipo LogiVisir **no ve** los
  clientes, rutas, pedidos ni choferes de ninguna empresa (tampoco desde `/admin/`).
- Clientes con geocodificación automática de la dirección (Nominatim / OpenStreetMap),
  con reintento sin el sufijo de unidad ("Local 3", "Depto 12"...) cuando el primer
  intento falla.
- Clientes sin ubicación en el mapa: aviso con el total, filtro, botón para reintentar
  (de a uno o por lotes de 15, respetando el límite de Nominatim) y coordenadas pegadas
  desde Google Maps en la edición del cliente.
- Pedidos editables y cancelables antes de la entrega: si ya estaban en una ruta, la
  parada se quita y el chofer recibe un aviso; se registra quién canceló, cuándo y por qué.
- Rutas con estados (Planificada → En proceso → Completada) y paradas ordenables.
- Edición de rutas: nombre siempre; chofer aunque la ruta ya haya empezado (se avisa al
  nuevo y al anterior); fecha solo si aún no empezó. Las rutas pasadas quedan fijas.
- Pedidos simples (cliente + qué se despacha, en texto) que se asignan a paradas de ruta.
- Configuración de la dirección de salida de la empresa (menú **Empresa**): se ubica
  automáticamente en el mapa o con coordenadas pegadas desde Google Maps.

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
- Navegación en Google Maps por tramos (máximo 9 paradas intermedias por enlace, el
  límite de Google) y solo con las paradas pendientes, partiendo desde la ubicación del
  chofer una vez que la ruta empezó.
- Avisos en la plataforma (campana) y por correo cuando se le asigna una ruta o la ruta
  cambia; "Mis rutas" con las próximas y las recientes.

**Analítica y segmentación** (`core/analytics.py`)
- Despachos realizados, entregas al primer intento, entregas con foto y pedidos por
  despachar; series por mes y por comuna; top de clientes por cantidad de despachos.
- **Segmentación RF (Recencia / Frecuencia de despachos) con K-Means** (scikit-learn):
  agrupa a los clientes y nombra cada grupo por un score de sus centroides, para que
  "VIP" sea siempre el segmento con mejor combinación real.
- Exportación a CSV para seguir el análisis en Power BI u otra herramienta.

**Seguridad**
- Todo queryset y `get_object_or_404` pasa por un helper de tenant (`core/tenancy.py`);
  se corrigió una vulnerabilidad IDOR de acceso entre empresas.
- Cambio de contraseña obligatorio en el primer ingreso de usuarios creados por un admin.
- Correo obligatorio y único por usuario; recuperación de contraseña por correo, aviso
  por correo cada vez que cambia la contraseña y bienvenida al crear la cuenta.
- Una empresa suspendida no puede ingresar, ni siquiera con una sesión ya abierta.
- El parámetro `?next=` del login solo acepta rutas internas (sin redirecciones abiertas).
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
| `logivisir_demo` | Equipo LogiVisir | Empresas clientes y solicitudes (sin sus datos) |
| `owner_demo` | Dueño de la Panadería Demo | Panel completo, rutas, clientes, analítica |
| `admin_demo` | Administrador | Operación diaria |
| `chofer_demo` | Chofer | Panel de reparto del día |

> `seed_demo` usa nombres de clientes **inventados**, pero direcciones reales del sur de
> Santiago, verificadas con su número en OpenStreetMap. Con `--reset` borra la empresa demo y la vuelve a crear.

---

## Tests

```bash
python manage.py test
```

183 tests que cubren el optimizador de rutas, el aislamiento multi-tenant, pedidos,
solicitudes de cuenta, el panel del equipo LogiVisir, la analítica y las vistas.

---

## Estructura

```
backend/
  api_rutas/        # configuración del proyecto Django
  core/
    models.py       # Empresa, Cliente, Chofer, Ruta, ParadaRuta, Pedido...
    views.py        # vistas (operación, chofer, pedidos, analítica, staff)
    optimizer.py    # TSP: vecino más cercano + 2-opt + OSRM
    geocoding.py    # direcciones -> lat/lon (Nominatim)
    analytics.py    # despachos, ranking y segmentación RF con K-Means
    tenancy.py      # aislamiento por empresa (tenant)
    notifications.py# correos a chofer y cliente
    tests/          # 183 tests
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
