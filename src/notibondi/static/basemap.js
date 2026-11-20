// The look of the three maps, in one place. When the server has a Protomaps
// file it says so in <meta name="basemap-tiles"> (base.html): the tiles then
// come from this server, read in pieces by pmtiles.js, with the "light" look
// of basemaps.js and the names in Spanish. Without it, OpenFreeMap like before.
//
// The fonts and icons of the style are ours too, in static/basemap/
// (scripts/download_basemap_assets.py).

const Basemap = (() => {
  const POSITRON = "https://tiles.openfreemap.org/styles/positron";
  // Absolute: MapLibre doesn't resolve relative glyph and sprite URLs
  const ASSETS = `${location.origin}/static/basemap`;
  let protocolAdded = false;

  // Quieter than "light": pale water and parks, grey place names, and few
  // place icons, so the blue and red of the buses are what stands out
  const QUIET = {
    water: "#c5dbe5",
    ocean_label: "#7b93a3",
    park_b: "#c4dccb",
    wood_b: "#c7dcc7",
    scrub_b: "#c6dccf",
  };
  const POI_GREY = "#7d8590";

  function flavor() {
    const light = basemaps.namedFlavor("light");
    const pois = Object.fromEntries(Object.keys(light.pois).map((k) => [k, POI_GREY]));
    return { ...light, ...QUIET, pois };
  }

  function layers() {
    const all = basemaps.layers("protomaps", flavor(), { lang: "es" });
    const pois = all.find((layer) => layer.id === "pois");
    // Train and subway stations always (where people change to the bus);
    // shops, cafés, schools... only at street zoom
    pois.filter = [
      "all",
      pois.filter,
      ["any", ["==", ["get", "kind"], "station"], [">=", ["zoom"], 16]],
    ];
    return all;
  }

  function style() {
    const meta = document.querySelector('meta[name="basemap-tiles"]');
    if (!meta) return POSITRON;
    if (!protocolAdded) {
      // "pmtiles://" URLs: each tile is a Range request to the one file
      maplibregl.addProtocol("pmtiles", new pmtiles.Protocol().tile);
      protocolAdded = true;
    }
    return {
      version: 8,
      glyphs: `${ASSETS}/fonts/{fontstack}/{range}.pbf`,
      sprite: `${ASSETS}/sprites/light`,
      sources: {
        protomaps: {
          type: "vector",
          url: `pmtiles://${new URL(meta.content, location.href)}`,
          attribution:
            '<a href="https://protomaps.com">Protomaps</a> © ' +
            '<a href="https://openstreetmap.org/copyright">OpenStreetMap</a>',
        },
      },
      layers: layers(),
    };
  }

  return { style };
})();
