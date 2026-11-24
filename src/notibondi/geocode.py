"""Addresses to coordinates, with Nominatim (OpenStreetMap).

Its usage policy (https://operations.osmfoundation.org/policies/nominatim/):
an identifying User-Agent, at most 1 request per second, cache the results,
and no searching while the user types. The last one is up to the page, which
only searches on Enter.
"""

import asyncio
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable

import httpx2
from pydantic import BaseModel

from notibondi.config import Settings

# Street names repeat across the AMBA ("Corrientes 1500" is also in Quilmes,
# Olivos and Ezeiza; "Cabildo 2000" in Moreno) and most searches mean the
# city, so CABA goes first and the whole AMBA is the fallback.
# Viewboxes are the longitude and latitude of two corners.
CABA_VIEWBOX = "-58.54,-34.71,-58.33,-34.52"
# The box is a rectangle and its corners reach the province (Aldo Bonzi,
# Avellaneda), so a result counts as CABA only by its state. Nominatim may
# rank one of those first: on 2026-11-19 "corrientes 1500" gave Aldo Bonzi
# first and Avenida Corrientes second, so ask for a few.
CABA_STATE = "Ciudad Autónoma de Buenos Aires"
CABA_LIMIT = 5
# From Campana–Cañuelas to the river
AMBA_VIEWBOX = "-59.3,-35.2,-57.8,-34.2"
MIN_INTERVAL_S = 1.0
TIMEOUT = httpx2.Timeout(8, connect=5)
# A person searches the same 2 or 3 addresses; this only stops it growing forever
MAX_CACHED = 500
# Searches going to Nominatim at once, the one asking plus the ones in line.
# At one per second the last one waits ~5 s; more than that, a bot is
# flooding it, and in line they'd only hold requests open
MAX_PENDING = 5


class GeocodeError(Exception):
    """Any failure asking Nominatim: network, bad status or bad body."""


class GeocodeBusy(GeocodeError):
    """Too many searches already waiting for Nominatim: try again later."""


class Place(BaseModel):
    lat: float
    lon: float
    label: str  # short, for "Paradas cerca de …"


def normalize(q: str) -> str:
    """The cache key: "  Triunvirato   3424 " and "triunvirato 3424" are one search."""
    return re.sub(r"\s+", " ", q).strip().lower()


def short_label(result: dict) -> str:
    """ "Avenida Triunvirato 3424, Villa Urquiza" instead of the full display_name,
    which goes on to the comuna, postcode and country."""
    address = result.get("address") or {}
    street = " ".join(
        part for part in (address.get("road"), address.get("house_number")) if part
    )
    area = next(
        (
            address[key]
            for key in ("suburb", "city_district", "town", "city")
            if address.get(key)
        ),
        None,
    )
    if street:
        return f"{street}, {area}" if area else street
    # A place without a street, like a station or a square
    return ", ".join(result["display_name"].split(", ")[:2])


class Geocoder:
    def __init__(
        self,
        client: httpx2.AsyncClient,
        settings: Settings,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.client = client
        self.settings = settings
        self.clock = clock
        self.sleep = sleep
        # One request at a time, so two people searching can't break the 1/s limit
        self.lock = asyncio.Lock()
        self.last_request: float | None = None
        self.pending = 0
        # Not found (None) is cached too: asking again gives the same answer
        self.cache: OrderedDict[str, Place | None] = OrderedDict()

    async def search(self, q: str) -> Place | None:
        key = normalize(q)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]

        if self.pending >= MAX_PENDING:
            raise GeocodeBusy(f"{self.pending} searches already waiting")
        self.pending += 1
        try:
            async with self.lock:
                # Someone else may have searched it while this one waited
                if key in self.cache:
                    return self.cache[key]
                found = await self._ask(key, CABA_VIEWBOX, CABA_LIMIT)
                place = next((p for p, state in found if state == CABA_STATE), None)
                if place is None:
                    found = await self._ask(key, AMBA_VIEWBOX, 1)
                    place = found[0][0] if found else None
        finally:
            self.pending -= 1

        self.cache[key] = place
        if len(self.cache) > MAX_CACHED:
            self.cache.popitem(last=False)
        return place

    async def _wait_for_turn(self):
        if self.last_request is None:
            return
        wait = MIN_INTERVAL_S - (self.clock() - self.last_request)
        if wait > 0:
            await self.sleep(wait)

    async def _ask(
        self, q: str, viewbox: str, limit: int
    ) -> list[tuple[Place, str | None]]:
        await self._wait_for_turn()
        try:
            return await self._request(q, viewbox, limit)
        finally:
            # Even a failed request counts toward the limit
            self.last_request = self.clock()

    async def _request(
        self, q: str, viewbox: str, limit: int
    ) -> list[tuple[Place, str | None]]:
        """Each place found, with its state (province) to tell CABA apart."""
        params = {
            "q": q,
            "format": "jsonv2",
            "limit": str(limit),
            "addressdetails": "1",
            "countrycodes": "ar",
            "viewbox": viewbox,
            "bounded": "1",
            "accept-language": "es",
        }
        try:
            resp = await self.client.get(
                f"{self.settings.nominatim_url}/search",
                params=params,
                headers={"User-Agent": self.settings.nominatim_user_agent},
                timeout=TIMEOUT,
            )
        except httpx2.RequestError as e:
            raise GeocodeError(f"request failed: {type(e).__name__}") from e

        if resp.status_code != 200:
            raise GeocodeError(f"unexpected status {resp.status_code}")
        try:
            return [
                (
                    Place(
                        lat=float(r["lat"]),
                        lon=float(r["lon"]),
                        label=short_label(r),
                    ),
                    (r.get("address") or {}).get("state"),
                )
                for r in resp.json()
            ]
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            raise GeocodeError("response is not a JSON list of places") from e
