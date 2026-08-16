"""iCalendar feed generation.

Subscribe once and every Seattle race lands in your calendar as the site
updates. This is the one thing a static events site can offer that a runner
keeps using after the first visit.

Notes on the format, all of which matter for Apple Calendar and Google Calendar
to accept the file:

  * Lines must be CRLF terminated and folded at 75 octets.
  * A VTIMEZONE block is required for local times to survive; floating times
    drift for anyone outside Pacific.
  * UIDs must be stable across rebuilds, otherwise every refresh duplicates
    every event in the subscriber's calendar.
"""

from datetime import date, datetime, timedelta

PRODID = "-//Run206//Seattle running events//EN"

# America/Los_Angeles, expressed once so calendar clients resolve local times
# themselves rather than trusting us to have done the arithmetic.
VTIMEZONE = """BEGIN:VTIMEZONE
TZID:America/Los_Angeles
X-LIC-LOCATION:America/Los_Angeles
BEGIN:DAYLIGHT
TZOFFSETFROM:-0800
TZOFFSETTO:-0700
TZNAME:PDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0700
TZOFFSETTO:-0800
TZNAME:PST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE"""

DEFAULT_START = (9, 0)      # events with no stated time
DEFAULT_DURATION_HOURS = 2


def _escape(text):
    """RFC 5545 text escaping: backslash, semicolon, comma, newline."""
    if not text:
        return ""
    return (str(text)
            .replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\r\n", "\\n")
            .replace("\n", "\\n"))


def _fold(line):
    """Fold to 75 octets, continuation lines prefixed with a single space."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    chunks = []
    start = 0
    limit = 75
    while start < len(raw):
        end = min(start + limit, len(raw))
        # Back off while the split point lands inside a multi-byte character.
        # The test is on the byte *at* `end` — a continuation byte there means
        # the character started earlier and would be cut in half.
        while end > start + 1 and end < len(raw) and (raw[end] & 0xC0) == 0x80:
            end -= 1
        chunks.append(raw[start:end].decode("utf-8"))
        start = end
        limit = 74
    return "\r\n ".join(chunks)


def _parse_time(text):
    """'6:30 PM' -> (18, 30). Returns None when unparseable."""
    if not text:
        return None
    cleaned = str(text).strip().upper().replace(".", "")
    meridiem = None
    for suffix in ("AM", "PM"):
        if cleaned.endswith(suffix):
            meridiem = suffix
            cleaned = cleaned[:-2].strip()
            break
    parts = cleaned.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return None
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    if meridiem == "PM" and hour < 12:
        hour += 12
    elif meridiem == "AM" and hour == 12:
        hour = 0
    return hour, minute


def build(events, domain, name="Run206", description="Seattle running events"):
    """Render an iCalendar document for the given events."""
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:" + PRODID,
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:" + _escape(name),
        "X-WR-CALDESC:" + _escape(description),
        "X-WR-TIMEZONE:America/Los_Angeles",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
    ]
    lines.extend(VTIMEZONE.split("\n"))

    for event in events:
        if not event.get("date"):
            continue        # undated recurring runs have nothing to anchor to
        try:
            day = date.fromisoformat(event["date"])
        except (ValueError, TypeError):
            continue

        clock = _parse_time(event.get("time")) or DEFAULT_START
        start = datetime(day.year, day.month, day.day, clock[0], clock[1])
        end = start + timedelta(hours=DEFAULT_DURATION_HOURS)

        summary = event["name"]
        if event.get("type") and event["type"] != "Race":
            summary = "{} ({})".format(summary, event["type"])

        body = []
        if event.get("org"):
            body.append(event["org"])
        if event.get("distances"):
            body.append(event["distances"])
        if event.get("price"):
            body.append(event["price"])
        if event.get("desc"):
            body.append(event["desc"])
        if event.get("url"):
            body.append(event["url"])

        lines.extend([
            "BEGIN:VEVENT",
            # Stable across rebuilds: same event, same UID, no duplicates on
            # the subscriber's side.
            "UID:{}@{}".format(event["id"], domain),
            "DTSTAMP:" + stamp,
            "DTSTART;TZID=America/Los_Angeles:" + start.strftime("%Y%m%dT%H%M%S"),
            "DTEND;TZID=America/Los_Angeles:" + end.strftime("%Y%m%dT%H%M%S"),
            "SUMMARY:" + _escape(summary),
        ])
        if body:
            lines.append("DESCRIPTION:" + _escape("\n".join(body)))
        if event.get("location"):
            lines.append("LOCATION:" + _escape(event["location"]))
        if event.get("url"):
            lines.append("URL:" + _escape(event["url"]))
        lines.append("CATEGORIES:" + _escape(event.get("type", "Race")))
        lines.append("STATUS:CONFIRMED")
        lines.append("TRANSP:TRANSPARENT")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
