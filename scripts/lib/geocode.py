"""Geocoding via OpenStreetMap Nominatim, with a committed cache.

Nominatim's usage policy allows at most one request per second and requires a
identifying User-Agent. Both are honoured here.

The cache (`data/geocache.json`) is committed to the repo on purpose: most
events share a handful of locations ("Seattle, WA", "Kirkland, WA"), so after
the first run almost every lookup is a cache hit and the build makes no
geocoding requests at all. It also means a Nominatim outage can't break a build.
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from lib.util import USER_AGENT

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
RATE_LIMIT_SECONDS = 1.1
MAX_LOOKUPS_PER_BUILD = 40

# Bounding box for the Puget Sound region. Anything geocoded outside it is
# discarded rather than dropping a pin in the wrong state — Nominatim will
# happily return Kirkland, Quebec for "Kirkland".
LAT_RANGE = (46.8, 48.6)
LON_RANGE = (-123.4, -121.4)

# Well-known Seattle running spots Nominatim resolves poorly or ambiguously.
KNOWN = {
    "green lake": (47.6806, -122.3287),
    "green lake wading pool": (47.6797, -122.3255),
    "lower woodland park track": (47.6689, -122.3419),
    "gas works park": (47.6456, -122.3344),
    "seward park": (47.5514, -122.2549),
    "magnuson park": (47.6812, -122.2568),
    "discovery park": (47.6580, -122.4060),
    "lincoln park": (47.5301, -122.3951),
    "alki beach": (47.5812, -122.4087),
    "mohai": (47.6275, -122.3360),
    "brooks trailhead": (47.6497, -122.3424),
    "chambers bay": (47.2015, -122.5730),
    "flying lion brewing": (47.5595, -122.2870),
    "roosevelt high school": (47.6764, -122.3175),
    "cleveland high school": (47.5478, -122.3125),
    "hiawatha": (47.5610, -122.3865),
}


def _cache_path(root):
    return os.path.join(root, "data", "geocache.json")


def load_cache(root):
    path = _cache_path(root)
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as handle:
            return json.load(handle)
    except ValueError:
        return {}


def save_cache(root, cache):
    with open(_cache_path(root), "w") as handle:
        json.dump(cache, handle, indent=1, sort_keys=True, ensure_ascii=False)


def normalise(location):
    """Cache key: lowercased, punctuation-collapsed location string."""
    text = re.sub(r"\s+", " ", str(location or "").strip().lower())
    return re.sub(r"[^\w ,]", "", text)


def _in_region(lat, lon):
    return LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]


def _lookup(query):
    params = {
        "q": query,
        "format": "json",
        "limit": "1",
        "countrycodes": "us",
        # Bias results to the Puget Sound box.
        "viewbox": "{},{},{},{}".format(LON_RANGE[0], LAT_RANGE[1],
                                        LON_RANGE[1], LAT_RANGE[0]),
        "bounded": "1",
    }
    url = "{}?{}".format(NOMINATIM_URL, urllib.parse.urlencode(params))
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload:
        return None
    try:
        lat = float(payload[0]["lat"])
        lon = float(payload[0]["lon"])
    except (KeyError, ValueError, IndexError):
        return None
    if not _in_region(lat, lon):
        return None
    return [round(lat, 5), round(lon, 5)]


def resolve(events, root, log=print):
    """Attach `coords` to each event that can be placed on a map.

    Returns the number of events successfully located.
    """
    cache = load_cache(root)
    pending = []

    for event in events:
        key = normalise(event.get("location"))
        if not key:
            continue

        # Known landmarks first — they're more precise than a city centroid.
        hit = None
        for landmark, coords in KNOWN.items():
            if landmark in key:
                hit = list(coords)
                break
        if hit:
            event["coords"] = hit
            continue

        if key in cache:
            if cache[key]:
                event["coords"] = cache[key]
            continue
        if key not in pending:
            pending.append(key)

    looked_up = 0
    for key in pending[:MAX_LOOKUPS_PER_BUILD]:
        if looked_up:
            time.sleep(RATE_LIMIT_SECONDS)   # Nominatim: max 1 req/sec
        looked_up += 1
        try:
            cache[key] = _lookup(key)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
            log("    geocode failed for {!r}: {}".format(key, exc))
            continue

    if looked_up:
        save_cache(root, cache)
        log("  geocoded {} new location(s)".format(looked_up))

    located = 0
    for event in events:
        if event.get("coords"):
            located += 1
            continue
        key = normalise(event.get("location"))
        if key and cache.get(key):
            event["coords"] = cache[key]
            located += 1

    return located
