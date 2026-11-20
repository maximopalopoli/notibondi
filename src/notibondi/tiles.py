"""The map tiles: our own Protomaps file when there is one.

A .pmtiles file is the whole basemap of an area in one file. The browser
reads only the pieces it needs with HTTP Range requests, so the server just
serves it as a static file. It's cut from Protomaps' daily world build
with `make tiles` (about 75 MB). The box holds every stop of the GTFS, out
to the long lines that reach lon -61.

With no file in data/tiles, the maps use OpenFreeMap like before.
"""

from pathlib import Path

# Relative to the working directory, like data/gtfs.zip: outside git and the
# Docker image (in compose it's a volume)
TILES_DIR = Path("data/tiles")
TILES_PREFIX = "/tiles"


def newest_tiles(directory: Path) -> str | None:
    """The name of the newest .pmtiles file in the folder, or None.

    The newest, so dropping in a new cut is enough: the old one can be
    deleted later. The date in the name gives it a new URL, so a browser
    never mixes pieces of two cuts.
    """
    files = list(directory.glob("*.pmtiles")) if directory.is_dir() else []
    if not files:
        return None
    return max(files, key=lambda f: f.stat().st_mtime).name


class TilesUrl:
    """tiles_url() -> "/tiles/caba-2026-11.pmtiles", or None with no file.

    A template global, called on every page: a glob of one small folder.
    """

    def __init__(self, directory: Path, prefix: str = TILES_PREFIX) -> None:
        self.directory = directory
        self.prefix = prefix

    def __call__(self) -> str | None:
        name = newest_tiles(self.directory)
        return f"{self.prefix}/{name}" if name else None
