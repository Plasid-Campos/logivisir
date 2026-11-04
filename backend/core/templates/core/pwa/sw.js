// Service worker de LogiVisir: solo da una página «sin conexión».
// No guarda páginas con datos (rutas, clientes): siempre se piden al servidor.
const CACHE = "{{ version }}";
const OFFLINE = "/offline/";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll([OFFLINE, "{{ icono }}"])));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((claves) => Promise.all(claves.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE)));
});
