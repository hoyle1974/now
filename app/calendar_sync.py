"""Pure ICS parsing, diffing and fetch for the calendar item type: no DB
(`app/calendar_jobs.py` orchestrates fetch → parse → write)."""
from __future__ import annotations

import datetime
import html
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from app import models


log = logging.getLogger(__name__)

DOWNLOAD_ERROR = "Could not download calendar"
MAX_SYNC_ERROR_LEN = 500
MAX_REDIRECTS = 3


def _download_error(detail: str) -> CalendarSyncError:
    """A fetch failure the viewer can show: the stable prefix plus why."""
    detail = " ".join(str(detail).split())
    msg = f"{DOWNLOAD_ERROR}: {detail}" if detail else DOWNLOAD_ERROR
    return CalendarSyncError(msg[:MAX_SYNC_ERROR_LEN])


class CalendarSyncError(Exception):
    """The feed could not be fetched or parsed."""


@dataclass(frozen=True)
class ParsedEvent:
    external_uid: str
    title: str
    due_date: datetime.datetime  # naive; all-day events are midnight (matches due-time.md convention)
    location: str | None = None
    end_date: datetime.datetime | None = None  # naive like due_date; None when the feed gives no end
    notes: str | None = None
    repeat_summary: str | None = None
    conference_url: str | None = None
    attendees: tuple[models.Attendee, ...] = ()

    def todo_fields(self) -> dict:
        """The calendar_event fields a sync owns: what gets written, and what is compared."""
        return {"title": self.title, "due_date": self.due_date, "location": self.location,
                "end_date": self.end_date, "notes": self.notes, "repeat_summary": self.repeat_summary,
                "conference_url": self.conference_url, "attendees": list(self.attendees)}


_DAY_NAMES = {"MO": "Mon", "TU": "Tue", "WE": "Wed", "TH": "Thu", "FR": "Fri", "SA": "Sat", "SU": "Sun"}
_FREQS = {"DAILY": ("Daily", "day"), "WEEKLY": ("Weekly", "week"),
          "MONTHLY": ("Monthly", "month"), "YEARLY": ("Yearly", "year")}
_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", -1: "last"}


def describe_rrule(rule) -> str:
    """An RRULE in words for the viewer ("Weekly on Mon, Wed", "Every 2 weeks",
    "Monthly on the 2nd Tue"). Rare shapes fall back to the plain frequency, or "Repeats"."""
    def first(key, default):
        values = rule.get(key) or [default]
        return values[0] if isinstance(values, list) else values

    freq = str(first("FREQ", "")).upper()
    if freq not in _FREQS:
        return "Repeats"
    interval = int(first("INTERVAL", 1) or 1)
    word, unit = _FREQS[freq]
    head = word if interval == 1 else f"Every {interval} {unit}s"
    days = [str(d).upper() for d in rule.get("BYDAY") or []]
    if not days:
        return head
    parsed = [re.fullmatch(r"([+-]?\d+)?([A-Z]{2})", d) for d in days]
    if not all(m and m.group(2) in _DAY_NAMES for m in parsed):
        return head
    if all(m.group(1) is None for m in parsed):
        if interval == 1 and freq in ("DAILY", "WEEKLY") and set(days) == {"MO", "TU", "WE", "TH", "FR"}:
            return "Every weekday"
        return f"{head} on {', '.join(_DAY_NAMES[m.group(2)] for m in parsed)}"
    if len(parsed) == 1 and int(parsed[0].group(1)) in _ORDINALS:
        return f"{head} on the {_ORDINALS[int(parsed[0].group(1))]} {_DAY_NAMES[parsed[0].group(2)]}"
    return head


# Google Calendar appends its dial-in details between two of these separator lines.
_GOOGLE_INVITE_BLOCK = re.compile(r"-::~[:~]*::-.*?-::~[:~]*::-", re.S)
_MEETING_URL = re.compile(
    r"https://(?:[\w-]+\.)*(?:meet\.google\.com|zoom\.us|teams\.microsoft\.com|teams\.live\.com|webex\.com)"
    r"/[^\s<>\"')\]]+")


def _plain_text(description: str) -> str | None:
    """DESCRIPTION as readable plain text: Google sends HTML and a dial-in block."""
    text = _GOOGLE_INVITE_BLOCK.sub("", description)
    if re.search(r"<[a-zA-Z/][^>]*>", text):
        text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", text)
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n")).strip()
    return text[:models.MAX_NOTES_LEN] or None


