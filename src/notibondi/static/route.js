const el = document.getElementById("map");

const map = new maplibregl.Map({
  container: el,
  center: [-58.44, -34.61], // [lon, lat], only until fitBounds runs
  zoom: 11,
  style: {
    version: 8,
    sources: {
      osm: {
        type: "raster",
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        tileSize: 256,
        attribution: "© OpenStreetMap contributors",
      },
    },
    layers: [{ id: "osm", type: "raster", source: "osm" }],
  },
});

// direction 0 is blue, direction 1 is red
const DIRECTION_COLOR = ["match", ["get", "direction_id"], 0, "#2563eb", "#dc2626"];

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

  map.addLayer({
    id: "stops",
    type: "circle",
    source: "route",
    filter: ["==", ["geometry-type"], "Point"],
    paint: {
      "circle-radius": 4,
      "circle-color": "#ffffff",
      "circle-stroke-color": DIRECTION_COLOR,
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
});
