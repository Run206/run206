"""Distance tagging, affiliate links, dedupe.

The distance buckets here deliberately replace the ones in the original
mockups, which put 8K in both the 5K and 10K buckets and filed 30K under "10K".
"""

import re
import urllib.parse

# Ordered: first match wins for display purposes, but an event can carry
# several tags (a "Half Marathon & 5K" is both).
_RULES = [
    ("Kids", r"\bkid|\bkids\b|\byouth\b|\btot\b|diaper|\bdash\b"),
    ("Track", r"\btrack\b|\bintervals?\b|\btempo\b"),
    ("Relay", r"\brelay\b|\bragnar\b"),
    # \btimed\b, not timed\b — the latter also matches "UNTIMED", which tagged
    # a pile of kids' fun runs as ultramarathons.
    ("Ultra", r"\bultra|\b50k\b|\b100k\b|\b50\s*mile|\b100\s*mile|\b12\s*hour|"
              r"\b24\s*hour|\b6\s*hour|\b3\s*hour|\btimed\b|\b50m\b|\b100m\b"),
    ("Marathon", r"\bmarathon\b|\b26\.2\b"),
    ("Half", r"\bhalf\b|\b13\.1\b|\bhalf-marathon\b"),
    ("10K", r"\b10\s*k\b|\b10km\b|\b12k\b|\b15k\b|\b8\s*k\b|\b6\s*mile|\b5\s*mile"),
    ("5K", r"\b5\s*k\b|\b5km\b|\b4\s*k\b|\b3\s*k\b|\b2\s*k\b"),
    ("Mile", r"\b1\s*mile\b|\bone\s*mile\b|\bmile\s*run\b"),
]
_COMPILED = [(tag, re.compile(pattern, re.I)) for tag, pattern in _RULES]

# "Marathon" must not fire on "Half Marathon".
_HALF_RE = re.compile(r"\bhalf\b|\b13\.1\b", re.I)


def distance_tags(text):
    """Return the set of filter tags implied by a distance/event string."""
    if not text:
        return []
    blob = str(text)
    tags = []
    for tag, rx in _COMPILED:
        if not rx.search(blob):
            continue
        if tag == "Marathon" and _HALF_RE.search(blob) and not re.search(
            r"(?<!half\s)marathon", blob, re.I
        ):
            # Only "Half Marathon" present, no standalone marathon.
            continue
        tags.append(tag)

    # A string naming both distances keeps both; one naming only the half
    # should not claim the full.
    if "Marathon" in tags and "Half" in tags:
        without_half = _HALF_RE.sub(" ", blob)
        if not re.search(r"\bmarathon\b|\b26\.2\b", without_half, re.I):
            tags.remove("Marathon")
    return tags


# Clean distance tokens to show in the UI, longest-first so "half marathon"
# wins over "marathon".
_DISPLAY_RULES = [
    (r"\bhalf\s*marathon\b|\b13\.1\b", "Half Marathon"),
    (r"\bfull\s*marathon\b|\b26\.2\b|(?<!half )\bmarathon\b", "Marathon"),
    (r"\b100\s*mile[rs]?\b|\b100m\b", "100 Mile"),
    (r"\b50\s*mile[rs]?\b|\b50m\b", "50 Mile"),
    (r"\b(\d{1,3})\s*k(?:m)?\b", None),          # 5K, 10K, 50K …
    (r"\b(\d{1,2})\s*mile[rs]?\b", None),        # 1 Mile, 10 Mile …
    (r"\b(\d{1,2})\s*hour\b", None),             # 6 Hour, 12 Hour …
    (r"\brelay\b", "Relay"),
    (r"\bkids?\b|\byouth\b|\bdash\b|\btot\b", "Kids"),
    (r"\bruck\b", "Ruck"),
    (r"\bwalk\b", "Walk"),
]
_DISPLAY_COMPILED = [(re.compile(p, re.I), label) for p, label in _DISPLAY_RULES]


def summarize_distances(names, limit=4):
    """Turn a race's raw event names into a short, scannable distance list.

    RunSignUp event names are free text and often unusable as-is — things like
    "Run or Walk 5k YOUTH - under 14 (youth size shirt)". Pulling the actual
    distance tokens out gives "5K, Kids" instead.

    Falls back to the raw names when nothing recognisable is found, so an
    unusual event is still described rather than blanked.
    """
    blob = " ; ".join(n for n in names if n)
    if not blob:
        return ""

    found = []
    for rx, label in _DISPLAY_COMPILED:
        for match in rx.finditer(blob):
            if label:
                value = label
            else:
                number = match.group(1)
                raw = match.group(0).lower()
                if "hour" in raw:
                    value = "{} Hour".format(number)
                elif "mile" in raw:
                    value = "{} Mile".format(number)
                else:
                    value = "{}K".format(number)
            if value not in found:
                found.append(value)

    if not found:
        cleaned = [n.strip() for n in names if n and len(n) < 40]
        return ", ".join(cleaned[:2])

    # Keep the numeric distances first and in ascending order; qualifiers last.
    def sort_key(value):
        match = re.match(r"^(\d+)\s*(K|Mile|Hour)$", value)
        if match:
            number, unit = int(match.group(1)), match.group(2)
            metres = {"K": 1000, "Mile": 1609, "Hour": 100000}[unit] * number
            return (0, metres)
        order = {"Half Marathon": 21097, "Marathon": 42195,
                 "50 Mile": 80467, "100 Mile": 160934}
        if value in order:
            return (0, order[value])
        return (1, 0)

    found.sort(key=sort_key)
    return ", ".join(found[:limit])


def apply_affiliate(url, token):
    """Append the RunSignUp affiliate token to a runsignup.com URL.

    Applied centrally at build time so no link is ever hand-tagged, and so
    rotating the token is a one-line change.
    """
    if not url or not token:
        return url
    parts = urllib.parse.urlsplit(url)
    if not parts.netloc.lower().endswith("runsignup.com"):
        return url
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query = [(k, v) for k, v in query if k not in ("affiliateToken", "raceRefCode")]
    query.append(("affiliateToken", token))
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment)
    )


_NOISE_RE = re.compile(r"\b(the|a|an|annual|\d{1,2}(st|nd|rd|th)|20\d\d)\b", re.I)
_NONWORD_RE = re.compile(r"[^a-z0-9]+")


def dedupe_key(name, event_date):
    """Loose identity for an event, so API and manual entries collapse.

    Strips ordinals and years so "17th Annual Parkland Pace" and
    "Parkland Pace 2026" match.
    """
    text = _NOISE_RE.sub(" ", str(name or "").lower())
    text = _NONWORD_RE.sub("", text)
    return "{}|{}".format(text, event_date or "")


def dedupe(events):
    """Keep the first occurrence of each key. Manual entries should be passed
    in first so they win over API-sourced duplicates."""
    seen = {}
    out = []
    for event in events:
        key = dedupe_key(event.get("name"), event.get("date"))
        if key in seen:
            continue
        seen[key] = True
        out.append(event)
    return out
