#!/usr/bin/env python3
"""Post-build checks. Exits non-zero if the build should not be published.

    python3 scripts/verify.py [--baseline path/to/previous/events.json]

The point of this file is that a broken build must fail loudly rather than
quietly publishing an empty or corrupted calendar. The most dangerous failure
mode is not a crash — it's the API returning a well-formed empty result and the
site going live with nothing on it.
"""

import argparse
import json
import os
import re
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")

MIN_EVENTS = 100
MIN_RATIO = 0.5

REQUIRED_FILES = ["index.html", "events.json", "sitemap.xml", "robots.txt",
                  "CNAME", "calendar.ics", "races.ics", "club-runs.ics",
                  os.path.join("map", "index.html")]

failures = []
warnings = []


def fail(message):
    failures.append(message)


def warn(message):
    warnings.append(message)


def check_files():
    for name in REQUIRED_FILES:
        path = os.path.join(PUBLIC, name)
        if not os.path.exists(path):
            fail("missing output file: public/{}".format(name))
        elif os.path.getsize(path) == 0:
            fail("empty output file: public/{}".format(name))


def check_events(data, baseline):
    events = data.get("events", [])
    count = len(events)

    if count < MIN_EVENTS:
        fail("only {} events (expected at least {})".format(count, MIN_EVENTS))

    if baseline:
        previous = baseline.get("count", 0)
        if previous and count < previous * MIN_RATIO:
            fail("event count collapsed: {} now vs {} previously (<{:.0%}) — "
                 "refusing to publish".format(count, previous, MIN_RATIO))

    today = date.today()
    past = [e for e in events if e.get("date") and e["date"] < today.isoformat()]
    if past:
        fail("{} events dated in the past, e.g. {}".format(
            len(past), ", ".join(e["name"] for e in past[:3])))

    # Weekly club runs must resolve to a real date; that expansion is the whole
    # point of the recurrence engine.
    undated_weekly = [
        e for e in events
        if e.get("recurring") and not e.get("date")
        and e.get("schedule", "").lower().startswith("every")
    ]
    if undated_weekly:
        fail("{} weekly club runs have no concrete date, e.g. {}".format(
            len(undated_weekly), undated_weekly[0]["name"]))

    # Unescaped markup surviving into a text field means strip_html missed it.
    for event in events:
        for field in ("name", "desc", "location", "distances", "org"):
            value = event.get(field) or ""
            if "<" in value or ">" in value:
                fail("raw markup in {} of {!r}: {!r}".format(field, event["name"], value))
                break

    no_url = [e for e in events if not e.get("url")]
    if len(no_url) > count * 0.15:
        warn("{} events have no link ({:.0%})".format(len(no_url), len(no_url) / count))

    return events


def check_affiliate(events, platforms):
    """Per-platform coverage: every link on a monetisable domain must carry the
    tag once that platform is enabled."""
    stale = [e for e in events if "raceRefCode=" in (e.get("url") or "")]
    if stale:
        fail("{} links still carry a legacy raceRefCode, which earns nothing "
             "and is stripped on purpose".format(len(stale)))

    for platform in platforms:
        domain = str(platform.get("domain", "")).lower()
        name = platform.get("name") or domain
        if not domain:
            continue

        on_domain = [e for e in events if domain in (e.get("url") or "").lower()]
        if not on_domain:
            continue

        if not (platform.get("enabled") and platform.get("token")):
            warn("{}: {} link(s) untagged and earning nothing — no token set. {}"
                 .format(name, len(on_domain),
                         platform.get("signup") or "no public programme"))
            continue

        needle = "{}=".format(platform.get("param"))
        untagged = [e for e in on_domain if needle not in e["url"]]
        if untagged:
            fail("{}: {} of {} links missing the affiliate tag, e.g. {}".format(
                name, len(untagged), len(on_domain), untagged[0]["name"]))
        else:
            print("OK: {} — all {} links tagged".format(name, len(on_domain)))


