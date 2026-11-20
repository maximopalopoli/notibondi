import json
import re
import struct

import pytest
from fastapi.testclient import TestClient

from notibondi.main import BASE_DIR, app

client = TestClient(app)
STATIC = BASE_DIR / "static"


@pytest.fixture
def db_client(client):
    """The conftest client, with the database: /routes lists the lines."""
    return client


def manifest() -> dict:
    return json.loads((STATIC / "manifest.webmanifest").read_text())


def png_size(path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n"), path
    return struct.unpack(">II", data[16:24])


# The manifest


def test_manifest_has_what_chrome_needs_to_install_the_app():
    m = manifest()

    assert m["name"] and m["short_name"]
    assert m["start_url"] == "/"
    assert m["display"] == "standalone"
    sizes = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= sizes


def test_manifest_has_a_maskable_icon_for_android():
    assert any(i.get("purpose") == "maskable" for i in manifest()["icons"])


def test_manifest_theme_color_matches_the_pages():
    html = client.get("/").text

    assert f'<meta name="theme-color" content="{manifest()["theme_color"]}">' in html


@pytest.mark.parametrize("icon", manifest()["icons"], ids=lambda i: i["src"])
def test_every_manifest_icon_exists_with_its_size(icon):
    path = STATIC / icon["src"].removeprefix("/static/")
    width, height = png_size(path)

    assert f"{width}x{height}" == icon["sizes"]


def test_manifest_is_served_as_a_manifest():
    html = client.get("/").text
    [href] = re.findall(r'<link rel="manifest" href="([^"]+)"', html)

    response = client.get(href)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")


@pytest.mark.parametrize("page", ["/", "/stops", "/routes", "/favorites"])
def test_every_page_links_the_manifest_and_the_icons(db_client, page):
    html = db_client.get(page).text

    assert 'rel="manifest"' in html
    assert re.search(r'rel="apple-touch-icon" href="/static/icon-180\.png\?v=', html)
    assert png_size(STATIC / "icon-180.png") == (180, 180)


# The service worker


def test_service_worker_is_served_at_the_root():
    # Under /static/ it would only control /static/, not the pages
    response = client.get("/sw.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.text == (STATIC / "sw.js").read_text()


def test_service_worker_is_never_cached_blindly():
    # So a new version reaches the phones: the browser always asks
    assert client.get("/sw.js").headers["cache-control"] == "no-cache"


def test_service_worker_is_registered_at_its_unversioned_url():
    assert 'register("/sw.js")' in (STATIC / "ui.js").read_text()


def test_service_worker_saves_the_offline_page_that_exists():
    sw = (STATIC / "sw.js").read_text()
    [url] = re.findall(r'OFFLINE_URL = "([^"]+)"', sw)

    assert client.get(url).status_code == 200


# The offline page


def test_offline_page_says_there_is_no_connection():
    response = client.get("/offline")

    assert response.status_code == 200
    assert "Sin conexión" in response.text
    assert response.headers["cache-control"] == "no-cache"


def test_offline_page_needs_no_other_file():
    # Only the page is saved: a stylesheet or script would be missing offline
    html = client.get("/offline").text

    assert "/static/" not in html
    assert "<script" not in html
