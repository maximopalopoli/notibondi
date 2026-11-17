const el = document.getElementById("map");

const map = new maplibregl.Map({
  container: el,
  center: [-58.44, -34.61], // [lon, lat], only until fitBounds runs
  zoom: 11,
  // A light grey vector style, so the route is the main thing on the map.
  // It brings its own attribution (OpenFreeMap and OpenStreetMap).
  style: "https://tiles.openfreemap.org/styles/positron",
});

// direction 0 is blue, direction 1 is red
const BLUE = "#2563eb";
const RED = "#dc2626";
const DIRECTION_COLOR = ["match", ["get", "direction_id"], 0, BLUE, RED];

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

map.on("load", async () => {
  const response = await fetch(el.dataset.geojsonUrl);
  if (!response.ok) {
    console.error("could not load the route", response.status);
    return;
  }
  const data = await response.json();

  map.addSource("route", { type: "geojson", data });

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
    id: "stops",
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

  map.addSource("vehicles", {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  map.addLayer({
    id: "vehicles",
    type: "circle",
    source: "vehicles",
    paint: {
      "circle-radius": 7,
      "circle-color": DIRECTION_COLOR,
      "circle-stroke-color": "#000000",
      "circle-stroke-width": 2,
    },
  });

  // zoom to the whole route
  const lines = data.features.filter((f) => f.geometry.type === "LineString");
  if (lines.length > 0) {
    const bounds = new maplibregl.LngLatBounds();
    for (const line of lines) {
      for (const point of line.geometry.coordinates) {
        bounds.extend(point);
      }
    }
    map.fitBounds(bounds, { padding: 40 });
  }

  // only now the "vehicles" source exists, so the first round can draw
  refreshVehicles();
});

async function refreshVehicles() {
  // a hidden tab doesn't need new positions; check again in the next round
  if (document.hidden) {
    setTimeout(refreshVehicles, 30_000);
    return;
  }
  try {
    const response = await fetch(el.dataset.vehiclesUrl);
    if (response.ok) {
      map.getSource("vehicles").setData(await response.json());
    } else {
      console.error("could not load the buses", response.status);
    }
  } catch (error) {
    console.error("could not load the buses", error);
  }
  setTimeout(refreshVehicles, 30_000);
}
