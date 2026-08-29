"""Shared helpers: HTTP, text cleaning, slugs, dates."""

import html
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime

USER_AGENT = "Run206/1.0 (+https://run206.com) events aggregator"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


class FetchError(Exception):
    pass


def get_json(url, params=None, retries=3, timeout=30):
    """GET a JSON endpoint with retries and exponential backoff.

    RunSignUp signals bad requests with HTTP 200 and an `error` key in the body
    rather than a 4xx, so a caller that only checks the status code sees an
    empty result set and silently publishes nothing. Treat that as a hard error.
    """
    if params:
        url = "{}?{}".format(url, urllib.parse.urlencode(params))
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            continue

        if isinstance(payload, dict) and payload.get("error"):
            error = payload["error"]
            raise FetchError("API rejected the request: {} (code {}) — {}".format(
                error.get("error_msg", "unknown"),
                error.get("error_code", "?"),
                json.dumps(error.get("param_datatype_mismatch", [])),
            ))
        return payload

    raise FetchError("GET {} failed after {} tries: {}".format(url, retries, last))


def strip_html(value):
    """Turn a possibly-HTML string into clean single-line plain text.

    The RunSignUp API returns real HTML inside `description` (<p>, <span>,
    inline styles). Rendering that raw is both ugly and an injection vector, so
    every description goes through here before it reaches a template.
    """
    if not value:
        return ""
    text = _TAG_RE.sub(" ", str(value))
    text = html.unescape(text)
    text = text.replace(" ", " ")
    return _WS_RE.sub(" ", text).strip()


_WEEKDAY_RE = re.compile(
    r"^\s*(mon|tues|wednes|thurs|fri|satur|sun)day\b", re.I)
_ZIP_RE = re.compile(r"\b\d{5}(-\d{4})?\b")


# Emoji, variation selectors and ZWJ sequences. Race marketing copy is full of
# them ("🎀 Join the Fight", "🦥🏃‍♂️ The Sloth Run"), and they land at the front
# where they push the actual information out of the two-line clamp.
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"      # pictographs, emoticons, transport, symbols
    "\U00002600-\U000027BF"      # misc symbols and dingbats
    "\U00002B00-\U00002BFF"      # arrows and geometric shapes
    "\U0001F1E6-\U0001F1FF"      # regional indicators (flags)
    "\U0000FE00-\U0000FE0F"      # variation selectors
    "\U0000200D"                  # zero-width joiner
    "\U000023E9-\U000023FA"      # media symbols
    "]+", flags=re.UNICODE)


def strip_emoji(text):
    """Remove emoji from imported copy.

    Deliberate editorial choice, not a bug fix: these descriptions are other
    people's promotional text shown in a two-line clamp, so decorative
    characters cost information. Revert by dropping this call if you'd rather
    keep the source copy verbatim.
    """
    if not text:
        return text
    cleaned = _EMOJI_RE.sub(" ", text)
    return re.sub(r"\s{2,}", " ", cleaned).strip(" -–—:·|")


def clean_description(text):
    """Drop leading logistics boilerplate from a race description.

    Race directors routinely open with the date and venue address — "Sunday,
    Aug 16 @ 9am 7235 NE Pkwy, Suquamish, WA 98392 | House of Awakened
    Culture | A fun, scenic course…" — which is all repeated elsewhere in the
    row. Strip up to two leading pipe-delimited segments that look like a date
    or an address, then keep the prose.

    Conservative on purpose: if nothing recognisably boilerplate is found, the
    original text is returned untouched.
    """
    if not text or "|" not in text:
        return text
    segments = [s.strip() for s in text.split("|")]
    dropped = 0
    while len(segments) > 1 and dropped < 2:
        head = segments[0]
        looks_like_boilerplate = (
            _WEEKDAY_RE.search(head) or _ZIP_RE.search(head)
        ) and len(head) < 120
        if not looks_like_boilerplate:
            break
        segments.pop(0)
        dropped += 1
    return " ".join(" ".join(segments).split()) if dropped else text


def truncate(text, limit=180):
    """Trim to `limit` chars on a word boundary."""
    if not text or len(text) <= limit:
        return text or ""
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:-")
    return cut + "…"


def esc(value):
    """HTML-escape for safe interpolation, quotes included."""
    return html.escape("" if value is None else str(value), quote=True)


def slugify(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return re.sub(r"-{2,}", "-", text) or "event"


def parse_api_date(value):
    """RunSignUp returns dates as M/D/YYYY, sometimes with a trailing time."""
    if not value:
        return None
    head = str(value).strip().split(" ")[0]
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    return None


def parse_money(value):
    """'$35.00' -> 35.0. Returns None when unparseable."""
    if value is None:
        return None
    match = re.search(r"[\d,]+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def format_price_range(low, high):
    if low is None and high is None:
        return ""
    if low == 0 and (high in (0, None)):
        return "Free"

    def fmt(amount):
        return "${:,.0f}".format(amount) if amount == int(amount) else "${:,.2f}".format(amount)

    if high is None or abs(high - low) < 0.01:
        return fmt(low)
    return "{}–{}".format(fmt(low), fmt(high))


def today():
    return date.today()
