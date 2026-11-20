// The service worker: what comes from the cache and what from the network.
// Served at /sw.js (not /static/sw.js): it only controls the URLs under its
// own folder, and it has to control the pages.
//
// - Versioned static files (/static/x?v=<hash>): cache first. A versioned
//   URL never changes its content, so a cached copy is never stale.
// - Pages: always the network (arrivals are live); with no network, the
//   "Sin conexión" page saved on install.
// - Everything else (htmx partials, /api, map tiles, Nominatim): not
//   touched, it goes to the network as without a service worker. Tiles are
//   another site, and Range requests (Protomaps) can't go in the Cache API.

// Change it to drop every cache, for example if the offline page changes
const CACHE = "notibondi-v1";
const OFFLINE_URL = "/offline";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.add(new Request(OFFLINE_URL, { cache: "reload" }))),
  );
  // Don't wait for every tab to close to start using the new version
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n))),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/static/") && url.searchParams.has("v")) {
    event.respondWith(cacheFirst(request, url));
  } else if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(
        async () => (await caches.match(OFFLINE_URL)) ?? Response.error(),
      ),
    );
  }
});

async function cacheFirst(request, url) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    await cache.put(request, response.clone());
    await dropOtherVersions(cache, url);
  }
  return response;
}

// Every deploy brings new ?v= URLs: keep only the newest copy of each file
async function dropOtherVersions(cache, url) {
  for (const key of await cache.keys()) {
    const old = new URL(key.url);
    if (old.pathname === url.pathname && old.search !== url.search) {
      await cache.delete(key);
    }
  }
}
