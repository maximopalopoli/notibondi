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
      layers: basemaps.layers("protomaps", basemaps.namedFlavor("light"), {
        lang: "es",
      }),
    };
  }

  return { style };
})();
