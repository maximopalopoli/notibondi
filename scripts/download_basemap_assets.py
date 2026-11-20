"""Download the fonts and icons of the Protomaps "light" style into static/.

The tiles (data/tiles/*.pmtiles) only have the data; the style also needs
glyphs (the letters of the labels) and a sprite (the icons of parks,
stations, ...). They're small, so they live in git under static/basemap/
and the maps don't depend on protomaps.github.io.

Only the glyph ranges for Spanish names: Latin (0-1023) and punctuation
like – or “ (8192-8447). MapLibre asks for a range only when a label has a
letter in it; Chinese, Japanese and Korean it draws with the system font.

Usage: uv run python scripts/download_basemap_assets.py
"""

import urllib.request
from pathlib import Path

ASSETS = "https://protomaps.github.io/basemaps-assets"
OUT = Path(__file__).parents[1] / "src" / "notibondi" / "static" / "basemap"

# The fonts the "light" flavor of basemaps.js uses
FONTS = ["Noto Sans Regular", "Noto Sans Medium", "Noto Sans Italic"]
RANGES = ["0-255", "256-511", "512-767", "768-1023", "8192-8447"]
SPRITES = ["light.json", "light.png", "light@2x.json", "light@2x.png"]


def download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=30) as response:
        path.write_bytes(response.read())
    print(f"{path.relative_to(OUT)}  {path.stat().st_size:>8} B")


def main() -> None:
    for name in SPRITES:
        download(f"{ASSETS}/sprites/v4/{name}", OUT / "sprites" / name)
    for font in FONTS:
        for r in RANGES:
            url = f"{ASSETS}/fonts/{urllib.request.quote(font)}/{r}.pbf"
            download(url, OUT / "fonts" / font / f"{r}.pbf")


if __name__ == "__main__":
    main()
