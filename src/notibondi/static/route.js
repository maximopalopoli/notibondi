// The map of the line page: one branch, drawn by route_layers.js
const el = document.getElementById("map");
const noLive = document.getElementById("no-live");
const unknownBranch = document.getElementById("unknown-branch");

const map = new maplibregl.Map({
  container: el,
  center: [-58.44, -34.61], // [lon, lat], only until the route is drawn
  zoom: 11,
  // A light grey vector style, so the route is the main thing on the map.
  // It brings its own attribution (basemap.js).
  style: Basemap.style(),
});

map.on("load", () => {
  RouteLayers.add(map);
  RouteLayers.show(
    map,
    { geojson: el.dataset.geojsonUrl, vehicles: el.dataset.vehiclesUrl },
    (data) => {
      noLive.hidden = data.features.length > 0;
      unknownBranch.hidden = data.features.every((f) => f.properties.branch_known);
    },
  );
});
