# Publicar LogiVisir en internet (PythonAnywhere, gratis)

Resultado: la plataforma queda en `https://USUARIO.pythonanywhere.com`, encendida
todo el día, con datos de demostración ficticios, para que cualquiera (profesores
incluidos) entre desde su computador o teléfono.

En todos los pasos, reemplaza `USUARIO` por el nombre de la cuenta que crees.

## 1. Crear la cuenta

1. Entra a https://www.pythonanywhere.com → **Pricing & signup** → **Create a Beginner account** (gratis, sin tarjeta).
2. El nombre de usuario será parte de la dirección. Sugerencia: `logivisir`.

## 2. Bajar el código

En el menú **Consoles** → **Bash**, pega:

```bash
git clone https://github.com/Plasid-Campos/logivisir.git
cd logivisir/backend
mkvirtualenv --python=python3.12 logivisir
pip install -r requirements.txt
```

La instalación tarda unos minutos. Si avisa que se acabó el espacio (la cuenta
gratis tiene 512 MB), ejecuta `rmvirtualenv logivisir` y repite con
`mkvirtualenv --system-site-packages --python=python3.12 logivisir`. Esa variante
reutiliza numpy y scikit-learn, que PythonAnywhere ya trae instalados.

## 3. Configurar las variables

Genera una clave secreta:

```bash
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

Crea el archivo `.env`:

```bash
nano ~/logivisir/backend/.env
```

con este contenido (pega la clave generada):

```
DJANGO_SECRET_KEY=pega-aqui-la-clave
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=USUARIO.pythonanywhere.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://USUARIO.pythonanywhere.com
DJANGO_SECURE=True
GEOCODING_PROVIDER=nominatim
OSRM_HABILITADO=True
```

Guarda con `Ctrl+O`, `Enter` y sal con `Ctrl+X`.

## 4. Preparar la base de datos con datos de demostración

```bash
cd ~/logivisir/backend
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py seed_demo
python manage.py createsuperuser
```

`seed_demo` crea la "Panadería Demo", con 14 clientes ficticios, productos,
pedidos y rutas. También crea estos usuarios, todos con la contraseña `demo12345`:

| Usuario | Rol |
|---|---|
| `owner_demo` | Dueño/a (todo + analítica) |
| `admin_demo` | Administrador/a |
| `chofer_demo` | Chofer (panel móvil) |

## 5. Crear la aplicación web

En el menú **Web** → **Add a new web app** → **Manual configuration** → **Python 3.12**. Luego, en la misma página:

- **Source code:** `/home/USUARIO/logivisir/backend`
- **Virtualenv:** `/home/USUARIO/.virtualenvs/logivisir`
- **WSGI configuration file:** haz clic en el enlace, borra todo y pega:

```python
import os, sys
path = "/home/USUARIO/logivisir/backend"
if path not in sys.path:
    sys.path.insert(0, path)
os.environ["DJANGO_SETTINGS_MODULE"] = "api_rutas.settings"
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

- **Static files:** agrega dos filas.

| URL | Directory |
|---|---|
| `/static/` | `/home/USUARIO/logivisir/backend/staticfiles` |
| `/media/` | `/home/USUARIO/logivisir/backend/media` |

- **Force HTTPS:** activado.
- Presiona el botón verde **Reload**.

Abre `https://USUARIO.pythonanywhere.com` y entra con `owner_demo`.

## 6. Actualizar después de subir cambios a GitHub

```bash
cd ~/logivisir && git pull
cd backend && workon logivisir
python manage.py migrate
python manage.py collectstatic --noinput
```

Después presiona **Reload** en la pestaña **Web**.

Para dejar los datos de demostración como nuevos (por ejemplo, antes de la
presentación), usa `python manage.py seed_demo --reset`.

## Límites de la cuenta gratis

- **Vencimiento:** la pestaña **Web** muestra hasta qué fecha está activa la página. Antes de que venza, hay que entrar y presionar **Run until 3 months from today**.
- **Acceso a internet restringido:** la cuenta gratis solo puede conectarse a una lista de servicios permitidos.
  - Si el servicio de rutas OSRM no está en esa lista, el optimizador calcula con distancia en línea recta, como define el RNF04 del informe. El sistema sigue funcionando.
  - Los clientes demo ya traen coordenadas, así que no dependen de la geocodificación.
- **Correo:** sin `EMAIL_HOST_USER`, los avisos al chofer se escriben en el log del servidor en vez de enviarse. Eso basta para la demostración.
- **Errores:** si algo falla, el detalle está en **Web** → **Error log**.
