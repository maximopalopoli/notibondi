// One branch on a MapLibre map: its shape (blue one way, red the other,
// with arrows the way the bus goes), its stops and its buses, refreshed
// every 30 s. The line page and the "Mapa de líneas" map both use it.
// Only one branch at a time: showing another one replaces it.
//
// Under the map, the legend of the two directions, which is also a filter:
// "Ambos", or only one of them.

const RouteLayers = (() => {
  // direction 0 is blue, direction 1 is red
  const BLUE = "#2563eb";
  const RED = "#dc2626";
  const DIRECTION_COLOR = ["match", ["get", "direction_id"], 0, BLUE, RED];
  const EMPTY = { type: "FeatureCollection", features: [] };
  const REFRESH_MS = 30_000;

  // Each direction a few pixels to the right of the way it goes, like the
  // traffic: where both share a street they go side by side instead of the
  // red covering the blue. More at street zoom, where there's room.
  const OFFSET = ["interpolate", ["linear"], ["zoom"], 11, 1, 16, 4];
  // The arrows go with their line. An icon offset is along the icon: y is
  // to the right of the arrow, which points the way the bus goes.
  const ARROW_OFFSET = ["interpolate", ["linear"], ["zoom"], 11, ["literal", [0, 1]], 16, ["literal", [0, 4]]];

  const IS_LINE = ["==", ["geometry-type"], "LineString"];
  const IS_STOP = ["==", ["geometry-type"], "Point"];
  // Each layer's filter with both directions; showDirection() adds one
  const BASE_FILTERS = {
    "lines-casing": IS_LINE,
    lines: IS_LINE,
    arrows: IS_LINE,
    "route-stops": IS_STOP,
    "vehicles-unknown-branch": ["!", ["get", "branch_known"]],
    vehicles: ["get", "branch_known"],
  };

  // The arrows are drawn here instead of loading an image file. They point
  // right: on a "line" symbol, right means "forward along the line", and the
  // shapes go the way the bus goes.
  function arrowImage(color) {
    const size = 28; // 14 px on the screen, drawn at 2x so it looks sharp
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext("2d");

    ctx.beginPath();
    ctx.moveTo(size * 0.2, size * 0.15);
    ctx.lineTo(size * 0.85, size * 0.5);
    ctx.lineTo(size * 0.2, size * 0.85);
    ctx.lineTo(size * 0.4, size * 0.5);
    ctx.closePath();

    // the white border first, then the color on top, so the arrow reads on
    // the line and on the grey map
    ctx.lineJoin = "round";
    ctx.lineWidth = 5;
    ctx.strokeStyle = "#ffffff";
    ctx.stroke();
    ctx.fillStyle = color;
    ctx.fill();

    return ctx.getImageData(0, 0, size, size);
  }

  // Once, after the map's "load": empty sources and their layers
  function add(map) {
    map.addSource("route", { type: "geojson", data: EMPTY });
    map.addSource("vehicles", { type: "geojson", data: EMPTY });

    // A white border under both lines, so they stand out from the streets.
    // One layer for both, under the two lines: the border of one never
    // covers the other line
    const rounded = { "line-join": "round", "line-cap": "round" };
    map.addLayer({
      id: "lines-casing",
      type: "line",
      source: "route",
      filter: BASE_FILTERS["lines-casing"],
      layout: rounded,
      paint: { "line-color": "#ffffff", "line-width": 7, "line-offset": OFFSET },
    });
    map.addLayer({
      id: "lines",
      type: "line",
      source: "route",
      filter: BASE_FILTERS.lines,
      layout: rounded,
      paint: { "line-color": DIRECTION_COLOR, "line-width": 4, "line-offset": OFFSET },
    });

    map.addImage("arrow-0", arrowImage(BLUE), { pixelRatio: 2 });
    map.addImage("arrow-1", arrowImage(RED), { pixelRatio: 2 });

    // after the lines and before the stops, so stops and buses stay on top
    map.addLayer({
      id: "arrows",
      type: "symbol",
      source: "route",
      filter: BASE_FILTERS.arrows,
      layout: {
        "symbol-placement": "line",
        "symbol-spacing": 80, // pixels between two arrows
        "icon-image": ["match", ["get", "direction_id"], 0, "arrow-0", "arrow-1"],
        "icon-offset": ARROW_OFFSET,
        "icon-allow-overlap": true,
        // don't hide the street names of the base map
        "icon-ignore-placement": true,
      },
    });

    map.addLayer({
      id: "route-stops",
      type: "circle",
      source: "route",
      minzoom: 13,
      filter: BASE_FILTERS["route-stops"],
      paint: {
        "circle-radius": 4,
        "circle-color": "#ffffff",
        "circle-stroke-color": DIRECTION_COLOR,
        "circle-stroke-width": 2,
      },
    });

    // Buses of this line number whose branch we don't know: faded and under
    // the others, since they may belong to another branch
    map.addLayer({
      id: "vehicles-unknown-branch",
      type: "circle",
      source: "vehicles",
      filter: BASE_FILTERS["vehicles-unknown-branch"],
      paint: {
        "circle-radius": 6,
        "circle-color": DIRECTION_COLOR,
        "circle-opacity": 0.35,
        "circle-stroke-color": "#6b7280",
        "circle-stroke-width": 1.5,
      },
    });
    map.addLayer({
      id: "vehicles",
      type: "circle",
      source: "vehicles",
      filter: BASE_FILTERS.vehicles,
      paint: {
        "circle-radius": 7,
        "circle-color": DIRECTION_COLOR,
        "circle-stroke-color": "#000000",
        "circle-stroke-width": 2,
      },
    });

    legend = document.createElement("div");
    legend.className = "directions";
    legend.setAttribute("role", "group");
    legend.setAttribute("aria-label", "Sentidos");
    legend.hidden = true;
    legend.addEventListener("click", (event) => {
      const button = event.target.closest("button");
      if (button) pick(map, button);
    });
    map.getContainer().after(legend);
  }

  // The legend under the map (see add)
  let legend = null;

  // [[direction_id, headsign], ...] of the branch, one per direction
  function directionsOf(data) {
    const seen = new Map();
    for (const f of data.features) {
      if (f.geometry.type !== "LineString") continue;
      const { direction_id: id, trip_headsign: headsign } = f.properties;
      if (!seen.has(id)) seen.set(id, headsign);
    }
    return [...seen].sort((a, b) => a[0] - b[0]);
  }

  function button(label, direction, pressed) {
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.direction = direction;
    b.setAttribute("aria-pressed", pressed);
    if (direction !== "all") {
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = direction === "0" ? BLUE : RED;
      b.append(swatch);
    }
    // A text node, never markup: the headsign comes from the GTFS
    b.append(document.createTextNode(label));
    return b;
  }

  // "a Liniers" -> "A Liniers"; no headsign -> "Ida" / "Vuelta"
  function label(direction, headsign) {
    if (!headsign) return direction === 0 ? "Ida" : "Vuelta";
    return headsign[0].toUpperCase() + headsign.slice(1);
  }

  // A new branch: its directions, and both shown again
  function showLegend(map, data) {
    showDirection(map, null);
    const directions = directionsOf(data);
    // With one direction there's nothing to pick nor to tell apart
    legend.hidden = directions.length < 2;
    legend.replaceChildren(
      button("Ambos", "all", true),
      ...directions.map(([id, headsign]) => button(label(id, headsign), String(id), false)),
    );
  }

  function pick(map, picked) {
    for (const b of legend.querySelectorAll("button")) {
      b.setAttribute("aria-pressed", b === picked);
    }
    const d = picked.dataset.direction;
    showDirection(map, d === "all" ? null : Number(d));
  }

  // null: both directions
  function showDirection(map, direction) {
    for (const [id, base] of Object.entries(BASE_FILTERS)) {
      const only = ["==", ["get", "direction_id"], direction];
      map.setFilter(id, direction === null ? base : ["all", base, only]);
    }
  }

  // Each show() gets a number. An answer for an older one (the user already
  // picked another branch) is thrown away, and its refresh loop stops.
  let latest = 0;
  let timer = null;

  // urls: {geojson, vehicles}. onVehicles(data) runs after each refresh, so
  // the page can say "no live data".
  async function show(map, urls, onVehicles = () => {}) {
    const call = ++latest;
    clearTimeout(timer);
    map.getSource("vehicles").setData(EMPTY);

    let data;
    try {
      const response = await fetch(urls.geojson);
      if (!response.ok) throw new Error(`status ${response.status}`);
      data = await response.json();
    } catch (error) {
      console.error("could not load the route", error);
      return;
    }
    if (call !== latest) return;

    map.getSource("route").setData(data);
    showLegend(map, data);
    fit(map, data);
    refresh(map, urls.vehicles, call, onVehicles);
  }

  // zoom to the whole route
  function fit(map, data) {
    const lines = data.features.filter((f) => f.geometry.type === "LineString");
    if (lines.length === 0) return;
    const bounds = new maplibregl.LngLatBounds();
    for (const line of lines) {
      for (const point of line.geometry.coordinates) bounds.extend(point);
    }
    map.fitBounds(bounds, { padding: 40 });
  }

  async function refresh(map, url, call, onVehicles) {
    // a hidden tab doesn't need new positions; check again in the next round
    if (!document.hidden) {
      try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`status ${response.status}`);
        const data = await response.json();
        if (call !== latest) return;
        map.getSource("vehicles").setData(data);
        onVehicles(data);
      } catch (error) {
        console.error("could not load the buses", error);
      }
    }
    if (call === latest) timer = setTimeout(() => refresh(map, url, call, onVehicles), REFRESH_MS);
  }

  // arrowImage too: the stops map draws its own path with the same arrows
  return { add, show, arrowImage };
})();
