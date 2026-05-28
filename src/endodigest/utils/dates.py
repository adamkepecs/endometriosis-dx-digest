from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_stamp() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%SZ")


def today_in_timezone(tz_name: str) -> date:
    return datetime.now(ZoneInfo(tz_name)).date()


def iso_today() -> str:
    return utc_now().date().isoformat()


def parse_date(value: object) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y"):
        try:
            parsed = datetime.strptime(text[: len(fmt)], fmt)
            if fmt == "%Y":
                return date(parsed.year, 1, 1)
            if fmt == "%Y-%m":
                return date(parsed.year, parsed.month, 1)
            return parsed.date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def date_window(*, lookback_days: int | None, backfill_days: int | None, tz_name: str) -> tuple[date, date]:
    end = today_in_timezone(tz_name)
    days = backfill_days if backfill_days is not None else lookback_days
    if days is None:
        days = 10
    return end - timedelta(days=max(0, int(days))), end


def pubmed_date(value: date) -> str:
    return value.strftime("%Y/%m/%d")
