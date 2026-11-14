const el = document.getElementById("map");
const map = new maplibregl.Map({
  container: el,
  center: [-58.44, -34.61],   // [lon, lat] again!
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

map.on("load", async () => {
  const data = await (await fetch(el.dataset.geojsonUrl)).json();
  map.addSource("route", { type: "geojson", data });

  map.addLayer({
    id: "lines",
    type: "line",
    source: "route",
    filter: ["==", ["geometry-type"], "LineString"],
    paint: {
      "line-color": ["match", ["get", "direction_id"], 0, "#2563eb", "#dc2626"],
      "line-width": 4,
    },
  });

  // a second layer, type "circle", with the filter for "Point"…
});
