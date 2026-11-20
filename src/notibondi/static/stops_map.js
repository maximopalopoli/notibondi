// The map on the stops page: where you are (or the address you searched),
// the stops near you, and the buses of the line you tapped under a stop.
// The list stays the main thing; the map only helps to see where things are.

const mapEl = document.getElementById("stops-map");
const stopsEl = document.getElementById("stops");

const ME = "#1a73e8";
const BUS = "#facc15";
// The path of the tapped line: dark, so it doesn't look like you (blue)
const PATH = "#374151";
const VEHICLES_EVERY_MS = 30_000;

const EMPTY = { type: "FeatureCollection", features: [] };

let map = null;
let ready = false;
// What to draw once the map has loaded (the first stops usually come before)
let pending = null;
let selectedStop = null;
// The line tapped under the open stop: only its buses go on the map
let selectedLine = null;
let vehiclesTimer = null;

function point(lon, lat, properties = {}) {
  return { type: "Feature", geometry: { type: "Point", coordinates: [lon, lat] }, properties };
}

// The stops list as GeoJSON, read from the data-* attributes of the partial
function readList() {
  const list = stopsEl.querySelector("ul.stops[data-origin-lat]");
  if (!list) return null;
  const origin = point(Number(list.dataset.originLon), Number(list.dataset.originLat));
  const stops = [...list.querySelectorAll(":scope > li[data-lat]")].map((li) =>
    point(Number(li.dataset.lon), Number(li.dataset.lat), {
      stop_id: li.dataset.stopId,
      name: li.querySelector("strong").textContent,
    }),
  );
  return { origin, stops };
}

