import json
import os
import re

import pytest
from fastapi.testclient import TestClient

from notibondi.main import BASE_DIR, app, templates, tiles_files
from notibondi.tiles import TILES_PREFIX, TilesUrl, newest_tiles

STATIC = BASE_DIR / "static"
MAP_PAGES = ["/stops", "/routes", "/routes/1001"]

plain_client = TestClient(app)


@pytest.fixture
def tiles_dir(tmp_path, monkeypatch):
    """data/tiles is a temporary folder: /tiles serves it, pages point at it."""
    monkeypatch.setattr(tiles_files, "all_directories", [tmp_path])
    monkeypatch.setitem(templates.env.globals, "tiles_url", TilesUrl(tmp_path))
    return tmp_path


def touch(path, mtime):
    path.write_bytes(b"x")
    os.utime(path, (mtime, mtime))


# Which file


def test_no_tiles_without_the_folder(tmp_path):
    assert newest_tiles(tmp_path / "missing") is None


def test_no_tiles_in_an_empty_folder(tmp_path):
    (tmp_path / "gtfs.zip").write_bytes(b"x")

    assert newest_tiles(tmp_path) is None


def test_the_newest_file_wins(tmp_path):
    # By date, not by name: an AMBA cut replaces the CABA one
    touch(tmp_path / "caba-2026-11.pmtiles", 1_000)
    touch(tmp_path / "amba-2026-12.pmtiles", 2_000)

    assert newest_tiles(tmp_path) == "amba-2026-12.pmtiles"


def test_tiles_url_is_under_its_own_prefix(tmp_path):
    touch(tmp_path / "caba-2026-11.pmtiles", 1_000)

    assert TilesUrl(tmp_path)() == "/tiles/caba-2026-11.pmtiles"


# Serving the file


def test_tiles_answer_a_range_request_with_only_that_part(tiles_dir):
    (tiles_dir / "caba.pmtiles").write_bytes(bytes(range(256)) * 4)

    response = plain_client.get("/tiles/caba.pmtiles", headers={"Range": "bytes=0-126"})

    # pmtiles.js reads the header first: the first 127 bytes
    assert response.status_code == 206
    assert response.content == bytes(range(127))
    assert response.headers["content-range"] == "bytes 0-126/1024"


def test_tiles_are_404_without_the_file(tiles_dir):
    assert plain_client.get("/tiles/caba.pmtiles").status_code == 404


def test_tiles_are_404_without_the_folder(tmp_path, monkeypatch):
    # A fresh clone: data/ is in .gitignore, so data/tiles isn't there
    monkeypatch.setattr(tiles_files, "directory", tmp_path / "missing")
    monkeypatch.setattr(tiles_files, "all_directories", [tmp_path / "missing"])

    assert plain_client.get("/tiles/caba.pmtiles").status_code == 404


def test_tiles_never_serve_other_files_of_data():
    # The mount is data/tiles, not data/: gtfs.zip stays private
    assert plain_client.get("/tiles/../gtfs.zip").status_code == 404


def test_service_worker_leaves_the_tiles_alone():
    # It caches /static/ only, and the Cache API refuses 206 answers
    sw = (STATIC / "sw.js").read_text()

    assert 'url.pathname.startsWith("/static/")' in sw
    assert not TILES_PREFIX.startswith("/static")


# The pages


def test_pages_point_at_the_tiles_when_there_is_a_file(tiles_dir):
    touch(tiles_dir / "caba-2026-11.pmtiles", 1_000)

    html = plain_client.get("/").text

    assert '<meta name="basemap-tiles" content="/tiles/caba-2026-11.pmtiles">' in html


def test_pages_have_no_tiles_meta_without_a_file(tiles_dir):
    # basemap.js then uses OpenFreeMap
    assert "basemap-tiles" not in plain_client.get("/").text


@pytest.mark.parametrize("page", MAP_PAGES)
def test_map_pages_load_the_basemap_before_their_map(client, page):
    # All deferred, so they run in this order: basemap.js needs the three
    # libraries, and the page's map script calls Basemap.style()
    html = client.get(page).text
    order = ["maplibre-gl.js", "pmtiles.js", "basemaps.js", "basemap.js"]
    positions = [html.index(f"/static/{name}?v=") for name in order]
    [page_script] = re.findall(r"/static/(lines_map|stops_map|route)\.js\?v=", html)

    assert positions == sorted(positions)
    assert positions[-1] < html.index(f"/static/{page_script}.js?v=")


@pytest.mark.parametrize("script", ["lines_map.js", "stops_map.js", "route.js"])
def test_every_map_takes_its_style_from_basemap_js(script):
    js = (STATIC / script).read_text()

    assert "style: Basemap.style()" in js
    assert "openfreemap" not in js


# The fonts and icons of the style


def test_basemap_takes_fonts_and_icons_from_this_server():
    js = (STATIC / "basemap.js").read_text()

    assert "protomaps.github.io" not in js
    assert "/static/basemap" in js


@pytest.mark.parametrize(
    "font",
    sorted(set(re.findall(r'"(Noto Sans \w+)"', (STATIC / "basemaps.js").read_text()))),
)
def test_every_font_of_the_style_has_its_latin_letters(font):
    # Without them the street names don't show
    for r in ["0-255", "256-511"]:
        assert (STATIC / "basemap" / "fonts" / font / f"{r}.pbf").stat().st_size > 0


@pytest.mark.parametrize("name", ["light", "light@2x"])
def test_the_style_icons_exist(name):
    sprites = STATIC / "basemap" / "sprites"

    assert json.loads((sprites / f"{name}.json").read_text())
    assert (sprites / f"{name}.png").read_bytes().startswith(b"\x89PNG")


def test_glyphs_are_served_from_a_folder_with_spaces(client):
    # MapLibre asks for "Noto%20Sans%20Regular/0-255.pbf"
    response = client.get("/static/basemap/fonts/Noto%20Sans%20Regular/0-255.pbf")

    assert response.status_code == 200