def _conference_url(component, texts: list[str]) -> str | None:
    """The video-call link: Google's own property, RFC 7986 CONFERENCE, else the first
    known meeting URL in the location or description."""
    for key in ("X-GOOGLE-CONFERENCE", "CONFERENCE"):
        value = component.get(key)
        for v in value if isinstance(value, list) else [value]:
            url = str(v or "").strip()
            if url.startswith("https://") and len(url) <= models.MAX_URL_LEN:
                return url
    for text in texts:
        match = _MEETING_URL.search(text)
        if match and len(match.group(0)) <= models.MAX_URL_LEN:
            return match.group(0)
    return None


def _email(address) -> str | None:
    value = str(address or "").strip()
    if value.lower().startswith("mailto:"):
        value = value[len("mailto:"):]
    return value or None


def _attendees(component) -> tuple[models.Attendee, ...]:
    """Guests as the feed reports them. Rooms and other resources are left out."""
    raw = component.get("ATTENDEE")
    if raw is None:
        return ()
    organizer = _email(component.get("ORGANIZER"))
    out = []
    for address in raw if isinstance(raw, list) else [raw]:
        params = getattr(address, "params", {})
        email = _email(address)
        if (str(params.get("CUTYPE", "INDIVIDUAL")).upper() in ("RESOURCE", "ROOM")
                or (email or "").endswith("resource.calendar.google.com")):
            continue
        name = str(params.get("CN", "")).strip() or None
        status = str(params.get("PARTSTAT", "NEEDS-ACTION")).lower()
        out.append(models.Attendee(
            name=None if name == email else name,  # Google repeats the email as CN when there is no name
            email=email,
            status=status if status in ("accepted", "declined", "tentative") else "needs-action",
            organizer=bool(email) and (email or "").lower() == (organizer or "").lower(),
        ))
    return tuple(out[:models.MAX_ATTENDEES])


def _wall_clock(value, tz: ZoneInfo) -> datetime.datetime:
    """A DTSTART/DTEND value as this app's floating wall-clock time (see parse_ics)."""
    if not isinstance(value, datetime.datetime):  # a DATE: all-day, midnight
        return datetime.datetime.combine(value, datetime.time(0, 0))
    return value.replace(tzinfo=None) if value.tzinfo is None else value.astimezone(tz).replace(tzinfo=None)


def parse_ics(raw: str, window_start: datetime.date, window_end: datetime.date,
              tz: ZoneInfo | None = None, *, now: datetime.datetime | None = None,
              series_window_end: datetime.date | None = None) -> list[ParsedEvent]:
    """The events to mirror: every one-off event starting in [window_start, window_end),
    plus, for each recurring series, only its *next* occurrence: the earliest one in
    [window_start, series_window_end) that has not ended by `now` (default: midnight
    of window_start). A series is one item that moves forward, not one per occurrence.
    Cancelled events are left out.

    `due_date` is a floating wall-clock time everywhere in this app (see due-time.md and
    app/ics.py's outbound feed), never a UTC instant. A timezone-aware DTSTART is therefore
    converted to `tz`'s (the home timezone's, per app/push.py) wall-clock time, not UTC —
    `tz` defaults to UTC so a floating-time fixture/caller is unaffected (floating times have
    no tzinfo and never go through this conversion at all). `now` is a wall-clock time too."""
    import icalendar
    import recurring_ical_events

    tz = tz or ZoneInfo("UTC")
    now = now or datetime.datetime.combine(window_start, datetime.time(0, 0))
    series_window_end = max(series_window_end or window_end, window_end)

    try:
        cal = icalendar.Calendar.from_ical(raw)
    except Exception as e:
        raise CalendarSyncError(f"could not parse calendar: {e}") from e

    try:
        occurrences = recurring_ical_events.of(cal).between(window_start, series_window_end)
    except Exception as e:
        raise CalendarSyncError(f"could not expand recurrence: {e}") from e

    # Which UIDs are a series, and their rule in words. This is a property of the source
    # VEVENT (does it have an RRULE/RDATE), not of how many occurrences fall in the window.
    # A series' external_uid is its bare UID: it stays put while the series' next occurrence
    # moves forward (or the organizer moves it), so each sync patches the same item in place.
    # (recurring_ical_events, as of 2.2.3, does not set RECURRENCE-ID on expanded
    # occurrences, so we check the original VEVENT instead.)
    series: dict[str, str] = {}
    for component in cal.walk("VEVENT"):
        rrule, rdate = component.get("RRULE"), component.get("RDATE")
        uid = str(component.get("UID", ""))
        if uid and (rrule is not None or rdate is not None):
            rule = rrule[0] if isinstance(rrule, list) else rrule
            series[uid] = describe_rrule(rule) if rule is not None else "Repeats"

    one_offs: list[ParsedEvent] = []
    next_in_series: dict[str, ParsedEvent] = {}
    for occ in occurrences:
        uid = str(occ.get("UID", ""))
        if not uid:
            continue  # an event with no UID can never be matched on the next sync; skip it
        if str(occ.get("STATUS", "")).upper() == "CANCELLED":
            continue
        due = _wall_clock(occ["DTSTART"].dt, tz)
        end = None
        if occ.get("DTEND") is not None:
            end = _wall_clock(occ["DTEND"].dt, tz)
        elif occ.get("DURATION") is not None:
            end = due + occ["DURATION"].dt
        if end is not None and end <= due:
            end = None
        location = str(occ.get("LOCATION", "")).strip() or None
        description = str(occ.get("DESCRIPTION", ""))
        event = ParsedEvent(
            external_uid=uid,
            title=str(occ.get("SUMMARY", "")) or "(untitled event)",
            due_date=due,
            location=location,
            end_date=end,
            notes=_plain_text(description),
            repeat_summary=series.get(uid),
            conference_url=_conference_url(occ, [location or "", description]),
            attendees=_attendees(occ),
        )
        if uid not in series:
            if due.date() < window_end:
                one_offs.append(event)
            continue
        # An all-day occurrence with no end lasts the whole day.
        ends = end or (due + datetime.timedelta(days=1) if due.time() == datetime.time(0, 0) else due)
        if ends > now and (uid not in next_in_series or due < next_in_series[uid].due_date):
            next_in_series[uid] = event
    return one_offs + list(next_in_series.values())


