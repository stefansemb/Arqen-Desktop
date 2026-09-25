import base64
import html
import re
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from typing import Any
from urllib.parse import quote, urlencode

from arqen.connectors.google import CALENDAR, DRIVE, GMAIL, google_bytes, google_json
from arqen.tools.base import Tool

_ADDRESS = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
_READ_LIMIT = 8000


def _clip(text: str | None, limit: int = _READ_LIMIT) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _id(arguments: dict[str, Any], name: str) -> str:
    value = str(arguments[name]).strip()
    if not value:
        raise ValueError(f"{name} is empty.")
    return quote(value, safe="")


def _as_int(arguments: dict[str, Any], name: str) -> dict[str, Any]:
    # Models often send numbers as text ("7").
    value = arguments.get(name)
    if isinstance(value, str) and value.strip().isdigit():
        return {**arguments, name: int(value.strip())}
    return arguments


class _GoogleTool(Tool):
    connector_id = "google"

    def _get(self, url: str):
        return google_json("GET", url, self.credentials())


# --- Gmail -------------------------------------------------------------------

def _headers(message: dict) -> dict[str, str]:
    return {item["name"].casefold(): item["value"] for item in message.get("payload", {}).get("headers", [])}


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _body_text(part: dict) -> tuple[str, str, list[str]]:
    """Plain text, HTML and attachment names found anywhere in a message part."""
    plain, rich, attachments = "", "", []
    mime = part.get("mimeType", "")
    data = part.get("body", {}).get("data")
    if part.get("filename"):
        attachments.append(part["filename"])
    elif data and mime == "text/plain":
        plain = _decode(data)
    elif data and mime == "text/html":
        rich = _decode(data)
    for child in part.get("parts", []) or []:
        child_plain, child_rich, child_files = _body_text(child)
        plain, rich = plain or child_plain, rich or child_rich
        attachments.extend(child_files)
    return plain, rich, attachments


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text))


class GmailSearchMessagesTool(_GoogleTool):
    name = "gmail_search_messages"
    description = (
        "Searches the user's Gmail (e-post, mejl, inkorg) and lists up to 10 messages with id, date, "
        "sender, subject and snippet. Uses Gmail search syntax, e.g. 'from:anna is:unread newer_than:7d'; "
        "an empty query lists the newest mail in the inbox."
    )
    arguments_schema = {"query": str}

    def run(self, arguments: dict[str, Any]) -> str:
        query = str(arguments["query"]).strip() or "in:inbox"
        listing = self._get(f"{GMAIL}/messages?" + urlencode({"q": query, "maxResults": 10})) or {}
        ids = [item["id"] for item in listing.get("messages", [])]
        if not ids:
            return "No messages match."
        lines = []
        for message_id in ids:
            message = self._get(
                f"{GMAIL}/messages/{quote(message_id, safe='')}?format=metadata"
                "&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date"
            ) or {}
            headers = _headers(message)
            unread = " (unread)" if "UNREAD" in message.get("labelIds", []) else ""
            lines.append(
                f"[{message_id}] {headers.get('date', '')} · {headers.get('from', '')} · "
                f"{headers.get('subject', '(no subject)')}{unread}\n  {html.unescape(message.get('snippet', ''))}"
            )
        return "\n".join(lines)


class GmailReadMessageTool(_GoogleTool):
    name = "gmail_read_message"
    description = "Reads one Gmail message (mejl) by its id from gmail_search_messages: headers, text and attachment names."
    arguments_schema = {"message_id": str}

    def run(self, arguments: dict[str, Any]) -> str:
        message = self._get(f"{GMAIL}/messages/{_id(arguments, 'message_id')}?format=full") or {}
        headers = _headers(message)
        plain, rich, attachments = _body_text(message.get("payload", {}))
        text = plain or _strip_html(rich) or message.get("snippet", "")
        lines = [
            f"From: {headers.get('from', '')}",
            f"To: {headers.get('to', '')}",
            f"Date: {headers.get('date', '')}",
            f"Subject: {headers.get('subject', '(no subject)')}",
        ]
        if attachments:
            lines.append("Attachments: " + ", ".join(attachments))
        return "\n".join(lines) + "\n\n" + _clip(text)


