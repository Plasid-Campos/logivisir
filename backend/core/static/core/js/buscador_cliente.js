/*
 * Buscador de clientes tipo "escribe y aparecen sugerencias" (sin librerias
 * externas). Pensado para reemplazar los <select> gigantes de 1000+
 * clientes, que son imposibles de usar para alguien que solo sabe el
 * nombre del cliente y no tiene paciencia para scrollear una lista enorme.
 *
 * Uso: initBuscadorCliente({
 *   inputId: "id del <input type=text> visible",
 *   hiddenId: "id del <input type=hidden> que realmente se envia en el form",
 *   dropdownId: "id del <div> vacio donde se pintan las sugerencias",
 *   dataId: "id del <script type=application/json> con la lista de clientes",
 *   submitSelector: "opcional, selector del boton submit a habilitar/deshabilitar",
 * });
 */
function normalizarTexto(txt) {
  return (txt || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, ""); // quita tildes/acentos
}

function initBuscadorCliente(config) {
  const input = document.getElementById(config.inputId);
  const hidden = document.getElementById(config.hiddenId);
  const dropdown = document.getElementById(config.dropdownId);
  const dataEl = document.getElementById(config.dataId);

  if (!input || !hidden || !dropdown || !dataEl) return;

  const clientes = JSON.parse(dataEl.textContent).map(function (c) {
    return {
      id: c.id,
      nombre: c.nombre,
      comuna: c.comuna || "",
      tipo: c.tipo_cliente || "NORMAL",
      buscable: normalizarTexto(c.nombre + " " + (c.comuna || "")),
    };
  });

  function actualizarSubmit() {
    // El selector puede apuntar a varios botones («Guardar y agregar otro» y «Guardar y armar ruta»).
    if (!config.submitSelector) return;
    document.querySelectorAll(config.submitSelector).forEach(function (b) { b.disabled = !hidden.value; });
  }

  function cerrarDropdown() {
    dropdown.innerHTML = "";
    dropdown.classList.remove("show");
  }

  function seleccionar(cliente) {
    hidden.value = cliente.id;
    input.value = cliente.comuna ? cliente.nombre + " (" + cliente.comuna + ")" : cliente.nombre;
    input.classList.add("is-valid");
    cerrarDropdown();
    actualizarSubmit();
  }

  function pintarResultados(resultados, termino) {
    dropdown.innerHTML = "";

    if (!termino) {
      cerrarDropdown();
      return;
    }

    if (resultados.length === 0) {
      const vacio = document.createElement("div");
      vacio.className = "buscador-cliente-empty";
      vacio.textContent = "No se encontraron clientes con ese nombre.";
      dropdown.appendChild(vacio);
      dropdown.classList.add("show");
      return;
    }

    resultados.slice(0, 12).forEach(function (c) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "buscador-cliente-item";
      // Con textContent, nunca innerHTML: los nombres pueden venir de una
      // planilla importada y no deben interpretarse como HTML.
      function span(clase, texto) {
        const s = document.createElement("span");
        s.className = clase;
        s.textContent = texto;
        return s;
      }
      item.appendChild(span("buscador-cliente-nombre", c.nombre));
      if (c.comuna) item.appendChild(span("buscador-cliente-comuna", c.comuna));
      item.appendChild(span(
        "buscador-cliente-badge " + (c.tipo === "DELIVERY" ? "delivery" : "regular"),
        c.tipo === "DELIVERY" ? "Delivery" : "Regular"
      ));
      item.addEventListener("click", function () {
        seleccionar(c);
      });
      dropdown.appendChild(item);
    });

    dropdown.classList.add("show");
  }

  input.addEventListener("input", function () {
    hidden.value = "";
    input.classList.remove("is-valid");
    actualizarSubmit();

    const termino = normalizarTexto(input.value.trim());
    if (!termino) {
      cerrarDropdown();
      return;
    }

    const resultados = clientes.filter(function (c) {
      return c.buscable.indexOf(termino) !== -1;
    });
    pintarResultados(resultados, termino);
  });

  input.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      cerrarDropdown();
    } else if (e.key === "Enter") {
      const primero = dropdown.querySelector(".buscador-cliente-item");
      if (primero && !hidden.value) {
        e.preventDefault();
        primero.click();
      }
    }
  });

  document.addEventListener("click", function (e) {
    if (e.target !== input && !dropdown.contains(e.target)) {
      cerrarDropdown();
    }
  });

  actualizarSubmit();
}
