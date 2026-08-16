"""Race Roster events.

Race Roster has no usable public event-search API — `/api/v1/events` returns
401, because that API is scoped to an organiser managing their own events, not
a directory feed. Their `/search` page is client-rendered.

What they *do* publish, deliberately and for crawlers, is a sitemap. So:

  1. pull sitemaps/events_<year>.xml (one file per year)
  2. keep base event URLs whose slug names a Seattle-area place
  3. fetch each of those pages and read its schema.org Event JSON-LD
  4. drop anything whose address isn't actually in Washington

Step 2 is a cheap filter that turns ~17,000 nationwide events into ~30 local
candidates, so step 3 stays small. Race Roster's robots.txt asks for
`Crawl-Delay: 5` and that is honoured between every request, which is why this
source is capped and cached.
"""

import json
import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

from lib.util import USER_AGENT, strip_html, truncate  # noqa: E402

SITEMAP_URL = "https://sitemap.raceroster.com/sitemaps/events_{}.xml"
LOC_RE = re.compile(r"<loc>(.*?)</loc>")
LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
# https://raceroster.com/events/<year>/<id>/<slug>  — and nothing deeper, which
# excludes /promote, /fundraising-organization/<n>, /volunteer and friends.
EVENT_URL_RE = re.compile(r"^https://raceroster\.com/events/(\d{4})/(\d+)/([a-z0-9\-]+)$")

CRAWL_DELAY = 5
MAX_EVENTS = 60

# Slug fragments that suggest a Seattle-area event. Deliberately generous — a
# false positive costs one request and is then dropped by the WA address check.
AREA_SLUGS = [
    "seattle", "tacoma", "bellevue", "kirkland", "redmond", "everett", "renton",
    "kent", "bothell", "issaquah", "bainbridge", "edmonds", "shoreline",
    "burien", "auburn", "puyallup", "snoqualmie", "woodinville", "lynnwood",
    "mercer-island", "federal-way", "gig-harbor", "poulsbo", "mukilteo",
    "sammamish", "kenmore", "des-moines", "tukwila", "monroe", "duvall",
    "north-bend", "carnation", "green-lake", "greenlake", "magnuson",
    "discovery-park", "alki", "ballard", "fremont", "capitol-hill", "queen-anne",
    "west-seattle", "lake-union", "lake-washington", "chambers-bay", "emerald-city",
]


def _get(url, timeout=45):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def fetch(config, start, log=print):
    settings = (config.get("sources") or {}).get("raceroster") or {}
    if not settings.get("enabled", True):
        return []

    years = sorted({start.year, start.year + 1})
    candidates = {}

    for year in years:
        try:
            xml = _get(SITEMAP_URL.format(year))
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            log("  raceroster: sitemap {} unavailable ({})".format(year, exc))
            continue

        found = 0
        for url in LOC_RE.findall(xml):
            match = EVENT_URL_RE.match(url.strip())
            if not match:
                continue
            slug = match.group(3)
            if not any(area in slug for area in AREA_SLUGS):
                continue
            # Key by numeric event id so a renamed slug doesn't duplicate.
            candidates.setdefault(match.group(2), url.strip())
            found += 1
        log("  raceroster: {} sitemap -> {} local candidates".format(year, found))

    if not candidates:
        return []

    cache = _load_cache(config)
    out = []
    fetched = 0

    for event_id, url in sorted(candidates.items())[:MAX_EVENTS]:
        cached = cache.get(event_id)
        if cached and cached.get("date") and cached["date"] >= start.isoformat():
            out.append(dict(cached))
            continue

        if fetched:
            time.sleep(CRAWL_DELAY)   # robots.txt: Crawl-Delay: 5
        fetched += 1

        try:
            html = _get(url)
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            log("    raceroster: {} unreachable ({})".format(event_id, exc))
            continue

        built = _parse(html, url, event_id, start)
        if built:
            out.append(built)
            cache[event_id] = built

    _save_cache(config, cache)
    log("  raceroster: {} events ({} newly fetched)".format(len(out), fetched))
    return out


def _parse(html, url, event_id, start):
    node = None
    for block in LD_RE.findall(html):
        try:
            parsed = json.loads(block)
        except ValueError:
            continue
        for item in (parsed if isinstance(parsed, list) else [parsed]):
            if isinstance(item, dict) and "Event" in str(item.get("@type", "")):
                node = item
                break
        if node:
            break
    if not node:
        return None

    place = node.get("location") or {}
    address = place.get("address") or {}
    if str(address.get("addressRegion", "")).upper() != "WA":
        return None   # slug matched, but the event isn't in Washington

    when = _parse_start(node.get("startDate"))
    if not when or when.date() < start:
        return None

    city = strip_html(address.get("addressLocality")) or "Seattle"
    name = strip_html(node.get("name"))
    if not name:
        return None

    return {
        "name": name,
        "date": when.date().isoformat(),
        "time": _format_time(when),
        "type": "Race",
        "distances": "",
        "location": "{}, WA".format(city),
        "org": "",
        "desc": truncate(_clean_desc(strip_html(node.get("description")), name), 150),
        "url": node.get("url") or url,
        "price": "",
        "source": "raceroster",
        "source_id": "rr-{}".format(event_id),
        "recurring": False,
    }


def _clean_desc(text, name):
    """Race Roster descriptions echo the event name, city and date back at you
    before the real copy starts. Strip that preamble."""
    if not text:
        return ""
    cleaned = text
    if name and cleaned.startswith(name):
        cleaned = cleaned[len(name):]
    cleaned = re.sub(r"^[\s,\-–]*[A-Za-z ]+, WA\s*[\-–]?\s*", "", cleaned)
    cleaned = re.sub(r"^\s*[A-Z]+DAY, [A-Z]+ \d{1,2}, \d{4}", "", cleaned)
    cleaned = re.sub(r"\s*[\-–]\s*[A-Z][a-z]+ \d{1,2}, \d{4}\s*$", "", cleaned)
    return cleaned.strip(" ,-–")


def _parse_start(value):
    if not value:
        return None
    text = str(value).strip()
    # "2026-11-29T07:00:00-08:00" — drop the offset, the local wall time is
    # what a runner needs.
    text = re.sub(r"(?:Z|[+\-]\d{2}:?\d{2})$", "", text)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _format_time(moment):
    if moment.hour == 0 and moment.minute == 0:
        return ""
    return "{}:{:02d} {}".format(
        moment.hour % 12 or 12, moment.minute,
        "AM" if moment.hour < 12 else "PM")


def _cache_path(config):
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "data", "raceroster-cache.json")


def _load_cache(config):
    path = _cache_path(config)
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as handle:
            return json.load(handle)
    except ValueError:
        return {}


def _save_cache(config, cache):
    # Drop past events so the file doesn't grow without bound.
    today = datetime.utcnow().date().isoformat()
    pruned = {k: v for k, v in cache.items() if (v.get("date") or "") >= today}
    with open(_cache_path(config), "w") as handle:
        json.dump(pruned, handle, indent=1, ensure_ascii=False, sort_keys=True)