def _addresses(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,;]", value) if item.strip()]


class GmailCreateDraftTool(_GoogleTool):
    name = "gmail_create_draft"
    description = (
        "Creates an email draft (mejlutkast) in the user's Gmail. Nothing is sent; the user reviews and "
        "sends it from Gmail. 'to' takes one or more addresses separated by commas."
    )
    requires_confirmation = True
    arguments_schema = {"to": str, "subject": str, "body": str}

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        recipients = _addresses(str(arguments["to"]))
        if not recipients:
            return "The draft needs at least one recipient."
        wrong = [item for item in recipients if not _ADDRESS.match(item)]
        if wrong:
            return f"Not an email address: {', '.join(wrong)}"
        return None

    def run(self, arguments: dict[str, Any]) -> str:
        message = EmailMessage()
        message["To"] = ", ".join(_addresses(str(arguments["to"])))
        message["Subject"] = str(arguments["subject"]).strip()
        message.set_content(str(arguments["body"]))
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        draft = google_json("POST", f"{GMAIL}/drafts", self.credentials(), body={"message": {"raw": raw}}) or {}
        return f"Draft saved in Gmail (id {draft.get('id', '?')}). It has not been sent; the user sends it from Gmail's Drafts."


# --- Calendar ----------------------------------------------------------------

def _when(value: dict) -> str:
    if "dateTime" in value:
        return datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    return f"{value.get('date', '')} (all day)"


class CalendarListEventsTool(_GoogleTool):
    name = "calendar_list_events"
    description = (
        "Lists upcoming events (möten, händelser) in the user's primary Google Calendar (kalender) from now "
        "and the given number of days ahead (1–60)."
    )
    arguments_schema = {"days": int}

    def normalize_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return _as_int(arguments, "days")

    def run(self, arguments: dict[str, Any]) -> str:
        days = max(1, min(60, int(arguments["days"])))
        now = datetime.now().astimezone()
        listing = self._get(f"{CALENDAR}/calendars/primary/events?" + urlencode({
            "timeMin": now.isoformat(timespec="seconds"),
            "timeMax": (now + timedelta(days=days)).isoformat(timespec="seconds"),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 25,
        })) or {}
        events = listing.get("items", [])
        if not events:
            return f"No events in the next {days} days."
        lines = []
        for event in events:
            where = f" @ {event['location']}" if event.get("location") else ""
            lines.append(f"{_when(event.get('start', {}))} – {_when(event.get('end', {}))}: "
                         f"{event.get('summary', '(no title)')}{where}")
        return "\n".join(lines)


def _moment(text: str) -> date | datetime:
    """'2026-09-30' (all day) or '2026-09-30T14:00' (local time unless an offset is given)."""
    text = text.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return date.fromisoformat(text)
    moment = datetime.fromisoformat(text.replace("Z", "+00:00").replace(" ", "T", 1))
    return moment if moment.tzinfo else moment.astimezone()


