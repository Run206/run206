#!/usr/bin/env python3
"""Generate the weekly newsletter from the built events.

    python3 scripts/digest.py                 # the coming weekend
    python3 scripts/digest.py --days 10
    python3 scripts/digest.py --format html   # paste-ready

Writes to public/digest/latest.{md,html} and prints the markdown.

The point is that writing a weekly email by hand is the thing that kills weekly
emails. This turns it into a review-and-send.
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import yaml  # noqa: E402

from lib.util import esc  # noqa: E402

EVENTS = os.path.join(ROOT, "public", "events.json")
OUT_DIR = os.path.join(ROOT, "public", "digest")

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
            "Saturday", "Sunday"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def load(path, loader=json.load):
    with open(path) as handle:
        return loader(handle)


def pretty(iso):
    day = date.fromisoformat(iso)
    return "{}, {} {}".format(WEEKDAYS[day.weekday()], day.day,
                              MONTHS[day.month - 1])


def pick(events, start, days):
    end = start + timedelta(days=days)
    chosen = [
        e for e in events
        if e.get("date") and start.isoformat() <= e["date"] <= end.isoformat()
    ]
    chosen.sort(key=lambda e: (e["date"], e.get("time") or "zz", e["name"]))
    return chosen


def markdown(races, clubs, start, days, domain):
    end = start + timedelta(days=days)
    lines = [
        "# Running in Seattle: {} – {}".format(
            pretty(start.isoformat()), pretty(end.isoformat())),
        "",
        "{} races and {} club sessions in the next {} days.".format(
            len(races), len(clubs), days),
        "",
    ]

    if races:
        lines += ["## Races", ""]
        for event in races:
            bits = [b for b in [event.get("distances"), event.get("location"),
                                event.get("price")] if b]
            lines.append("**[{}]({})** — {}  ".format(
                event["name"], event.get("url") or "https://" + domain,
                pretty(event["date"])))
            if bits:
                lines.append("  " + " · ".join(bits))
            lines.append("")

    if clubs:
        lines += ["## Club runs and group sessions", ""]
        by_day = {}
        for event in clubs:
            by_day.setdefault(event["date"], []).append(event)
        for day in sorted(by_day):
            lines.append("**{}**  ".format(pretty(day)))
            for event in by_day[day]:
                where = " · ".join(
                    b for b in [event.get("org"), event.get("location"),
                                event.get("time")] if b)
                lines.append("  {} — {}  ".format(event["name"], where))
            lines.append("")

    lines += [
        "---",
        "",
        "All {} upcoming events: https://{}/  ".format(len(races) + len(clubs), domain),
        "On a map: https://{}/map/  ".format(domain),
        "Subscribe in your calendar: https://{}/calendar.ics".format(domain),
        "",
        "*Some race links are affiliate links — Run206 earns a small share of the "
        "booking fee at no extra cost to you.*",
    ]
    return "\n".join(lines)


def to_html(races, clubs, start, days, domain):
    end = start + timedelta(days=days)
    out = [
        '<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
        'max-width:600px;margin:0 auto;color:#14171A;line-height:1.55">',
        '<h1 style="font-size:22px;margin:0 0 4px">Running in Seattle</h1>',
        '<p style="margin:0 0 20px;color:#575E66;font-size:14px">{} – {}</p>'.format(
            esc(pretty(start.isoformat())), esc(pretty(end.isoformat()))),
    ]

    if races:
        out.append('<h2 style="font-size:15px;text-transform:uppercase;'
                   'letter-spacing:.06em;color:#878E96;margin:26px 0 10px">Races</h2>')
        for event in races:
            meta = " &middot; ".join(esc(b) for b in [
                event.get("distances"), event.get("location"), event.get("price")] if b)
            out.append(
                '<div style="padding:11px 0;border-bottom:1px solid #E5E2DC">'
                '<a href="{}" style="color:#C0402A;text-decoration:none;'
                'font-weight:600;font-size:15px">{}</a>'
                '<div style="font-size:13px;color:#575E66;margin-top:2px">{}</div>'
                '<div style="font-size:13px;color:#878E96">{}</div></div>'.format(
                    esc(event.get("url") or "https://" + domain),
                    esc(event["name"]), esc(pretty(event["date"])), meta))

    if clubs:
        out.append('<h2 style="font-size:15px;text-transform:uppercase;'
                   'letter-spacing:.06em;color:#878E96;margin:26px 0 10px">'
                   'Club runs</h2>')
        by_day = {}
        for event in clubs:
            by_day.setdefault(event["date"], []).append(event)
        for day in sorted(by_day):
            out.append('<p style="margin:14px 0 4px;font-weight:600;font-size:14px">'
                       "{}</p>".format(esc(pretty(day))))
            for event in by_day[day]:
                where = " &middot; ".join(esc(b) for b in [
                    event.get("org"), event.get("location"), event.get("time")] if b)
                out.append('<div style="font-size:13px;color:#575E66;padding:3px 0">'
                           "<strong>{}</strong> — {}</div>".format(
                               esc(event["name"]), where))

    out.append(
        '<p style="margin:28px 0 0;font-size:13px;color:#878E96;'
        'border-top:1px solid #E5E2DC;padding-top:16px">'
        '<a href="https://{d}/" style="color:#575E66">All events</a> &middot; '
        '<a href="https://{d}/map/" style="color:#575E66">Map</a> &middot; '
        '<a href="https://{d}/calendar.ics" style="color:#575E66">Calendar feed</a>'
        "<br><br>Some race links are affiliate links — Run206 earns a small share "
        "of the booking fee at no extra cost to you.</p></div>".format(d=esc(domain)))
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--format", choices=["md", "html", "both"], default="both")
    args = parser.parse_args()

    if not os.path.exists(EVENTS):
        print("No public/events.json — run scripts/build.py first.")
        return 1

    config = load(os.path.join(ROOT, "data", "config.yml"), yaml.safe_load) or {}
    domain = (config.get("site") or {}).get("domain", "run206.com")

    events = load(EVENTS)["events"]
    start = date.today()
    upcoming = pick(events, start, args.days)

    races = [e for e in upcoming if e["type"] == "Race"]
    clubs = [e for e in upcoming if e["type"] != "Race"]

    if not races and not clubs:
        print("Nothing in the next {} days — no digest written.".format(args.days))
        return 0

    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)

    text = markdown(races, clubs, start, args.days, domain)
    if args.format in ("md", "both"):
        with open(os.path.join(OUT_DIR, "latest.md"), "w") as handle:
            handle.write(text + "\n")
    if args.format in ("html", "both"):
        with open(os.path.join(OUT_DIR, "latest.html"), "w") as handle:
            handle.write(to_html(races, clubs, start, args.days, domain) + "\n")

    print(text)
    print("\n---\nwrote public/digest/latest.md and latest.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