function createMap() {
  mapEl.hidden = false;
  try {
    map = new maplibregl.Map({
      container: mapEl,
      center: [-58.44, -34.61],
      zoom: 15,
      style: Basemap.style(),
    });
  } catch (error) {
    // No WebGL, for example: the list works the same without the map
    console.error("could not create the map", error);
    mapEl.hidden = true;
    map = null;
    return;
  }

  map.on("load", () => {
    map.addSource("stops", { type: "geojson", data: EMPTY });
    map.addSource("origin", { type: "geojson", data: EMPTY });
    map.addSource("vehicles", { type: "geojson", data: EMPTY });
    map.addSource("path", { type: "geojson", data: EMPTY });

    // The tapped line's path, under everything, with arrows the way it goes
    map.addLayer({
      id: "path",
      type: "line",
      source: "path",
      layout: { "line-join": "round", "line-cap": "round" },
      paint: { "line-color": PATH, "line-width": 4, "line-opacity": 0.8 },
    });
    map.addImage("path-arrow", RouteLayers.arrowImage(PATH), { pixelRatio: 2 });
    map.addLayer({
      id: "path-arrows",
      type: "symbol",
      source: "path",
      layout: {
        "symbol-placement": "line",
        "symbol-spacing": 80,
        "icon-image": "path-arrow",
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
      },
    });

    map.addLayer({
      id: "stops",
      type: "circle",
      source: "stops",
      paint: {
        "circle-radius": 6,
        "circle-color": "#ffffff",
        "circle-stroke-color": "#374151",
        "circle-stroke-width": 2,
      },
    });
    // The open stop, bigger and blue, drawn over the others
    map.addLayer({
      id: "stop-selected",
      type: "circle",
      source: "stops",
      filter: ["==", ["get", "stop_id"], ""],
      paint: {
        "circle-radius": 9,
        "circle-color": "#ffffff",
        "circle-stroke-color": ME,
        "circle-stroke-width": 4,
      },
    });
    // The buses go faded when their branch is unknown, like on the line map
    map.addLayer({
      id: "vehicles",
      type: "circle",
      source: "vehicles",
      paint: {
        "circle-radius": 7,
        "circle-color": BUS,
        "circle-opacity": ["case", ["get", "branch_known"], 1, 0.45],
        "circle-stroke-color": "#000000",
        "circle-stroke-width": ["case", ["get", "branch_known"], 2, 1],
      },
    });
    // You on top of everything: a blue dot with a white border
    map.addLayer({
      id: "origin",
      type: "circle",
      source: "origin",
      paint: {
        "circle-radius": 8,
        "circle-color": ME,
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 3,
      },
    });

    // Tapping a stop on the map opens it in the list
    map.on("click", "stops", (event) => {
      const id = event.features[0].properties.stop_id;
      const button = stopsEl.querySelector(`li[data-stop-id="${CSS.escape(id)}"] > .stop`);
      if (!button) return;
      const li = button.closest("li");
      // Up to right under the map, instead of scrolling down to where it is
      pinToTop(li);
      // Already open: keep it open (a tap on the button would close it)
      if (button.getAttribute("aria-expanded") !== "true") button.click();
      li.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    // Tapping a bus says which line it is (the map has no labels)
    map.on("click", "vehicles", (event) => {
      const bus = event.features[0];
      const { line, branch_known } = bus.properties;
      new maplibregl.Popup({ closeButton: false })
        .setLngLat(bus.geometry.coordinates)
        .setText(branch_known ? `Línea ${line}` : `Línea ${line} (ramal desconocido)`)
        .addTo(map);
    });
    for (const layer of ["stops", "vehicles"]) {
      map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
    }

    ready = true;
    if (pending) draw(pending);
  });
}

// The stop opened from the map goes first in the list, under the map. Only
// one at a time: the one before goes back to its place, by distance.
let pinned = null;

function pinToTop(li) {
  if (pinned === li) return;
  unpin();
  li.parentElement.prepend(li);
  pinned = li;
}

function unpin() {
  if (!pinned) return;
  const li = pinned;
  pinned = null;
  // data-order is its place in the list as the server sent it
  const order = Number(li.dataset.order);
  const after = [...li.parentElement.children].find(
    (other) => other !== li && Number(other.dataset.order) > order,
  );
  li.parentElement.insertBefore(li, after ?? null);
}

function draw({ origin, stops }) {
  if (!ready) {
    pending = { origin, stops };
    return;
  }
  pending = null;
  map.getSource("origin").setData({ type: "FeatureCollection", features: [origin] });
  map.getSource("stops").setData({ type: "FeatureCollection", features: stops });
  select(null);

  const bounds = new maplibregl.LngLatBounds();
  bounds.extend(origin.geometry.coordinates);
  for (const stop of stops) bounds.extend(stop.geometry.coordinates);
  // maxZoom: with a single stop next to you, don't zoom into one building
  map.fitBounds(bounds, { padding: 40, maxZoom: 17, animate: false });
}

// The stop whose arrivals are open: highlight it. No buses until a line is tapped.
function select(stopId) {
  selectedStop = stopId;
  showLine(null);
  for (const li of stopsEl.querySelectorAll("ul.stops > li.selected")) {
    li.classList.remove("selected");
  }
  if (stopId) {
    stopsEl.querySelector(`li[data-stop-id="${CSS.escape(stopId)}"]`)?.classList.add("selected");
  }
  if (!ready) return;
  map.setFilter("stop-selected", ["==", ["get", "stop_id"], stopId ?? ""]);
}

// The buses of one line of the open stop, or none (null)
function showLine(line) {
  selectedLine = line;
  clearTimeout(vehiclesTimer);
  for (const button of stopsEl.querySelectorAll(".line[data-line]")) {
    const li = button.closest("li[data-stop-id]");
    const on = line !== null && li?.dataset.stopId === selectedStop && button.dataset.line === line;
    button.setAttribute("aria-pressed", String(on));
  }
  for (const note of stopsEl.querySelectorAll(".no-live-line")) note.remove();
  if (ready) {
    map.getSource("vehicles").setData(EMPTY);
    map.getSource("path").setData(EMPTY);
  }
  if (line !== null && ready) {
    loadPath();
    refreshVehicles(true);
  }
}

// The path doesn't move: once per tap, not every 30 s
async function loadPath() {
  const stopId = selectedStop;
  const line = selectedLine;
  try {
    const response = await fetch(
      `/api/v1/stops/${encodeURIComponent(stopId)}/lines/${encodeURIComponent(line)}/geojson`,
    );
    if (!response.ok) throw new Error(`status ${response.status}`);
    const data = await response.json();
    if (stopId === selectedStop && line === selectedLine) map.getSource("path").setData(data);
  } catch (error) {
    // The buses still show without it
    console.error("could not load the path", error);
  }
}

// "No live buses" under the lines, so an empty map doesn't look broken
function noLiveNote(line) {
  const lines = stopsEl.querySelector(`li[data-stop-id="${CSS.escape(selectedStop)}"] > .lines`);
  if (!lines) return;
  const note = document.createElement("p");
  note.className = "note no-live-line";
  note.textContent = `La ${line} no tiene colectivos en vivo ahora.`;
  lines.after(note);
}

// The stop and its nearest buses, so you see them coming without zooming out
function fitNearest(features) {
  const stop = map
    .getSource("stops")
    .serialize()
    .data.features.find((f) => f.properties.stop_id === selectedStop);
  if (!stop) return;
  const [lon, lat] = stop.geometry.coordinates;
  const far = (f) => (f.geometry.coordinates[0] - lon) ** 2 + (f.geometry.coordinates[1] - lat) ** 2;
  const bounds = new maplibregl.LngLatBounds();
  bounds.extend([lon, lat]);
  for (const f of [...features].sort((a, b) => far(a) - far(b)).slice(0, 3)) {
    bounds.extend(f.geometry.coordinates);
  }
  map.fitBounds(bounds, { padding: 50, maxZoom: 16 });
}

async function refreshVehicles(first = false) {
  const stopId = selectedStop;
  const line = selectedLine;
  const current = () => stopId === selectedStop && line === selectedLine;
  // A hidden tab doesn't need new positions; check again in the next round
  if (!document.hidden) {
    try {
      const response = await fetch(
        `/api/v1/stops/${encodeURIComponent(stopId)}/vehicles?line=${encodeURIComponent(line)}`,
      );
      if (response.ok) {
        const data = await response.json();
        // Another stop or line may have been tapped while this one was loading
        if (!current()) return;
        map.getSource("vehicles").setData(data);
        stopsEl.querySelector(".no-live-line")?.remove();
        if (data.features.length === 0) noLiveNote(line);
        else if (first) fitNearest(data.features);
      } else {
        console.error("could not load the buses", response.status);
      }
    } catch (error) {
      console.error("could not load the buses", error);
    }
  }
  if (current()) {
    vehiclesTimer = setTimeout(refreshVehicles, VEHICLES_EVERY_MS);
  }
}

// A new list of stops (location or address): draw it
document.body.addEventListener("htmx:afterSwap", (event) => {
  if (event.detail.target !== stopsEl) return;
  pinned = null;
  stopsEl.querySelectorAll("ul.stops > li").forEach((li, i) => (li.dataset.order = i));
  const found = readList();
  if (!found || found.stops.length === 0) {
    // An error or no stops nearby: an empty map adds nothing
    mapEl.hidden = true;
    select(null);
    return;
  }
  if (!map) {
    createMap();
  } else {
    mapEl.hidden = false;
    // It was hidden, so it doesn't know its size any more
    map.resize();
  }
  if (map) draw(found);
});

// Opening or closing a stop, from the list or the map (which clicks the
// button). ui.js sends the event.
stopsEl.addEventListener("stop-toggle", (event) => {
  const stopId = event.target.dataset.stopId;
  if (event.detail.open) select(stopId);
  // Closing another stop than the highlighted one changes nothing on the map
  else if (stopId === selectedStop) select(null);
  if (!event.detail.open && event.target === pinned) unpin();
});

// Tapping a line under a stop: its buses on the map; tapping it again hides them.
// The stop opens too, if it was closed, to see when they arrive.
stopsEl.addEventListener("click", (event) => {
  const button = event.target.closest(".line[data-line]");
  if (!button || !map) return;
  const li = button.closest("li[data-stop-id]");
  const stopButton = li.querySelector(":scope > .stop");
  // ui.js opens it right away and sends stop-toggle, which calls select()
  if (stopButton.getAttribute("aria-expanded") !== "true") stopButton.click();
  // Already open, but another stop was opened after it: this one again
  if (selectedStop !== li.dataset.stopId) select(li.dataset.stopId);
  const line = button.dataset.line;
  showLine(button.getAttribute("aria-pressed") === "true" ? null : line);
  if (selectedLine) mapEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
});
