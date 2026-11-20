// One branch on a MapLibre map: its shape (blue one way, red the other,
// with arrows the way the bus goes), its stops and its buses, refreshed
// every 30 s. The line page and the "Mapa de líneas" map both use it.
// Only one branch at a time: showing another one replaces it.

const RouteLayers = (() => {
  // direction 0 is blue, direction 1 is red
  const BLUE = "#2563eb";
  const RED = "#dc2626";
  const DIRECTION_COLOR = ["match", ["get", "direction_id"], 0, BLUE, RED];
  const EMPTY = { type: "FeatureCollection", features: [] };
  const REFRESH_MS = 30_000;

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

    map.addLayer({
      id: "lines",
      type: "line",
      source: "route",
      filter: ["==", ["geometry-type"], "LineString"],
      paint: { "line-color": DIRECTION_COLOR, "line-width": 4 },
    });

    map.addImage("arrow-0", arrowImage(BLUE), { pixelRatio: 2 });
    map.addImage("arrow-1", arrowImage(RED), { pixelRatio: 2 });

    // after the lines and before the stops, so stops and buses stay on top
    map.addLayer({
      id: "arrows",
      type: "symbol",
      source: "route",
      filter: ["==", ["geometry-type"], "LineString"],
      layout: {
        "symbol-placement": "line",
        "symbol-spacing": 80, // pixels between two arrows
        "icon-image": ["match", ["get", "direction_id"], 0, "arrow-0", "arrow-1"],
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
      filter: ["==", ["geometry-type"], "Point"],
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
      filter: ["!", ["get", "branch_known"]],
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
      filter: ["get", "branch_known"],
      paint: {
        "circle-radius": 7,
        "circle-color": DIRECTION_COLOR,
        "circle-stroke-color": "#000000",
        "circle-stroke-width": 2,
      },
    });
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
