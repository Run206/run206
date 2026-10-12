"""Expand weekly club-run rules into concrete dates.

This is what turns "Every Monday 6:30 PM" into "Mon 17 Aug, 6:30 PM" so a club
run can sort and filter next to a race instead of being an unsortable string.

Deliberately conservative: only `cadence: weekly` entries get real dates.
Anything biweekly, monthly, or vague stays undated and is surfaced with its own
schedule text. Guessing which Sunday a twice-monthly run falls on would send
people to a park on the wrong day.
"""

from datetime import timedelta

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _next_weekday(start, weekday):
    """First date on/after `start` falling on `weekday`."""
    return start + timedelta(days=(weekday - start.weekday()) % 7)


def _week_of_month(day):
    """1 for the 1st–7th, 2 for the 8th–14th … i.e. "the Nth Tuesday"."""
    return (day.day - 1) // 7 + 1


def _rotation_for(entry, day):
    """Pick the `rotation` slot that covers this date, if the entry has one.

    Some clubs keep a fixed day and time but move the meeting point by week of
    the month — Orca Run Club is Sammamish on the 1st Tuesday, West Seattle on
    the 2nd, Renton on the 3rd. One location string would be wrong three weeks
    in four, so each slot carries its own `location` (and optional `desc`).
    A slot can also say `geocode: false` for "somewhere new, announced on
    Strava" weeks, which have a real date but nowhere to put a pin.
    """
    slots = entry.get("rotation") or []
    week = _week_of_month(day)
    for slot in slots:
        weeks = slot.get("weeks") or []
        if week in [int(w) for w in weeks]:
            return slot
    return None


def format_time(value):
    """'18:30' -> '6:30 PM'. Returns '' for unparseable input."""
    if not value:
        return ""
    try:
        hour_s, minute_s = str(value).split(":")[:2]
        hour, minute = int(hour_s), int(minute_s)
    except (ValueError, TypeError):
        return ""
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    return "{}:{:02d} {}".format(display_hour, minute, suffix)


def expand(entry, start, weeks_ahead):
    """Expand one clubs.yml entry into a list of occurrence dicts.

    Weekly entries yield one dict per occurrence. Irregular entries yield a
    single undated dict carrying `schedule` text.
    """
    base = {
        "name": entry.get("name", ""),
        "org": entry.get("club", ""),
        "type": entry.get("type", "Club Run"),
        "location": entry.get("location", ""),
        "distances": entry.get("distances", ""),
        "desc": entry.get("desc", ""),
        "url": entry.get("url") or "",
        "instagram": entry.get("instagram", ""),
        "price": entry.get("price", "Free"),
        "source": "manual",
        "recurring": True,
    }

    if entry.get("cadence") != "weekly":
        undated = dict(base)
        undated.update({
            "date": None,
            "time": entry.get("time_text", "") or "",
            "schedule": entry.get("schedule", ""),
            "cadence": "irregular",
        })
        return [undated]

    days = entry.get("days") or []
    time_display = format_time(entry.get("time")) or entry.get("time_text", "")
    cadence_label = _weekly_label(days)

    occurrences = []
    horizon = start + timedelta(weeks=weeks_ahead)
    for day_name in days:
        weekday = WEEKDAYS.get(str(day_name).strip().lower())
        if weekday is None:
            continue
        cursor = _next_weekday(start, weekday)
        while cursor <= horizon:
            occurrence = dict(base)
            occurrence.update({
                "date": cursor.isoformat(),
                "time": time_display,
                "sort_time": entry.get("time") or "23:59",
                "schedule": cadence_label,
                "cadence": "weekly",
            })
            slot = _rotation_for(entry, cursor)
            if slot:
                for field in ("location", "desc", "distances"):
                    if slot.get(field):
                        occurrence[field] = slot[field]
                if slot.get("geocode") is False:
                    occurrence["no_geocode"] = True
            occurrences.append(occurrence)
            cursor += timedelta(days=7)
    return occurrences


def _weekly_label(days):
    if not days:
        return "Weekly"
    names = [str(d)[:3].capitalize() for d in days]
    if len(names) == 1:
        return "Every {}".format(names[0])
    return "Every " + " & ".join(names)
