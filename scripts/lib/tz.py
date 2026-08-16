"""Pacific-time conversion without a hard dependency on tzdata.

CI runs Python 3.11 where zoneinfo works, but the local machine is on 3.8 where
it doesn't exist. Rather than pin a dependency for one conversion, fall back to
the US DST rule, which has been stable since 2007:

    DST starts  second Sunday in March at 02:00 local
    DST ends    first Sunday in November at 02:00 local
"""

from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    _PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:
    _PACIFIC = None


def _nth_weekday(year, month, weekday, n):
    """Date of the nth `weekday` (Mon=0) in a month."""
    first = datetime(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _is_pdt(moment):
    """True if `moment` (naive UTC) falls in Pacific Daylight Time."""
    year = moment.year
    start = _nth_weekday(year, 3, 6, 2) + timedelta(hours=10)   # 02:00 PST = 10:00 UTC
    end = _nth_weekday(year, 11, 6, 1) + timedelta(hours=9)     # 02:00 PDT = 09:00 UTC
    return start <= moment < end


def from_epoch_ms(millis):
    """Epoch milliseconds -> naive Pacific-local datetime."""
    if millis is None:
        return None
    try:
        millis = float(millis)
    except (TypeError, ValueError):
        return None
    if millis > 1e11:
        millis = millis / 1000.0

    utc = datetime(1970, 1, 1) + timedelta(seconds=millis)

    if _PACIFIC is not None:
        from datetime import timezone
        return (utc.replace(tzinfo=timezone.utc)
                   .astimezone(_PACIFIC)
                   .replace(tzinfo=None))

    return utc - timedelta(hours=7 if _is_pdt(utc) else 8)


def format_time(moment):
    """datetime -> '6:30 PM'."""
    if not moment:
        return ""
    return "{}:{:02d} {}".format(
        moment.hour % 12 or 12, moment.minute,
        "AM" if moment.hour < 12 else "PM")
