#!/usr/bin/env python3
"""Find dead links in the hand-maintained data.

    python3 scripts/linkcheck.py [--json]

Only checks `data/clubs.yml` and `data/races-manual.yml`. API-sourced links
look after themselves — a race that disappears from RunSignUp simply stops
being listed. Hand-entered URLs are the ones that rot silently, and the
spreadsheet's Seattle Marathon link had already 404'd before anyone noticed.

Run weekly from CI; failures become one GitHub issue rather than 30.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import yaml  # noqa: E402

from lib.util import USER_AGENT  # noqa: E402

DELAY_SECONDS = 1.0
TIMEOUT = 20

# Sites that refuse non-browser clients. A block is not a dead link, and
# reporting one as broken trains you to ignore the report.
KNOWN_BOT_BLOCKERS = ("rei.com", "nike.com", "lululemon.com", "instagram.com",
                      "brooksrunning.com", "facebook.com")


def check(url):
    """Return (ok, note). Tries HEAD, falls back to GET."""
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(
            url, method=method, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return True, str(response.status)
        except urllib.error.HTTPError as exc:
            # A redirect means the link works. Python 3.8's urllib doesn't
            # follow 308, so it surfaces here as an error rather than being
            # resolved — treat any 3xx as fine.
            if 300 <= exc.code < 400:
                return True, "redirect {}".format(exc.code)
            if exc.code in (403, 405, 429) and method == "HEAD":
                continue     # some servers reject HEAD specifically
            return False, "HTTP {}".format(exc.code)
        except urllib.error.URLError as exc:
            return False, str(exc.reason)
        except Exception as exc:                     # noqa: BLE001
            return False, exc.__class__.__name__
    return False, "unreachable"


def collect():
    urls = {}
    for filename, label in (("clubs.yml", "club"), ("races-manual.yml", "race")):
        path = os.path.join(ROOT, "data", filename)
        if not os.path.exists(path):
            continue
        with open(path) as handle:
            entries = yaml.safe_load(handle) or []
        for entry in entries:
            url = (entry or {}).get("url")
            if not url or not str(url).startswith("http"):
                continue
            name = "{} ({})".format(entry.get("name", "?"),
                                    entry.get("club") or entry.get("org") or label)
            urls.setdefault(url, []).append(name)
    return urls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    urls = collect()
    broken = []
    skipped = []

    for index, (url, owners) in enumerate(sorted(urls.items())):
        if any(host in url for host in KNOWN_BOT_BLOCKERS):
            skipped.append((url, owners))
            continue
        if index:
            time.sleep(DELAY_SECONDS)
        ok, note = check(url)
        if not ok:
            broken.append({"url": url, "reason": note, "used_by": owners})

    if args.json:
        print(json.dumps({"checked": len(urls), "broken": broken,
                          "skipped": len(skipped)}, indent=1))
    else:
        print("checked {} unique links ({} skipped as known bot-blockers)".format(
            len(urls), len(skipped)))
        for item in broken:
            print("\nBROKEN  {}".format(item["url"]))
            print("        {}".format(item["reason"]))
            for owner in item["used_by"]:
                print("        used by: {}".format(owner))
        if not broken:
            print("\nAll hand-maintained links resolve.")

    # Dead links are a maintenance signal, not a build failure — the site is
    # still perfectly usable with one stale URL on it.
    return 0


if __name__ == "__main__":
    sys.exit(main())
