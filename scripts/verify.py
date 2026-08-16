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

REQUIRED_FILES = ["index.html", "events.json", "sitemap.xml", "robots.txt", "CNAME"]

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


def check_affiliate(events, token):
    runsignup = [e for e in events if "runsignup.com" in (e.get("url") or "")]
    if not runsignup:
        warn("no RunSignUp links found at all — is the API source working?")
        return

    if not token:
        warn("no affiliate token configured, so {} RunSignUp links are untagged "
             "and will earn nothing. Set affiliate.runsignup_token in "
             "data/config.yml once approved at runsignup.com/affiliate."
             .format(len(runsignup)))
        return

    untagged = [e for e in runsignup if "affiliateToken=" not in e["url"]]
    if untagged:
        fail("{} RunSignUp links missing the affiliate token, e.g. {}".format(
            len(untagged), untagged[0]["name"]))

    stale = [e for e in events if "raceRefCode=" in (e.get("url") or "")]
    if stale:
        fail("{} links still carry a legacy raceRefCode, which earns nothing"
             .format(len(stale)))


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
    token = ""
    if os.path.exists(config_path):
        import yaml
        with open(config_path) as handle:
            config = yaml.safe_load(handle) or {}
        token = (config.get("affiliate") or {}).get("runsignup_token") or ""

    check_affiliate(events, token)
    check_html()

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
