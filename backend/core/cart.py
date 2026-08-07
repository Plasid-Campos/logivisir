"""
Carrito de compra en sesion (server-rendered, sin JS framework). Este es un
carrito que arma un ADMIN/OWNER para un Cliente ya elegido (Logivisir es una
plataforma B2B para que la pyme gestione sus pedidos, no una tienda pública
de autoservicio) — por eso el carrito siempre esta ligado a un cliente_id.
"""
from decimal import Decimal

from .models import Producto

SESSION_KEY = "carrito"


class Carrito:
    def __init__(self, request):
        self.request = request
        self.session = request.session
        datos = self.session.get(SESSION_KEY)
        if not datos or "cliente_id" not in datos:
            datos = {"cliente_id": None, "items": {}}
        self.datos = datos

    def _guardar(self):
        self.session[SESSION_KEY] = self.datos
        self.session.modified = True

    @property
    def cliente_id(self):
        return self.datos.get("cliente_id")

    def iniciar_para_cliente(self, cliente_id):
        """Empieza (o reinicia, si cambia de cliente) el carrito."""
        if self.datos.get("cliente_id") != cliente_id:
            self.datos = {"cliente_id": cliente_id, "items": {}}
            self._guardar()

    def agregar(self, producto_id, cantidad=1):
        items = self.datos["items"]
        clave = str(producto_id)
        items[clave] = items.get(clave, 0) + max(1, int(cantidad))
        self._guardar()

    def actualizar_cantidad(self, producto_id, cantidad):
        items = self.datos["items"]
        clave = str(producto_id)
        cantidad = int(cantidad)
        if cantidad <= 0:
            items.pop(clave, None)
        else:
            items[clave] = cantidad
        self._guardar()

    def quitar(self, producto_id):
        self.datos["items"].pop(str(producto_id), None)
        self._guardar()

    def vaciar(self):
        self.datos = {"cliente_id": None, "items": {}}
        self._guardar()

    def esta_vacio(self):
        return len(self.datos["items"]) == 0

    def items(self, empresa):
        """
        Resuelve los Producto reales (scopeados a la empresa) y devuelve una
        lista de dicts {producto, cantidad, subtotal}. Si un producto fue
        eliminado del catalogo despues de agregarse al carrito, se ignora.
        """
        ids = [int(pid) for pid in self.datos["items"].keys()]
        productos = Producto.objects.filter(id__in=ids, empresa=empresa)
        productos_por_id = {p.id: p for p in productos}

        resultado = []
        for pid_str, cantidad in self.datos["items"].items():
            producto = productos_por_id.get(int(pid_str))
            if not producto:
                continue
            subtotal = producto.precio * cantidad
            resultado.append({"producto": producto, "cantidad": cantidad, "subtotal": subtotal})
        return resultado

    def total(self, empresa):
        return sum((item["subtotal"] for item in self.items(empresa)), start=Decimal("0"))