def check_html():
    path = os.path.join(PUBLIC, "index.html")
    if not os.path.exists(path):
        return
    with open(path) as handle:
        html = handle.read()

    leftover = re.findall(r"\{\{[A-Z_]+\}\}", html)
    if leftover:
        fail("unreplaced template tokens: {}".format(", ".join(sorted(set(leftover)))))

    if "<article class=\"row\"" not in html:
        fail("index.html contains no event rows")

    if "application/ld+json" not in html:
        warn("no JSON-LD structured data emitted")

    # The page must not load anything from a third party at render time. Only
    # subresource tags count here — outbound <a href> links to race pages are
    # the entire point of the site.
    resources = []
    for tag in re.findall(r"<(?:script|img|link)\b[^>]*>", html, re.I):
        if re.search(r'rel="(?:canonical|alternate)"', tag, re.I):
            continue  # a canonical URL is metadata, not a fetched resource
        match = re.search(r'(?:src|href)="(https?://[^"]+)"', tag, re.I)
        if match:
            resources.append(match.group(1))
    if resources:
        warn("page loads external resources (should be fully self-contained): {}"
             .format(sorted(set(resources))[:3]))

    if "affiliate" not in html.lower():
        fail("affiliate disclosure missing from the page")


def check_calendar():
    """A malformed .ics fails silently in calendar apps, so check the shape."""
    path = os.path.join(PUBLIC, "calendar.ics")
    if not os.path.exists(path):
        return
    with open(path, "rb") as handle:
        raw = handle.read().decode("utf-8")

    lines = raw.split("\r\n")
    if len(lines) < 5:
        fail("calendar.ics is not CRLF terminated")
        return
    long_lines = [l for l in lines if len(l.encode("utf-8")) > 75]
    if long_lines:
        fail("calendar.ics has {} line(s) over 75 octets, e.g. {!r}".format(
            len(long_lines), long_lines[0][:60]))
    for tag in ("VCALENDAR", "VEVENT", "VTIMEZONE"):
        opens = sum(1 for l in lines if l == "BEGIN:" + tag)
        closes = sum(1 for l in lines if l == "END:" + tag)
        if opens != closes:
            fail("calendar.ics has unbalanced {} blocks ({} vs {})".format(
                tag, opens, closes))
    uids = [l for l in lines if l.startswith("UID:")]
    if len(uids) != len(set(uids)):
        fail("calendar.ics has duplicate UIDs — subscribers would see "
             "duplicated events")
    if not uids:
        warn("calendar.ics contains no events")


def check_event_pages(events):
    directory = os.path.join(PUBLIC, "e")
    if not os.path.isdir(directory):
        warn("no per-event pages were generated")
        return
    pages = [d for d in os.listdir(directory)
             if os.path.exists(os.path.join(directory, d, "index.html"))]
    dated = [e for e in events if e.get("date")]
    if len(pages) < len(dated) * 0.9:
        warn("only {} event pages for {} dated events".format(
            len(pages), len(dated)))

    if pages:
        sample = os.path.join(directory, pages[0], "index.html")
        with open(sample) as handle:
            html = handle.read()
        leftover = re.findall(r"\{\{[A-Z_]+\}\}", html)
        if leftover:
            fail("event pages have unreplaced tokens: {}".format(
                ", ".join(sorted(set(leftover)))))
        if "application/ld+json" not in html:
            fail("event pages are missing JSON-LD, which is their whole purpose")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", help="previous events.json to compare against")
    args = parser.parse_args()

    check_files()

    events_path = os.path.join(PUBLIC, "events.json")
    if not os.path.exists(events_path):
        print("FAIL: public/events.json does not exist")
        return 1

    with open(events_path) as handle:
        data = json.load(handle)

    baseline = None
    if args.baseline and os.path.exists(args.baseline):
        try:
            with open(args.baseline) as handle:
                baseline = json.load(handle)
        except ValueError:
            warn("baseline file is not valid JSON, skipping regression check")

    events = check_events(data, baseline)

    config_path = os.path.join(ROOT, "data", "config.yml")
    platforms = []
    if os.path.exists(config_path):
        import yaml
        with open(config_path) as handle:
            config = yaml.safe_load(handle) or {}
        platforms = (config.get("affiliate") or {}).get("platforms") or []

    check_affiliate(events, platforms)
    check_html()
    check_calendar()
    check_event_pages(events)

    for message in warnings:
        print("WARN: {}".format(message))
    for message in failures:
        print("FAIL: {}".format(message))

    if failures:
        print("\n{} check(s) failed — not safe to publish".format(len(failures)))
        return 1

    races = sum(1 for e in events if e["type"] == "Race")
    print("\nOK: {} events ({} races), {} warning(s)".format(
        len(events), races, len(warnings)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
