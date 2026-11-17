"""Download the static GTFS from the GCBA API.

It's the 2021 feed (/colectivos/feed-gtfs), which knows many more of the
stops in today's real-time feed than the public 2019 zip. It needs the same
credentials as the live feeds, so they come from Settings (.env) instead of
the command line, where they would end up in the shell history.
"""

import sys
import time
import zipfile
from pathlib import Path

import httpx2

from notibondi.config import get_settings
from notibondi.gcba import CONNECT_TIMEOUT

# The zip is ~210 MB. The read timeout is per chunk, not for the whole file,
# so a slow but steady download never hits it.
TIMEOUT = httpx2.Timeout(60, connect=CONNECT_TIMEOUT)


def download_gtfs(dest: Path) -> None:
    settings = get_settings()
    params = {
        "client_id": settings.gcba_client_id,
        "client_secret": settings.gcba_client_secret.get_secret_value(),
    }
    # Written next to the destination and renamed at the end, so a failed
    # download never replaces a good zip
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        with httpx2.stream(
            "GET",
            f"{settings.gcba_base_url}/colectivos/feed-gtfs",
            params=params,
            timeout=TIMEOUT,
        ) as resp:
            # Not raise_for_status(): its message has the URL, with the secret
            if resp.status_code != 200:
                sys.exit(f"unexpected status {resp.status_code}")
            with part.open("wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
    except httpx2.RequestError as e:
        # Only the type: the exception keeps the request, and so the secret
        part.unlink(missing_ok=True)
        sys.exit(f"download failed: {type(e).__name__}")

    if not zipfile.is_zipfile(part):
        part.unlink()
        sys.exit("the response is not a zip file")
    part.replace(dest)


if __name__ == "__main__":
    path = Path(sys.argv[1])

    start = time.perf_counter()
    download_gtfs(path)
    end = time.perf_counter()

    size_mb = path.stat().st_size / 1e6
    print(f"Downloaded {size_mb:.0f} MB to {path} in {end - start:.0f} seconds")
