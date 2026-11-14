import re
from datetime import date, datetime, time, timedelta

from django.utils import timezone


MEETING_TERMS = re.compile(
    r"\b(meet(?:ing)?|appointment|interview|conference|webinar|calendar invite|schedule|"
    r"scheduled|stand[- ]?up|sync(?:-up)?|call|presentation|reminder)\b",
    re.IGNORECASE,
)
MONTHS = {name.lower(): number for number, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1
)}
MONTH_PATTERN = "|".join(MONTHS)
WEEKDAYS = {name.lower(): index for index, name in enumerate(
    ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
)}


def _find_date(text, reference_date):
    match = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", text)
    if match:
        try:
            return date(*(int(part) for part in match.groups()))
        except ValueError:
            return None

    match = re.search(rf"\b({MONTH_PATTERN})\s+(\d{{1,2}})(?:,?\s+(20\d{{2}}))?\b", text, re.IGNORECASE)
    if match:
        month, day, year = match.groups()
        try:
            result = date(int(year or reference_date.year), MONTHS[month.lower()], int(day))
            if not year and result < reference_date:
                result = result.replace(year=result.year + 1)
            return result
        except ValueError:
            return None

    match = re.search(rf"\b(\d{{1,2}})\s+({MONTH_PATTERN})(?:,?\s+(20\d{{2}}))?\b", text, re.IGNORECASE)
    if match:
        day, month, year = match.groups()
        try:
            result = date(int(year or reference_date.year), MONTHS[month.lower()], int(day))
            if not year and result < reference_date:
                result = result.replace(year=result.year + 1)
            return result
        except ValueError:
            return None

    match = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(20\d{2}))?\b", text)
    if match:
        month, day, year = match.groups()
        try:
            result = date(int(year or reference_date.year), int(month), int(day))
            if not year and result < reference_date:
                result = result.replace(year=result.year + 1)
            return result
        except ValueError:
            return None

    lower = text.lower()
    if re.search(r"\btomorrow\b|\btonight\b", lower):
        return reference_date + (timedelta(days=1) if "tomorrow" in lower else timedelta())
    if re.search(r"\btoday\b", lower):
        return reference_date
    for weekday, index in WEEKDAYS.items():
        if re.search(rf"\b{weekday}\b", lower):
            delta = (index - reference_date.weekday()) % 7
            if delta == 0 or re.search(rf"\bnext\s+{weekday}\b", lower):
                delta = delta or 7
            return reference_date + timedelta(days=delta)
    return None


def _find_time(text):
    match = re.search(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b", text, re.IGNORECASE)
    if match:
        hour, minute, marker = match.groups()
        hour, minute = int(hour), int(minute or 0)
        marker = marker.lower().replace(".", "")
        if not 1 <= hour <= 12 or minute > 59:
            return None
        if marker == "pm" and hour != 12:
            hour += 12
        elif marker == "am" and hour == 12:
            hour = 0
        return time(hour, minute)
    match = re.search(r"\b(?:at\s+)?([01]?\d|2[0-3]):([0-5]\d)\b", text)
    return time(int(match.group(1)), int(match.group(2))) if match else None


def detect_meeting_time(email, client_tz=None):
    text = f"{email.subject or ''}\n{email.body_text or ''}"
    if not MEETING_TERMS.search(text):
        return None
    received_at = timezone.localtime(email.received_at, client_tz)
    event_date = _find_date(text, received_at.date())
    event_time = _find_time(text)
    if event_date is None and event_time is None:
        return None
    all_day = event_time is None
    start_at = timezone.make_aware(
        datetime.combine(event_date or received_at.date(), event_time or time(9, 0)),
        received_at.tzinfo,
    )
    if event_date is None and start_at <= received_at:
        start_at += timedelta(days=1)
    return {
        "email_id": email.id,
        "title": email.subject or "Meeting from email",
        "sender_name": email.sender_name,
        "sender_email": email.sender_email,
        "snippet": email.snippet or (email.body_text or "")[:180],
        "start_at": start_at.isoformat(),
        "all_day": all_day,
        "has_date": event_date is not None,
        "has_time": event_time is not None,
        "received_at": email.received_at.isoformat(),
    }