def diff_events(desired: list[ParsedEvent], existing: dict[str, models.Todo],
                ) -> tuple[list[ParsedEvent], list[tuple[str, ParsedEvent]], list[str]]:
    """(to_create, to_update, to_delete_ids). existing is keyed by external_uid.
    to_update pairs the existing todo's id with the new data, only when something changed."""
    desired_by_uid = {e.external_uid: e for e in desired}

    to_create = [e for uid, e in desired_by_uid.items() if uid not in existing]
    to_update = [
        (str(existing[uid].todo_id), e)
        for uid, e in desired_by_uid.items()
        if uid in existing and any(getattr(existing[uid], k) != v for k, v in e.todo_fields().items())
    ]
    to_delete = [str(t.todo_id) for uid, t in existing.items() if uid not in desired_by_uid]
    return to_create, to_update, to_delete


WINDOW_DAYS = 60          # one-off events this far ahead
SERIES_WINDOW_DAYS = 366  # how far to look for a series' next occurrence (a yearly one included)


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.version == 6 and ip.ipv4_mapped is not None:
        return _blocked_ip(ip.ipv4_mapped)
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified)


def _require_public_url(url: str) -> None:
    """Refuse a URL whose host is the metadata server or any non-public address."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in ("http", "https") or not host:
        log.warning("calendar fetch rejected non-http url")
        raise _download_error("not an http(s) URL")
    if host == "metadata.google.internal" or host.endswith(".metadata.google.internal"):
        log.warning("calendar fetch rejected metadata host")
        raise _download_error("metadata host")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(info[4][0].split("%", 1)[0])
                         for info in socket.getaddrinfo(host, None)]
        except socket.gaierror as e:
            log.warning("calendar fetch dns failed: %s", e)
            raise _download_error(f"DNS failed ({e})") from e
    if not addresses or any(_blocked_ip(ip) for ip in addresses):
        log.warning("calendar fetch rejected non-public host %s", host)
        raise _download_error("host is not a public address")


def _http_fetch(url: str) -> str:
    """Download an ICS feed. Redirects are followed one hop at a time, and every hop
    is checked again. The body is not size-capped: a Google secret address returns the
    whole history, and a 2 MB cap rejected a real feed (Cloud Run: exceeded 2097152 bytes)."""
    import requests
    current = url
    for hop in range(MAX_REDIRECTS + 1):
        _require_public_url(current)
        try:
            resp = requests.get(current, timeout=10, allow_redirects=False, stream=True)
        except CalendarSyncError:
            raise
        except Exception as e:
            log.warning("calendar fetch failed: %s", e)
            raise _download_error(e) from e
        try:
            if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location")
                if hop == MAX_REDIRECTS or not location:
                    log.warning("calendar fetch stopped after redirect from %s", current)
                    raise _download_error("too many redirects")
                current = urljoin(current, location)
                continue
            if resp.status_code >= 400:
                raise _download_error(f"HTTP {resp.status_code}")
            body = bytearray()
            for chunk in resp.iter_content(chunk_size=65536):
                body += chunk
            return bytes(body).decode(resp.encoding or "utf-8", errors="replace")
        except CalendarSyncError:
            raise
        except Exception as e:
            log.warning("calendar fetch failed: %s", e)
            raise _download_error(e) from e
        finally:
            resp.close()
    raise _download_error("too many redirects")
