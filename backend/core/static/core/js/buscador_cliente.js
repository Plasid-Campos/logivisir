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

  // Se busca en cada llamada (no se cachea): el boton submit puede estar
  // mas abajo en el HTML y todavia no existir cuando este script corre.
  function getSubmitBtn() {
    return config.submitSelector ? document.querySelector(config.submitSelector) : null;
  }

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
    const submitBtn = getSubmitBtn();
    if (submitBtn) submitBtn.disabled = !hidden.value;
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
      item.innerHTML =
        '<span class="buscador-cliente-nombre">' + c.nombre + "</span>" +
        (c.comuna ? '<span class="buscador-cliente-comuna">' + c.comuna + "</span>" : "") +
        '<span class="buscador-cliente-badge ' + (c.tipo === "DELIVERY" ? "delivery" : "regular") + '">' +
        (c.tipo === "DELIVERY" ? "Delivery" : "Regular") + "</span>";
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
