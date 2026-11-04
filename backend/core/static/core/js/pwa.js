// LogiVisir como app instalable: registra el service worker y maneja la
// tarjeta «Instala LogiVisir en tu teléfono» ([data-instalar-app]).
(function () {
  "use strict";

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {});
    });
  }

  var CLAVE_OCULTA = "lv_instalar_oculto";
  var aviso = null; // evento beforeinstallprompt guardado (Android / Chrome / Edge)

  function instalada() {
    return (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
      window.navigator.standalone === true;
  }

  function esIphone() {
    return /iphone|ipad|ipod/i.test(navigator.userAgent) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  }

  function oculta() {
    try { return localStorage.getItem(CLAVE_OCULTA) === "1"; } catch (e) { return false; }
  }

  function tarjetas() {
    return Array.prototype.slice.call(document.querySelectorAll("[data-instalar-app]"));
  }

  function mostrar(modo) {
    if (instalada() || oculta()) return;
    tarjetas().forEach(function (t) {
      t.hidden = false;
      t.querySelectorAll("[data-modo]").forEach(function (el) {
        el.hidden = el.getAttribute("data-modo") !== modo;
      });
    });
  }

  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    aviso = e;
    mostrar("boton");
  });

  window.addEventListener("appinstalled", function () {
    tarjetas().forEach(function (t) { t.hidden = true; });
  });

  document.addEventListener("click", function (e) {
    var instalar = e.target.closest("[data-instalar-boton]");
    if (instalar && aviso) {
      aviso.prompt();
      aviso.userChoice.finally(function () { aviso = null; });
      return;
    }
    var cerrar = e.target.closest("[data-instalar-cerrar]");
    if (cerrar) {
      try { localStorage.setItem(CLAVE_OCULTA, "1"); } catch (err) {}
      tarjetas().forEach(function (t) { t.hidden = true; });
    }
  });

  document.addEventListener("DOMContentLoaded", function () {
    // Safari en iPhone no avisa que se puede instalar: se explican los pasos.
    if (esIphone()) mostrar("iphone");
  });
})();
