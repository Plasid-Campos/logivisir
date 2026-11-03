/* Chat de ayuda guiado de LogiVisir: sin IA, con respuestas escritas por el equipo. */
(function () {
  "use strict";
  const datosEl = document.getElementById("lvc-datos");
  if (!datosEl) return;
  const datos = JSON.parse(datosEl.textContent);
  const temas = Object.fromEntries(datos.temas.map((t) => [t.id, t]));

  const ventana = document.getElementById("lvc-ventana");
  const lanzador = document.getElementById("lvc-abrir");
  const lista = document.getElementById("lvc-mensajes");
  const opciones = document.getElementById("lvc-opciones");
  const form = document.getElementById("lvc-form");
  const entrada = document.getElementById("lvc-texto");
  const reducido = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let iniciado = false;
  let ocupado = false;

  const normalizar = (t) => t.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  const esperar = (ms) => new Promise((r) => setTimeout(r, reducido ? 0 : ms));

  function burbuja(texto, quien) {
    const b = document.createElement("div");
    b.className = "lvc-burbuja lvc-" + quien;
    b.textContent = texto;
    lista.appendChild(b);
    lista.scrollTop = lista.scrollHeight;
    return b;
  }

  async function decir(mensajes) {
    ocupado = true;
    opciones.innerHTML = "";
    for (const m of mensajes) {
      const escribiendo = document.createElement("div");
      escribiendo.className = "lvc-burbuja lvc-bot lvc-escribiendo";
      escribiendo.innerHTML = "<span></span><span></span><span></span>";
      lista.appendChild(escribiendo);
      lista.scrollTop = lista.scrollHeight;
      await esperar(Math.min(1400, 350 + m.length * 9));
      escribiendo.remove();
      burbuja(m, "bot");
    }
    ocupado = false;
  }

  function chips(ids, extra) {
    opciones.innerHTML = "";
    if (extra) opciones.appendChild(extra);
    ids.filter((id) => temas[id]).forEach((id) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "lvc-chip";
      b.textContent = temas[id].boton;
      b.addEventListener("click", () => responder(id, temas[id].boton));
      opciones.appendChild(b);
    });
    const volver = document.createElement("button");
    volver.type = "button";
    volver.className = "lvc-chip lvc-chip-suave";
    volver.textContent = "Ver todos los temas";
    volver.addEventListener("click", () => chips(datos.temas.map((t) => t.id)));
    if (ids.length < datos.temas.length) opciones.appendChild(volver);
  }

  function enlace(texto, url, icono, externo) {
    const a = document.createElement("a");
    a.className = "lvc-accion";
    a.href = url;
    if (externo) { a.target = "_blank"; a.rel = "noopener"; }
    const i = document.createElement("i");
    i.className = "bi " + icono;
    a.append(i, " " + texto);
    return a;
  }

  function bloqueContacto() {
    const c = datos.contacto;
    const caja = document.createElement("div");
    caja.className = "lvc-acciones";
    if (c.whatsapp) caja.appendChild(enlace("Escribir por WhatsApp", "https://wa.me/" + c.whatsapp + "?text=" + encodeURIComponent("Hola, tengo una duda sobre LogiVisir"), "bi-whatsapp", true));
    if (c.email) caja.appendChild(enlace("Enviar un correo", "mailto:" + c.email, "bi-envelope"));
    caja.appendChild(enlace("Solicitar mi cuenta", c.solicitar, "bi-arrow-right-circle"));
    return caja;
  }

  async function responder(id, textoUsuario) {
    if (ocupado) return;
    const tema = temas[id];
    if (textoUsuario) burbuja(textoUsuario, "yo");
    await decir(tema.mensajes);
    let extra = null;
    if (tema.contacto) {
      extra = bloqueContacto();
      if (!datos.contacto.whatsapp && !datos.contacto.email) {
        await decir(["Por ahora la forma más directa es dejar tu consulta en «Solicita tu cuenta», en el campo de mensaje: no te compromete a pagar."]);
      }
    } else if (tema.accion) {
      extra = document.createElement("div");
      extra.className = "lvc-acciones";
      extra.appendChild(enlace(tema.accion.texto, tema.accion.url, "bi-arrow-right-circle"));
    }
    chips(tema.siguientes, extra);
  }

  function buscarTema(texto) {
    const t = normalizar(texto);
    let mejor = null;
    let puntaje = 0;
    datos.temas.forEach((tema) => {
      const p = tema.claves.reduce((s, k) => s + (t.includes(normalizar(k)) ? k.length : 0), 0);
      if (p > puntaje) { puntaje = p; mejor = tema.id; }
    });
    return mejor;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const texto = entrada.value.trim();
    if (!texto || ocupado) return;
    entrada.value = "";
    const id = buscarTema(texto);
    if (id) {
      responder(id, texto);
    } else {
      burbuja(texto, "yo");
      await decir(datos.no_entendi);
      chips(datos.inicio.concat(["humano"]));
    }
  });

  async function abrir() {
    ventana.hidden = false;
    lanzador.setAttribute("aria-expanded", "true");
    document.body.classList.add("lvc-abierto");
    if (!iniciado) {
      iniciado = true;
      await decir(datos.saludo);
      chips(datos.inicio);
    }
    if (window.matchMedia("(min-width: 768px)").matches) entrada.focus();
  }

  function cerrar() {
    ventana.hidden = true;
    lanzador.setAttribute("aria-expanded", "false");
    document.body.classList.remove("lvc-abierto");
    lanzador.focus();
  }

  lanzador.addEventListener("click", () => (ventana.hidden ? abrir() : cerrar()));
  document.getElementById("lvc-cerrar").addEventListener("click", cerrar);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !ventana.hidden) cerrar(); });
  document.querySelectorAll("[data-abrir-chat]").forEach((el) => el.addEventListener("click", (e) => { e.preventDefault(); abrir(); }));
})();
