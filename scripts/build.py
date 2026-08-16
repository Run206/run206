#!/usr/bin/env python3
"""Build the Run206 site.

    python3 scripts/build.py [--offline]

Pulls races from the RunSignUp API, expands club-run recurrence rules into real
dates, merges everything, and writes public/ ready for GitHub Pages.

--offline skips the network and rebuilds from the last public/events.json,
which is useful when iterating on templates.
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import yaml  # noqa: E402

from lib import geocode, recurrence  # noqa: E402
from lib.normalize import (  # noqa: E402
    apply_affiliate, dedupe, distance_tags, is_runnable,
)
from lib.util import slugify  # noqa: E402
from lib.render import render_site  # noqa: E402
from sources import heylo, raceroster, runsignup  # noqa: E402

DATA_DIR = os.path.join(ROOT, "data")
OUT_DIR = os.path.join(ROOT, "public")

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def load_yaml(name, default=None):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        return default if default is not None else []
    with open(path, "r") as handle:
        return yaml.safe_load(handle) or (default if default is not None else [])


def assign_group(event_date, today):
    """Bucket an event into a time group.

    Rolling 7-day windows rather than calendar weeks. Anchoring to the calendar
    week collapses "this week" to a single day when the build runs on a Sunday,
    which is exactly when someone is looking for something to run.

    Groups are assigned once at build time and baked into events.json, so the
    browser never re-derives them — filtering hides rows, it never moves an
    event between groups.
    """
    if not event_date:
        return "ongoing", "Ongoing & irregular", 9999

    parsed = date.fromisoformat(event_date)
    days_out = (parsed - today).days

    if days_out <= 7:
        return "this-week", "This week", 0
    if days_out <= 14:
        return "next-week", "Next week", 1

    key = "{:04d}-{:02d}".format(parsed.year, parsed.month)
    label = MONTHS[parsed.month - 1]
    if parsed.year != today.year:
        label = "{} {}".format(label, parsed.year)
    return key, label, 2 + parsed.year * 12 + parsed.month


def _suppress_superseded(recurring, heylo_events, config, log=print):
    """Drop generated weekly occurrences that a real posted event replaces.

    CSRD's "Monday Miles" exists both as a weekly rule in clubs.yml and, when
    they actually post it, as a dated event on Heylo — often renamed for a
    collab ("Monday Night Miles with New Balance"). Showing both would list the
    same run twice under two different names.

    Name matching can't catch that, so suppression is by organiser and date: if
    a Heylo community has any event on a given day, the weekly placeholders for
    the clubs it posts for are dropped for that day. The real event wins.
    """
    communities = ((config.get("sources") or {}).get("heylo") or {}).get(
        "communities") or []

    blocked = set()
    for community in communities:
        orgs = community.get("suppresses") or []
        if not orgs:
            continue
        dates = {e["date"] for e in heylo_events
                 if e.get("community_id") == community.get("id") and e.get("date")}
        for org in orgs:
            for day in dates:
                blocked.add((org.strip().lower(), day))

    if not blocked:
        return recurring

    kept = [e for e in recurring
            if ((e.get("org") or "").strip().lower(), e.get("date")) not in blocked]

    dropped = len(recurring) - len(kept)
    if dropped:
        log("  superseded {} generated occurrence(s) with real Heylo events"
            .format(dropped))
    return kept


def build_events(config, today, offline=False):
    platforms = (config.get("affiliate") or {}).get("platforms") or []
    weeks = int((config.get("build") or {}).get("club_weeks_ahead", 8))

    # Manual entries go first so they win any dedupe against the API.
    events = []

    for entry in load_yaml("races-manual.yml"):
        if not entry or not entry.get("name"):
            continue
        events.append({
            "name": entry["name"],
            "date": str(entry["date"]) if entry.get("date") else None,
            "time": entry.get("time", ""),
            "type": entry.get("type", "Race"),
            "distances": entry.get("distances", ""),
            "location": entry.get("location", ""),
            "org": entry.get("org", ""),
            "desc": entry.get("desc", ""),
            "url": entry.get("url") or "",
            "price": entry.get("price", ""),
            "source": "manual",
            "recurring": False,
        })

    recurring = []
    for entry in load_yaml("clubs.yml"):
        if not entry or not entry.get("name"):
            continue
        recurring.extend(recurrence.expand(entry, today, weeks))

    if offline:
        cached = os.path.join(OUT_DIR, "events.json")
        remote = []
        if os.path.exists(cached):
            with open(cached) as handle:
                previous = json.load(handle).get("events", [])
            remote = [e for e in previous
                      if e.get("source") in ("runsignup", "heylo", "raceroster")]
            print("offline: reused {} cached remote events".format(len(remote)))
    else:
        print("fetching Heylo community events…")
        remote = heylo.fetch(config, today, log=print)
        print("fetching RunSignUp races…")
        remote.extend(runsignup.fetch(config, today, log=print))
        print("fetching Race Roster events…")
        remote.extend(raceroster.fetch(config, today, log=print))

    heylo_events = [e for e in remote if e.get("source") == "heylo"]
    recurring = _suppress_superseded(recurring, heylo_events, config, log=print)

    events.extend(heylo_events)
    events.extend([e for e in remote if e.get("source") != "heylo"])
    events.extend(recurring)

    events = dedupe(events)

    excluded = set(load_yaml("overrides.yml", {}).get("exclude_race_ids", []) or [])
    prepared = []
    for event in events:
        if event.get("source_id") and event["source_id"] in excluded:
            continue
        # Volunteer shifts and sponsorship packages are registrations, not runs.
        if not is_runnable(event.get("name")):
            continue
        if event.get("date"):
            try:
                if date.fromisoformat(event["date"]) < today:
                    continue
            except (ValueError, TypeError):
                continue

        group, group_label, group_order = assign_group(event.get("date"), today)
        price = (event.get("price") or "").strip()
        url = event.get("url") or ""
        tagged, tagged_by = apply_affiliate(url, platforms)

        prepared.append({
            "id": "{}-{}".format(slugify(event["name"]), event.get("date") or "ongoing"),
            "name": event["name"],
            "date": event.get("date"),
            "time": event.get("time", ""),
            "type": event.get("type", "Race"),
            "distances": event.get("distances", ""),
            "distance_tags": distance_tags(
                "{} {}".format(event.get("distances", ""), event.get("name", ""))
            ),
            "location": event.get("location", ""),
            "org": event.get("org", ""),
            "desc": event.get("desc", ""),
            "url": tagged,
            "affiliate": bool(tagged_by),
            "affiliate_platform": tagged_by or "",
            "price": price,
            "free": price.lower() in ("free", "$0", "0"),
            "recurring": bool(event.get("recurring")),
            "schedule": event.get("schedule", ""),
            "source": event.get("source", ""),
            # Preserved so an --offline rebuild reproduces the same suppression
            # decisions as the online build that cached this data.
            "community_id": event.get("community_id", ""),
            "group": group,
            "group_label": group_label,
            "group_order": group_order,
        })

    _ensure_unique_ids(prepared)

    prepared.sort(key=lambda e: (
        e["group_order"],
        e["date"] or "9999-99-99",
        e.get("time") or "zz",
        e["name"],
    ))
    return prepared


def _ensure_unique_ids(events):
    """Guarantee every event id is unique.

    The id is both the per-event page path (/e/<id>/) and the calendar UID, so
    a collision means one event silently overwrites another's page and
    subscribers see duplicated calendar entries.

    Dedupe should already have merged genuine duplicates, but it matches names
    heuristically and will always miss some edge case — two distinct races can
    legitimately share a name and date in different cities. This makes the
    consequences structural rather than relying on the heuristic being perfect.
    """
    seen = {}
    for event in events:
        base = event["id"]
        if base not in seen:
            seen[base] = 1
            continue
        seen[base] += 1
        suffix = event.get("source") or str(seen[base])
        candidate = "{}-{}".format(base, slugify(suffix))
        while candidate in seen:
            seen[base] += 1
            candidate = "{}-{}-{}".format(base, slugify(suffix), seen[base])
        seen[candidate] = 1
        event["id"] = candidate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true",
                        help="skip the network, reuse cached API races")
    args = parser.parse_args()

    config = load_yaml("config.yml", {})
    today = date.today()

    active = [p.get("name") for p in (config.get("affiliate") or {}).get("platforms") or []
              if p.get("enabled") and p.get("token")]
    if active:
        print("affiliate platforms active: {}".format(", ".join(active)))
    else:
        print("WARNING: no affiliate platform enabled in data/config.yml — links "
              "are untagged and earn nothing. See runsignup.com/affiliate.")

    events = build_events(config, today, offline=args.offline)

    print("geocoding event locations…")
    located = geocode.resolve(events, ROOT, log=print)
    print("  {} of {} events placed on the map".format(located, len(events)))

    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)

    payload = {
        "generated": "{}T00:00:00Z".format(today.isoformat()),
        "count": len(events),
        "events": events,
    }
    with open(os.path.join(OUT_DIR, "events.json"), "w") as handle:
        json.dump(payload, handle, indent=1, ensure_ascii=False)

    render_site(config, events, today, OUT_DIR, ROOT)

    races = sum(1 for e in events if e["type"] == "Race")
    clubs = sum(1 for e in events if e["type"] == "Club Run")
    brands = sum(1 for e in events if e["type"] == "Brand Event")
    print("\nwrote {} events -> public/  ({} races, {} club runs, {} brand events)"
          .format(len(events), races, clubs, brands))


if __name__ == "__main__":
    main()
