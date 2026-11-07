"""Integrations module for Life Inbox.

Provides connectors for:
- Google Calendar & RFC 5545 iCalendar (.ics) exports
- Outbound Webhooks for Slack & Discord
- External Issue links for GitHub and Linear
- Natural date/timing parsing for tasks
"""

from datetime import datetime, timedelta, timezone
import re
from typing import Optional, Tuple
import urllib.parse
import uuid

import requests


def parse_timing_to_datetime(timing_text: Optional[str]) -> Tuple[datetime, datetime]:
    """Parse timing description into start and end datetimes in UTC.

    Defaults to tomorrow at 09:00 UTC if unspecified or ambiguous.
    """
    now = datetime.now(timezone.utc)
    base_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    if not timing_text:
        start = base_time + timedelta(days=1)
        return start, start + timedelta(hours=1)

    cl = timing_text.lower().strip()

    if "today" in cl:
        start = base_time
    elif "tomorrow" in cl:
        start = base_time + timedelta(days=1)
    elif "this weekend" in cl or "saturday" in cl:
        days_ahead = (5 - now.weekday()) % 7 or 7
        start = (now + timedelta(days=days_ahead)).replace(hour=10, minute=0, second=0)
    elif "next week" in cl or "next monday" in cl or "monday" in cl:
        days_ahead = (0 - now.weekday()) % 7 or 7
        start = (now + timedelta(days=days_ahead)).replace(hour=9, minute=0, second=0)
    elif "friday" in cl:
        days_ahead = (4 - now.weekday()) % 7 or 7
        start = (now + timedelta(days=days_ahead)).replace(hour=14, minute=0, second=0)
    else:
        # Match explicit month / day e.g. "sep 15", "oct 22", "nov 1"
        m = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*(\d{1,2})", cl)
        if m:
            month_map = {
                "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
            }
            mon = month_map.get(m.group(1)[:3], now.month)
            day = int(m.group(2))
            year = now.year if mon >= now.month else now.year + 1
            try:
                start = datetime(year, mon, day, 10, 0, tzinfo=timezone.utc)
            except ValueError:
                start = base_time + timedelta(days=1)
        else:
            start = base_time + timedelta(days=1)

    end = start + timedelta(hours=1)
    return start, end


def generate_google_calendar_url(title: str, details: str, start_dt: datetime, end_dt: datetime) -> str:
    """Build a direct 1-click Google Calendar Event creation URL."""
    fmt = "%Y%m%dT%H%M%SZ"
    dates_param = f"{start_dt.strftime(fmt)}/{end_dt.strftime(fmt)}"
    params = {
        "action": "TEMPLATE",
        "text": title,
        "details": details,
        "dates": dates_param,
    }
    return f"https://calendar.google.com/calendar/render?{urllib.parse.urlencode(params)}"


def generate_ics_calendar(
    title: str,
    details: str,
    start_dt: datetime,
    end_dt: datetime,
    uid: Optional[str] = None,
) -> str:
    """Generate RFC 5545 iCalendar content for Apple Calendar, Outlook, and Google Calendar."""
    fmt = "%Y%m%dT%H%M%SZ"
    dtstamp = datetime.now(timezone.utc).strftime(fmt)
    dtstart = start_dt.strftime(fmt)
    dtend = end_dt.strftime(fmt)
    event_uid = uid or f"{uuid.uuid4()}@lifeinbox.app"

    # Sanitize title and details for ICS text
    clean_title = title.replace("\n", " ").replace(";", "\\;")
    clean_details = details.replace("\n", "\\n").replace(";", "\\;")

    ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Life Inbox//AI Executive Assistant//EN\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "METHOD:PUBLISH\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{event_uid}\r\n"
        f"DTSTAMP:{dtstamp}\r\n"
        f"DTSTART:{dtstart}\r\n"
        f"DTEND:{dtend}\r\n"
        f"SUMMARY:{clean_title}\r\n"
        f"DESCRIPTION:{clean_details}\r\n"
        "STATUS:CONFIRMED\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    return ics


def generate_github_issue_url(title: str, body: str, repo: str = "saisidhardy/life-inbox") -> str:
    """Build URL to create a new pre-filled GitHub issue."""
    params = {
        "title": title,
        "body": body,
        "labels": "task,life-inbox",
    }
    return f"https://github.com/{repo}/issues/new?{urllib.parse.urlencode(params)}"


def generate_linear_issue_url(title: str, description: str) -> str:
    """Build URL to draft a new Linear issue."""
    params = {
        "title": title,
        "description": description,
    }
    return f"https://linear.app/new?{urllib.parse.urlencode(params)}"


def dispatch_outbound_webhook(
    webhook_url: str,
    title: str,
    message: str,
    fields: Optional[dict] = None,
    timeout: int = 5,
) -> Tuple[bool, int, str]:
    """Send an outbound notification to Slack, Discord, or generic webhook."""
    is_discord = "discord.com" in webhook_url.lower()

    if is_discord:
        payload = {
            "content": f"**[Life Inbox] {title}**\n{message}",
        }
        if fields:
            embed_fields = [{"name": str(k), "value": str(v), "inline": True} for k, v in fields.items()]
            payload["embeds"] = [
                {
                    "title": title,
                    "description": message,
                    "color": 3447003,
                    "fields": embed_fields,
                }
            ]
    else:
        # Slack / standard webhook format
        text = f"*{title}*\n{message}"
        if fields:
            field_text = "\n".join(f"• *{k}*: {v}" for k, v in fields.items())
            text += f"\n\n{field_text}"
        payload = {
            "text": text,
        }

    try:
        resp = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        dest = "discord" if is_discord else "slack_or_generic"
        return resp.status_code in (200, 204), resp.status_code, dest
    except Exception as exc:
        return False, 500, str(exc)
