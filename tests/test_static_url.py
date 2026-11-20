import os
import re

import pytest
from fastapi.testclient import TestClient

from notibondi.main import BASE_DIR, app
from notibondi.static_url import VERSION_LENGTH, StaticUrl

client = TestClient(app)


@pytest.fixture
def static(tmp_path):
    (tmp_path / "app.js").write_text("console.log(1);")
    return tmp_path


def bump_mtime(path):
    # Two writes in the same instant may share an mtime: move it on by hand
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


def test_url_has_the_prefix_the_path_and_a_short_version(static):
    url = StaticUrl(static)("app.js")

    assert re.fullmatch(rf"/static/app\.js\?v=[0-9a-f]{{{VERSION_LENGTH}}}", url)


def test_same_content_gives_the_same_version(static):
    (static / "copy.js").write_text("console.log(1);")
    static_url = StaticUrl(static)

    assert static_url("app.js").split("?")[1] == static_url("copy.js").split("?")[1]


def test_changing_the_file_changes_its_url(static):
    static_url = StaticUrl(static)
    before = static_url("app.js")

    (static / "app.js").write_text("console.log(2);")
    bump_mtime(static / "app.js")

    assert static_url("app.js") != before


def test_touching_the_file_without_changing_it_keeps_its_url(static):
    # A git checkout or a Docker build changes the mtime, not the content
    static_url = StaticUrl(static)
    before = static_url("app.js")

    bump_mtime(static / "app.js")

    assert static_url("app.js") == before


def test_the_file_is_only_read_again_when_its_mtime_changes(static):
    static_url = StaticUrl(static)
    before = static_url("app.js")
    mtime = (static / "app.js").stat().st_mtime_ns

    # Same mtime, new content: the cached hash is kept, no read
    (static / "app.js").write_text("console.log(2);")
    os.utime(static / "app.js", ns=(mtime, mtime))

    assert static_url("app.js") == before


def test_files_in_subfolders_work(static):
    (static / "img").mkdir()
    (static / "img" / "bus.svg").write_text("<svg/>")

    assert StaticUrl(static)("img/bus.svg").startswith("/static/img/bus.svg?v=")


def test_a_missing_file_fails_loudly(static):
    with pytest.raises(FileNotFoundError):
        StaticUrl(static)("typo.js")


@pytest.mark.parametrize("path", ["../secret.txt", "/etc/passwd"])
def test_a_path_outside_the_folder_is_refused(static, path):
    (static.parent / "secret.txt").write_text("no")

    with pytest.raises(ValueError):
        StaticUrl(static)(path)


# The real pages


def test_pages_link_every_static_file_with_a_version():
    html = client.get("/stops").text
    links = re.findall(r'(?:src|href)="(/static/[^"]+)"', html)

    assert links
    for link in links:
        assert re.search(rf"\?v=[0-9a-f]{{{VERSION_LENGTH}}}$", link), link


def test_the_version_is_the_hash_of_the_real_file():
    html = client.get("/").text
    expected = StaticUrl(BASE_DIR / "static")("style.css")

    assert f'href="{expected}"' in html


def test_the_versioned_url_serves_the_file():
    url = StaticUrl(BASE_DIR / "static")("style.css")

    response = client.get(url)

    assert response.status_code == 200
    assert response.text == (BASE_DIR / "static" / "style.css").read_text()
