// The map on the home page: where you are (or the address you searched),
// the stops near you, and the buses of the stop you opened.
// The list stays the main thing; the map only helps to see where things are.

const mapEl = document.getElementById("home-map");
const stopsEl = document.getElementById("stops");

const ME = "#1a73e8";
const BUS = "#facc15";
const VEHICLES_EVERY_MS = 30_000;

const EMPTY = { type: "FeatureCollection", features: [] };

let map = null;
let ready = false;
// What to draw once the map has loaded (the first stops usually come before)
let pending = null;
let selectedStop = null;
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
      style: "https://tiles.openfreemap.org/styles/positron",
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
      button.click();
      button.scrollIntoView({ behavior: "smooth", block: "nearest" });
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

// The stop whose arrivals are open: highlight it and follow its buses
function select(stopId) {
  selectedStop = stopId;
  clearTimeout(vehiclesTimer);
  for (const li of stopsEl.querySelectorAll("ul.stops > li.selected")) {
    li.classList.remove("selected");
  }
  if (!ready) return;
  map.setFilter("stop-selected", ["==", ["get", "stop_id"], stopId ?? ""]);
  map.getSource("vehicles").setData(EMPTY);
  if (stopId) refreshVehicles();
}

async function refreshVehicles() {
  const stopId = selectedStop;
  // A hidden tab doesn't need new positions; check again in the next round
  if (!document.hidden) {
    try {
      const response = await fetch(`/api/v1/stops/${encodeURIComponent(stopId)}/vehicles`);
      if (response.ok) {
        const data = await response.json();
        // Another stop may have been opened while this one was loading
        if (stopId !== selectedStop) return;
        map.getSource("vehicles").setData(data);
      } else {
        console.error("could not load the buses", response.status);
      }
    } catch (error) {
      console.error("could not load the buses", error);
    }
  }
  if (stopId === selectedStop) {
    vehiclesTimer = setTimeout(refreshVehicles, VEHICLES_EVERY_MS);
  }
}

// A new list of stops (location or address): draw it
document.body.addEventListener("htmx:afterSwap", (event) => {
  if (event.detail.target !== stopsEl) return;
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

// Opening a stop from the list (or from the map, which clicks the button)
stopsEl.addEventListener("click", (event) => {
  const li = event.target.closest("ul.stops > li[data-stop-id]");
  if (!li || !event.target.closest(".stop")) return;
  select(li.dataset.stopId);
  li.classList.add("selected");
});