class CalendarCreateEventTool(_GoogleTool):
    name = "calendar_create_event"
    description = (
        "Creates an event (möte, händelse) in the user's primary Google Calendar (kalender). "
        "start and end are local time as YYYY-MM-DDTHH:MM, or YYYY-MM-DD for an all-day event. "
        "description may be empty. Check the current date first if unsure."
    )
    requires_confirmation = True
    arguments_schema = {"title": str, "start": str, "end": str, "description": str}

    @staticmethod
    def _span(arguments: dict[str, Any]) -> tuple[date | datetime, date | datetime]:
        start, end = _moment(str(arguments["start"])), _moment(str(arguments["end"]))
        if isinstance(start, datetime) != isinstance(end, datetime):
            raise ValueError("start and end must both have a time, or both be dates for an all-day event.")
        if isinstance(start, datetime) and end <= start:
            raise ValueError("The event must end after it starts.")
        if not isinstance(start, datetime) and end < start:
            raise ValueError("The event must end on or after its start date.")
        return start, end

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        if not str(arguments["title"]).strip():
            return "The event needs a title."
        try:
            self._span(arguments)
        except ValueError as exc:
            return f"Invalid time: {exc}"
        return None

    def run(self, arguments: dict[str, Any]) -> str:
        start, end = self._span(arguments)
        if isinstance(start, datetime):
            times = {"start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}}
        else:
            # Google's all-day end date is exclusive.
            times = {"start": {"date": start.isoformat()}, "end": {"date": (end + timedelta(days=1)).isoformat()}}
        body = {"summary": str(arguments["title"]).strip(), **times}
        if str(arguments["description"]).strip():
            body["description"] = str(arguments["description"]).strip()
        event = google_json("POST", f"{CALENDAR}/calendars/primary/events", self.credentials(), body=body) or {}
        return f"Event created: {event.get('summary', body['summary'])}, {_when(event.get('start', times['start']))}. {event.get('htmlLink', '')}".strip()


# --- Drive -------------------------------------------------------------------

_EXPORT = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
_TEXT_TYPES = ("application/json", "application/xml", "application/csv", "application/javascript")
_DOWNLOAD_LIMIT = 256 * 1024


class DriveSearchFilesTool(_GoogleTool):
    name = "drive_search_files"
    description = (
        "Searches the user's Google Drive (filer, dokument) by name and content and lists up to 15 files "
        "with id, type and last change. An empty query lists the most recently changed files."
    )
    arguments_schema = {"query": str}

    def run(self, arguments: dict[str, Any]) -> str:
        text = str(arguments["query"]).strip()
        params = {"pageSize": 15, "fields": "files(id,name,mimeType,modifiedTime)"}
        if text:
            escaped = text.replace("\\", "\\\\").replace("'", "\\'")
            # Drive cannot sort full-text results; they come by relevance.
            params["q"] = f"(name contains '{escaped}' or fullText contains '{escaped}') and trashed = false"
        else:
            params.update(q="trashed = false", orderBy="modifiedTime desc")
        files = (self._get(f"{DRIVE}/files?" + urlencode(params)) or {}).get("files", [])
        if not files:
            return "No files match."
        return "\n".join(
            f"[{item['id']}] {item.get('name', '')} — {item.get('mimeType', '').rsplit('.', 1)[-1]}, "
            f"changed {item.get('modifiedTime', '')[:10]}"
            for item in files
        )


class DriveReadFileTool(_GoogleTool):
    name = "drive_read_file"
    description = (
        "Reads the text of a Google Drive file by its id from drive_search_files: Google Docs, Sheets (as CSV), "
        "Slides and plain text files."
    )
    arguments_schema = {"file_id": str}

    def run(self, arguments: dict[str, Any]) -> str:
        file_id = _id(arguments, "file_id")
        meta = self._get(f"{DRIVE}/files/{file_id}?fields=id,name,mimeType") or {}
        mime = meta.get("mimeType", "")
        if mime in _EXPORT:
            url = f"{DRIVE}/files/{file_id}/export?" + urlencode({"mimeType": _EXPORT[mime]})
        elif mime.startswith("text/") or mime in _TEXT_TYPES:
            url = f"{DRIVE}/files/{file_id}?alt=media"
        else:
            return f"{meta.get('name', file_id)} is {mime or 'an unknown type'} and cannot be read as text."
        data = google_bytes(url, self.credentials(), _DOWNLOAD_LIMIT)
        return f"{meta.get('name', '')}\n\n{_clip(data.decode('utf-8', errors='replace').lstrip(chr(0xFEFF)))}"
