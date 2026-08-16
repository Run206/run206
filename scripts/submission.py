#!/usr/bin/env python3
"""Turn a submitted GitHub issue into a clubs.yml entry.

    python3 scripts/submission.py --body-file issue.md --number 42

Reads the rendered issue-form body, validates it, and appends an entry to
data/clubs.yml. The workflow then opens a pull request, so nothing reaches the
site without review.

Issue forms render as `### Label` followed by the value, with the literal string
`_No response_` for skipped optional fields.
"""

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import yaml  # noqa: E402

CLUBS = os.path.join(ROOT, "data", "clubs.yml")

DAYS = ["monday", "tuesday", "wednesday", "thursday",
        "friday", "saturday", "sunday"]

# Anything that looks like an attempt to inject markup or a script rather than
# describe a run. Submissions are public input that ends up in a static page.
SUSPICIOUS = re.compile(r"<\s*script|javascript:|data:text/html|on\w+\s*=", re.I)


def parse_sections(body):
    """Split a rendered issue-form body into {heading: value}."""
    sections = {}
    current = None
    buffer = []

    for line in (body or "").replace("\r\n", "\n").split("\n"):
        heading = re.match(r"^###\s+(.*?)\s*$", line)
        if heading:
            if current:
                sections[current] = "\n".join(buffer).strip()
            current = heading.group(1).strip().lower()
            buffer = []
        elif current:
            buffer.append(line)
    if current:
        sections[current] = "\n".join(buffer).strip()

    return {k: ("" if v == "_No response_" else v) for k, v in sections.items()}


def checked_days(value):
    """Issue-form checkboxes render as '- [x] Monday'."""
    found = []
    for line in (value or "").split("\n"):
        match = re.match(r"^\s*-\s*\[[xX]\]\s*(.+?)\s*$", line)
        if match and match.group(1).strip().lower() in DAYS:
            found.append(match.group(1).strip().lower())
    return found


def normalise_time(value):
    """Accept '18:30', '6:30 PM', '6.30pm' -> '18:30'. None if unusable."""
    if not value:
        return None
    text = value.strip().upper().replace(".", ":")
    meridiem = None
    for suffix in ("AM", "PM"):
        if suffix in text:
            meridiem = suffix
            text = text.replace(suffix, "").strip()
            break
    match = re.match(r"^(\d{1,2})(?::(\d{2}))?$", text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if meridiem == "PM" and hour < 12:
        hour += 12
    elif meridiem == "AM" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return "{:02d}:{:02d}".format(hour, minute)


def clean(value, limit=300):
    text = re.sub(r"\s+", " ", (value or "").strip())
    return text[:limit]


def build_entry(sections):
    """Returns (entry_dict, [problems])."""
    problems = []

    name = clean(sections.get("event name"), 120)
    club = clean(sections.get("club, shop, or brand"), 120)
    location = clean(sections.get("meeting point"), 160)

    for label, value in (("Event name", name), ("Club", club),
                         ("Meeting point", location)):
        if not value:
            problems.append("{} is required".format(label))

    blob = " ".join(str(v) for v in sections.values())
    if SUSPICIOUS.search(blob):
        problems.append("submission contains markup or script-like content")

    url = clean(sections.get("link"), 300)
    if url and not re.match(r"^https?://[^\s<>\"]+$", url):
        problems.append("link must be a plain http(s) URL")
        url = ""

    kind = clean(sections.get("what kind of event is this?"), 40) or "Club Run"
    if kind not in ("Club Run", "Brand Event"):
        kind = "Club Run"

    entry = {
        "name": name,
        "club": club,
        "type": kind,
        "location": location,
    }

    weekly = (sections.get("how often does it happen?") or "").lower().startswith(
        "every week")
    days = checked_days(sections.get("which day(s)?"))
    time_value = normalise_time(sections.get("start time"))

    if weekly and days:
        entry["cadence"] = "weekly"
        entry["days"] = days
        if time_value:
            entry["time"] = time_value
        else:
            entry["time_text"] = clean(sections.get("start time"), 40) or "Evening"
    else:
        entry["cadence"] = "irregular"
        schedule = clean(sections.get("schedule, in words"), 120)
        if not schedule:
            if weekly and not days:
                problems.append(
                    "marked weekly but no day was ticked — either tick a day or "
                    "describe the schedule in words")
            schedule = "Varies - see the link"
        entry["schedule"] = schedule
        if sections.get("start time"):
            entry["time_text"] = clean(sections.get("start time"), 40)

    for key, source, limit in (
        ("distances", "distance or format", 80),
        ("desc", "short description", 220),
        ("instagram", "instagram handle", 40),
    ):
        value = clean(sections.get(source), limit)
        if value:
            entry[key] = value

    entry["url"] = url or None
    entry["price"] = clean(sections.get("cost"), 40) or "Free"
    return entry, problems


def is_duplicate(entry, existing):
    for other in existing or []:
        if (str(other.get("name", "")).strip().lower() == entry["name"].strip().lower()
                and str(other.get("club", "")).strip().lower()
                == entry["club"].strip().lower()):
            return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--body-file", required=True)
    parser.add_argument("--number", default="")
    args = parser.parse_args()

    with open(args.body_file) as handle:
        body = handle.read()

    entry, problems = build_entry(parse_sections(body))

    with open(CLUBS) as handle:
        existing = yaml.safe_load(handle) or []

    if not problems and is_duplicate(entry, existing):
        problems.append("an entry with this name and club already exists")

    if problems:
        print("REJECTED")
        for problem in problems:
            print("- {}".format(problem))
        return 1

    lines = ["", "# Submitted via issue #{}".format(args.number) if args.number
             else "# Submitted via the website form"]
    block = yaml.safe_dump([entry], sort_keys=False, allow_unicode=True,
                           default_flow_style=False, width=88)
    lines.append(block.rstrip("\n"))

    with open(CLUBS, "a") as handle:
        handle.write("\n".join(lines) + "\n")

    print("ACCEPTED")
    print(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
