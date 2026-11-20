"""URLs for the static files with a version that changes with their content.

Without it a browser may keep an old route.js after a deploy: the URL is the
same, so it reuses its copy. With "route.js?v=<hash>" a changed file has a new
URL, and the browser has no old copy of it. StaticFiles ignores the query.
"""

import hashlib
from pathlib import Path

VERSION_LENGTH = 8


class StaticUrl:
    """static_url("style.css") -> "/static/style.css?v=3f9a1c2e".

    The hash is kept per (path, mtime): each call only checks the mtime, and
    the file is read again only when it changed, so a CSS edit shows up
    without restarting the server.
    """

    def __init__(self, directory: Path, prefix: str = "/static") -> None:
        self.directory = directory.resolve()
        self.prefix = prefix
        self._versions: dict[str, tuple[int, str]] = {}

    def __call__(self, path: str) -> str:
        file = (self.directory / path).resolve()
        # Paths come from our templates, but never hash a file outside static/
        if not file.is_relative_to(self.directory):
            raise ValueError(f"{path!r} is outside {self.directory}")
        # A typo in a template fails loudly instead of losing the version
        mtime = file.stat().st_mtime_ns
        cached = self._versions.get(path)
        if cached is None or cached[0] != mtime:
            digest = hashlib.sha256(file.read_bytes()).hexdigest()
            cached = (mtime, digest[:VERSION_LENGTH])
            self._versions[path] = cached
        return f"{self.prefix}/{path}?v={cached[1]}"
