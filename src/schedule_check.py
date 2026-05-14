from __future__ import annotations

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _parse_minutes(t: str) -> int:
    """Convert 'HH:MM' to total minutes since midnight."""
    h, m = (int(x) for x in t.split(":"))
    return h * 60 + m


def _now_in_tz(timezone_name: str):
    """Return current datetime in the given IANA timezone (falls back to local time)."""
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        return datetime.now(ZoneInfo(timezone_name))
    except Exception:
        from datetime import datetime
        return datetime.now()


def is_dark_time(dark_periods: list, timezone_name: str = "Europe/Copenhagen") -> tuple[bool, str]:
    """
    Returns (True, reason) if the current time falls inside an enabled dark period,
    otherwise (False, "").  Supports overnight ranges (e.g. 22:00–06:00).
    Timezone-aware when zoneinfo is available (Python 3.9+).
    """
    now = _now_in_tz(timezone_name)
    day_name = WEEKDAYS[now.weekday()]
    current = now.hour * 60 + now.minute

    for period in dark_periods:
        if not period.get("enabled", True):
            continue
        day = period.get("day", "all")
        if day != "all" and day != day_name:
            continue

        start = _parse_minutes(period.get("start", "00:00"))
        end   = _parse_minutes(period.get("end",   "00:00"))

        if start == end:
            continue

        if start < end:
            # Same-day range  e.g. 08:00–18:00
            in_range = start <= current < end
        else:
            # Overnight range  e.g. 22:00–06:00
            in_range = current >= start or current < end

        if in_range:
            label = period.get("label") or f"{period.get('day','alle dage')} {period.get('start')}–{period.get('end')}"
            return True, label

    return False, ""
