// The map on the "Mapa de líneas" page. It starts on the city around you,
// or the Obelisco when the browser doesn't say where you are, and draws the
// branch you pick from the list (route_layers.js) without leaving the page.

const OBELISCO = [-58.3816, -34.6037]; // [lon, lat]
const ME = "#1a73e8";

const map = new maplibregl.Map({
  container: "lines-map",
  // Start at the Obelisco right away instead of waiting for the location,
  // which may take seconds or never come (Brave on a desktop)
  center: OBELISCO,
  zoom: 13,
  style: "https://tiles.openfreemap.org/styles/positron",
});

// Sources can only be added once the style has loaded. A promise, because
// the location may come before or after that
const loaded = new Promise((resolve) => map.once("load", resolve));
loaded.then(() => RouteLayers.add(map));

// Once the user moves the map, a late location must not take it away
let userMoved = false;
map.on("dragstart", () => (userMoved = true));
map.on("zoomstart", (event) => {
  // Only a zoom by the user has an originalEvent (wheel, pinch, buttons)
  if (event.originalEvent) userMoved = true;
});

function showMe(lon, lat) {
  const me = { type: "Feature", geometry: { type: "Point", coordinates: [lon, lat] } };
  map.addSource("me", { type: "geojson", data: me });
  map.addLayer({
    id: "me",
    type: "circle",
    source: "me",
    paint: {
      "circle-radius": 8,
      "circle-color": ME,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 3,
    },
  });
  if (!userMoved) map.jumpTo({ center: [lon, lat], zoom: 15 });
}

// No error message if it fails: the Obelisco is a fine answer, and this
// page isn't about where you are
navigator.geolocation?.getCurrentPosition(
  (position) => {
    const { longitude, latitude } = position.coords;
    loaded.then(() => showMe(longitude, latitude));
  },
  () => {},
  { timeout: 10000, maximumAge: 300000 },
);

// Picking a branch

const results = document.getElementById("search-results");
const noLive = document.getElementById("no-live");
const unknownBranch = document.getElementById("unknown-branch");

function showBranch(link) {
  for (const other of results.querySelectorAll("a[data-route-id]")) {
    other.toggleAttribute("aria-current", other === link);
  }
  // The route's zoom wins over a location that comes later
  userMoved = true;
  noLive.hidden = true;
  unknownBranch.hidden = true;
  const id = encodeURIComponent(link.dataset.routeId);
  loaded.then(() =>
    RouteLayers.show(
      map,
      { geojson: `/api/v1/routes/${id}/geojson`, vehicles: `/api/v1/routes/${id}/vehicles` },
      (data) => {
        noLive.hidden = data.features.length > 0;
        unknownBranch.hidden = data.features.every((f) => f.properties.branch_known);
      },
    ),
  );
  document.getElementById("lines-map").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

results.addEventListener("click", (event) => {
  const link = event.target.closest("a[data-route-id]");
  // A middle click or Ctrl+click still opens the line's own page
  if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;
  event.preventDefault();
  showBranch(link);
});

// A line with a single branch (like the 108) needs no second tap
document.body.addEventListener("htmx:afterSwap", (event) => {
  if (event.detail.target !== results) return;
  const links = results.querySelectorAll("a[data-route-id]");
  if (links.length === 1) showBranch(links[0]);
});
