"""RunSignUp races API client.

Endpoint notes learned the hard way:

  * zipcode + radius is the only geo filter that works. Passing latitude and
    longitude is silently ignored and returns nationwide results.
  * events=T is required to get per-distance detail and pricing.
  * The per-event `distance` field is unreliable (it reports a 10K as
    "7.5 Miles" and leaves Half Marathon null), so distances are derived from
    event *names* instead.
  * Prices live in registration_periods, not registration_fee.
"""

import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.normalize import summarize_distances  # noqa: E402
from lib.util import (  # noqa: E402
    clean_description, format_price_range, get_json, parse_api_date, parse_money,
    strip_html, truncate,
)

API_URL = "https://runsignup.com/Rest/races"
PAGE_SIZE = 250
MAX_PAGES = 20


def fetch(config, start, log=print):
    """Return normalised race dicts within the configured radius."""
    settings = config["sources"]["runsignup"]
    end = start + timedelta(days=int(settings.get("months_ahead", 14) * 30.5))
    exclude_virtual = bool(settings.get("exclude_virtual", True))

    races = []
    for page in range(1, MAX_PAGES + 1):
        payload = get_json(API_URL, {
            "format": "json",
            "zipcode": str(settings["zipcode"]),
            "radius": str(settings["radius_miles"]),
            # ISO, despite the published docs saying MM/DD/YYYY — that format
            # is rejected with error_code 3 and an HTTP 200.
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "events": "T",
            "only_partner_races": "F",
            "results_per_page": str(PAGE_SIZE),
            "page": str(page),
        })
        batch = payload.get("races") or []
        if not batch:
            break
        races.extend(batch)
        log("  page {}: {} races".format(page, len(batch)))
        if len(batch) < PAGE_SIZE:
            break

    out = []
    skipped_virtual = 0
    for wrapper in races:
        race = wrapper.get("race") or {}
        event = _normalise(race, start)
        if not event:
            continue
        if exclude_virtual and _is_virtual(race, event):
            skipped_virtual += 1
            continue
        out.append(event)

    if skipped_virtual:
        log("  skipped {} virtual races".format(skipped_virtual))
    return out


def _is_virtual(race, event):
    city = ((race.get("address") or {}).get("city") or "").strip().lower()
    if city == "virtual":
        return True
    return "virtual" in event["name"].lower()


def _normalise(race, start):
    if race.get("is_draft_race") == "T" or race.get("is_private_race") == "T":
        return None

    event_date = parse_api_date(race.get("next_date") or race.get("last_date"))
    if not event_date or event_date < start:
        return None

    address = race.get("address") or {}
    city = (address.get("city") or "").strip()
    state = (address.get("state") or "").strip()
    if state and state.upper() != "WA":
        return None

    events = race.get("events") or []
    name = strip_html(race.get("name"))
    distances = summarize_distances(_distance_names(events, name))
    low, high = _price_range(events)

    return {
        "name": name,
        "date": event_date.isoformat(),
        "time": _start_time(events),
        "type": "Race",
        "distances": distances,
        "location": ", ".join(p for p in (city, state) if p),
        # This endpoint exposes no organiser field, and echoing the race name
        # back as its own organiser just prints it twice.
        "org": "",
        "desc": truncate(clean_description(strip_html(race.get("description"))), 150),
        "url": race.get("url") or race.get("external_race_url") or "",
        "price": format_price_range(low, high),
        "price_low": low,
        "registration_open": race.get("is_registration_open") == "T",
        "logo": race.get("logo_url") or "",
        "source": "runsignup",
        "source_id": race.get("race_id"),
        "recurring": False,
    }


def _distance_names(events, fallback):
    """Distinct event names, which carry distance far more reliably than the
    numeric `distance` field."""
    names = []
    for event in events:
        name = strip_html(event.get("name"))
        if name and name not in names:
            names.append(name)
    if not names and fallback:
        return [strip_html(fallback)]
    return names[:8]


def _price_range(events):
    """Lowest and highest currently-relevant race fee across all events.

    Zero-cost entries (free kids' dashes, volunteer slots) are excluded from the
    low end unless every event is free — otherwise a $35 5K with a free kids run
    advertises itself as "$0–$35", which reads as though the race is free.
    """
    fees = []
    for event in events:
        periods = event.get("registration_periods") or []
        period_fees = [parse_money(p.get("race_fee")) for p in periods]
        period_fees = [f for f in period_fees if f is not None]
        if period_fees:
            fees.append(min(period_fees))
    if not fees:
        return None, None

    paid = [f for f in fees if f > 0]
    if not paid:
        return 0.0, 0.0
    return min(paid), max(paid)


def _start_time(events):
    for event in events:
        raw = event.get("start_time") or ""
        parts = str(raw).split(" ")
        if len(parts) >= 2 and ":" in parts[1]:
            try:
                hour, minute = int(parts[1].split(":")[0]), int(parts[1].split(":")[1])
            except (ValueError, IndexError):
                continue
            suffix = "AM" if hour < 12 else "PM"
            return "{}:{:02d} {}".format(hour % 12 or 12, minute, suffix)
    return ""
