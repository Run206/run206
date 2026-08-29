"""Heylo community events (Club Seattle Runners Division and friends).

Heylo is a Next.js app that embeds its data in `__NEXT_DATA__`, so the events
come out as clean JSON rather than needing HTML scraping:

    /g/<communityId>       -> upcoming events: id, name, timestamp, image
    /event/<eventId>       -> full record: notes, location, timezone, end time

heylo.com/robots.txt has no Disallow rules at all. Even so, this fetches the
group page once plus one request per upcoming event, with a delay between them,
and honours each event's own `isVisibleToPublic` / `isDraft` flags — private and
draft events are never ingested.

This is what surfaces CSRD's one-off collabs (the New Balance marathon festival,
the 1 Hotel morning runs) that a weekly recurrence rule can't express.
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.tz import format_time, from_epoch_ms  # noqa: E402
from lib.util import USER_AGENT, strip_html, truncate  # noqa: E402

import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

GROUP_URL = "https://www.heylo.com/g/{}"
EVENT_URL = "https://www.heylo.com/event/{}"
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)

MAX_EVENTS = 40
DELAY_SECONDS = 0.6

DEFAULT_BRANDS = [
    "lululemon", "1 hotel", "shake shack", "new balance", "brooks", "nike",
    "on running", "hoka", "asics", "adidas", "saucony", "tracksmith",
    "athletic brewing", "rei", "fleet feet", "satisfy", "norda",
]


def _get_html(url, timeout=25):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def _next_data(html):
    match = NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except ValueError:
        return None


def _queries(payload):
    try:
        return payload["props"]["pageProps"]["dehydratedState"]["queries"]
    except (KeyError, TypeError):
        return []


def fetch(config, start, log=print):
    """Return event dicts for every configured Heylo community."""
    settings = (config.get("sources") or {}).get("heylo") or {}
    communities = settings.get("communities") or []
    if not communities:
        return []

    brands = [b.lower() for b in (settings.get("brand_keywords") or DEFAULT_BRANDS)]
    out = []

    for community in communities:
        community_id = community.get("id")
        org = community.get("org") or "Heylo community"
        if not community_id:
            continue

        try:
            payload = _next_data(_get_html(GROUP_URL.format(community_id)))
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            log("  heylo: {} unreachable ({})".format(org, exc))
            continue

        listing = []
        for query in _queries(payload or {}):
            data = (query.get("state") or {}).get("data") or {}
            if isinstance(data, dict) and data.get("events"):
                listing = data["events"]
                break

        if not listing:
            log("  heylo: {} listed no upcoming events".format(org))
            continue

        log("  heylo: {} has {} upcoming".format(org, len(listing)))

        for entry in listing[:MAX_EVENTS]:
            event_id = entry.get("id")
            if not event_id:
                continue
            time.sleep(DELAY_SECONDS)
            try:
                detail = _event_detail(event_id)
            except (urllib.error.URLError, urllib.error.HTTPError) as exc:
                log("    skipped {} ({})".format(entry.get("name"), exc))
                continue

            built = _build(detail or {}, entry, org, community_id, brands, start)
            if built:
                out.append(built)

    return out


def _event_detail(event_id):
    payload = _next_data(_get_html(EVENT_URL.format(event_id)))
    for query in _queries(payload or {}):
        key = query.get("queryKey") or []
        if key and key[0] == "event":
            data = (query.get("state") or {}).get("data") or {}
            return data.get("event")
    return None


def _build(detail, listing, org, community_id, brands, start):
    # Respect the organiser's own visibility settings.
    if detail.get("isDraft") or detail.get("isVisibleToPublic") is False:
        return None

    millis = detail.get("timestamp") or listing.get("timestamp")
    when = from_epoch_ms(millis)
    if not when or when.date() < start:
        return None

    name = strip_html(detail.get("name") or listing.get("name") or "")
    if not name:
        return None

    full_notes = strip_html(detail.get("notes"))
    notes = truncate(full_notes, 150)
    location = _location(detail)

    # Match against the *full* notes, not the truncated display copy — the
    # partner is usually named a paragraph in ("Join CSRD and New Balance…"),
    # well past the 150-character summary.
    blob = "{} {}".format(name, full_notes).lower()
    is_brand = any(brand in blob for brand in brands)

    return {
        "name": name,
        "date": when.date().isoformat(),
        "time": format_time(when),
        "type": "Brand Event" if is_brand else "Club Run",
        "distances": "",
        "location": location,
        "org": org,
        "desc": notes,
        "url": EVENT_URL.format(detail.get("eventId") or listing.get("id")),
        "price": "Free",
        "image": detail.get("image") or listing.get("image") or "",
        "source": "heylo",
        "source_id": detail.get("eventId") or listing.get("id"),
        "community_id": community_id,
        "recurring": False,
    }


def _location(detail):
    """Prefer a real street address; fall back to the free-text location note."""
    data = detail.get("locationData") or {}
    address = data.get("address") or {}
    parts = [address.get("name"), address.get("streetAddress"),
             address.get("addressLocality")]
    joined = ", ".join(p for p in parts if p)
    if joined:
        return joined
    if address.get("neighborhood"):
        return address["neighborhood"]
    return truncate(strip_html(detail.get("location")), 60)
