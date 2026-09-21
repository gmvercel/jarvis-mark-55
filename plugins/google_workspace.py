"""Google Workspace and YouTube integration through the Google APIs."""
from __future__ import annotations

import base64
import html
import json
import mimetypes
import os
import re
import sys
import uuid
import webbrowser
from email.message import EmailMessage
from pathlib import Path
from typing import Any

PLUGIN = {
    "name": "google_workspace",
    "description": (
        "Complete Google integration. Use this for Gmail search, reading, summaries, sending, "
        "replies and attachments; Google Calendar events; Drive file search, download, upload "
        "and folders; Google Docs reading and editing; Sheets reading and writing; Slides; "
        "and YouTube search, video details and uploads. Authenticate once when requested."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "gmail_search | gmail_read | gmail_summarize | gmail_send | gmail_reply | "
                    "calendar_list | calendar_create | calendar_update | calendar_delete | "
                    "drive_search | drive_download | drive_upload | drive_folder | "
                    "docs_read | docs_create | docs_append | sheets_read | sheets_write | sheets_append | "
                    "slides_read | slides_create | youtube_search | youtube_video | youtube_upload | "
                    "authenticate"
                ),
            },
            "query": {"type": "STRING", "description": "Search query, Gmail query, title, or text"},
            "message_id": {"type": "STRING", "description": "Gmail message id"},
            "thread_id": {"type": "STRING", "description": "Gmail thread id"},
            "to": {"type": "STRING", "description": "Recipient email address(es), comma separated"},
            "subject": {"type": "STRING", "description": "Email subject or document title"},
            "body": {"type": "STRING", "description": "Email body or document content"},
            "attachment": {"type": "STRING", "description": "Local file path to attach or upload"},
            "file_id": {"type": "STRING", "description": "Google Drive, Docs, Sheets, Slides, or YouTube id"},
            "calendar_id": {"type": "STRING", "description": "Calendar id, default primary"},
            "start": {"type": "STRING", "description": "ISO date/time, for example 2026-09-20T10:00:00+02:00"},
            "end": {"type": "STRING", "description": "ISO date/time"},
            "location": {"type": "STRING", "description": "Event location"},
            "range": {"type": "STRING", "description": "Sheets A1 range, for example Sheet1!A1:D20"},
            "values": {"type": "ARRAY", "items": {"type": "ARRAY", "items": {"type": "STRING"}}, "description": "Rows of values for Sheets"},
            "folder_id": {"type": "STRING", "description": "Drive destination folder id"},
            "mime_type": {"type": "STRING", "description": "Optional upload MIME type"},
            "limit": {"type": "INTEGER", "description": "Maximum results, default 10"},
            "calendar_timezone": {"type": "STRING", "description": "IANA timezone, default Europe/Rome"},
        },
        "required": ["action"],
    },
}

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _ROOT / "config" / "api_keys.json"
_TOKEN_PATH = _ROOT / "config" / "google_token.json"
_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/youtube",
]
_SERVICES: dict[str, Any] = {}
_CREDS = None


def _config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _credentials_path() -> Path:
    config = _config()
    configured = os.environ.get("GOOGLE_CLIENT_SECRET_FILE") or config.get("google_client_secret_file")
    candidates = [
        Path(configured).expanduser() if configured else None,
        _ROOT / "config" / "google_client_secret.json",
        _ROOT / "config" / "credentials.json",
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    raise RuntimeError(
        "Google non configurato: scarica il client OAuth Desktop da Google Cloud Console "
        "e salvalo come config/google_client_secret.json."
    )


def _auth():
    global _CREDS
    if _CREDS is not None and getattr(_CREDS, "valid", False):
        return _CREDS
    try:
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError(
            "Dipendenze Google mancanti. Esegui: python -m pip install "
            "google-api-python-client google-auth-oauthlib google-auth-httplib2 "
            f"(interprete attivo: {sys.executable})"
        ) from exc

    creds = None
    if _TOKEN_PATH.exists():
        try:
            from google.oauth2.credentials import Credentials
            creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH), _SCOPES)
        except Exception:
            creds = None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(_credentials_path()), _SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True, access_type="offline", prompt="consent")
        _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    _CREDS = creds
    _SERVICES.clear()
    return creds


def _service(name: str, version: str):
    key = f"{name}:{version}"
    if key not in _SERVICES:
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Dipendenze Google mancanti. Esegui: python -m pip install "
                "google-api-python-client google-auth-oauthlib google-auth-httplib2 "
                f"(interprete attivo: {sys.executable})"
            ) from exc
        _SERVICES[key] = build(name, version, credentials=_auth(), cache_discovery=False)
    return _SERVICES[key]


def _limit(params: dict, default: int = 10) -> int:
    return max(1, min(50, int(params.get("limit") or default)))


def _show(player, title: str, text: str) -> None:
    if not player:
        return
    try:
        player.show_content(title, text[:12000])
        player.write_log(f"[Google] {title}")
    except Exception:
        pass


def _decode_gmail(data: str) -> str:
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    return raw.decode("utf-8", errors="replace")


def _strip_html(value: str) -> str:
    value = re.sub(r"<style.*?</style>|<script.*?</script>", " ", value, flags=re.I | re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def _gmail_parts(payload: dict) -> list[str]:
    if payload.get("body", {}).get("data"):
        return [_decode_gmail(payload["body"]["data"])]
    out = []
    for part in payload.get("parts", []):
        mime = part.get("mimeType", "")
        if mime.startswith("text/") and part.get("body", {}).get("data"):
            text = _decode_gmail(part["body"]["data"])
            out.append(_strip_html(text) if mime == "text/html" else text)
        elif part.get("parts"):
            out.extend(_gmail_parts(part))
    return out


def _headers(message: dict) -> dict:
    return {h.get("name", "").lower(): h.get("value", "") for h in message.get("payload", {}).get("headers", [])}


def _gmail_message(gmail, message_id: str, full: bool = True) -> dict:
    return gmail.users().messages().get(userId="me", id=message_id, format="full" if full else "metadata").execute()


def _gmail_summary(message: dict) -> str:
    headers = _headers(message)
    body = "\n".join(_gmail_parts(message.get("payload", {})))
    return (
        f"ID: {message.get('id')}\n"
        f"Da: {headers.get('from', '')}\n"
        f"A: {headers.get('to', '')}\n"
        f"Data: {headers.get('date', '')}\n"
        f"Oggetto: {headers.get('subject', '(senza oggetto)')}\n"
        f"{body[:3500] or message.get('snippet', '')}"
    )


def _gmail_search(params: dict, player=None) -> str:
    gmail = _service("gmail", "v1")
    query = str(params.get("query") or "newer_than:30d").strip()
    response = gmail.users().messages().list(userId="me", q=query, maxResults=_limit(params)).execute()
    messages = [_gmail_message(gmail, item["id"]) for item in response.get("messages", [])]
    result = "\n\n".join(_gmail_summary(item) for item in messages) or "Nessuna email trovata."
    _show(player, f"GMAIL SEARCH: {query}", result)
    return result


def _gmail_read(params: dict, player=None) -> str:
    gmail = _service("gmail", "v1")
    message_id = str(params.get("message_id") or "").strip()
    if not message_id:
        query = str(params.get("query") or "").strip()
        found = gmail.users().messages().list(userId="me", q=query, maxResults=1).execute().get("messages", [])
        if not found:
            return "Email non trovata."
        message_id = found[0]["id"]
    message = _gmail_message(gmail, message_id)
    result = _gmail_summary(message)
    gmail.users().messages().modify(userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}).execute()
    _show(player, "GMAIL EMAIL", result)
    return result


def _gmail_send(params: dict, reply: bool = False) -> str:
    gmail = _service("gmail", "v1")
    message = EmailMessage()
    message["To"] = str(params.get("to") or "").strip()
    message["Subject"] = str(params.get("subject") or "").strip()
    message.set_content(str(params.get("body") or "").strip())
    attachment = str(params.get("attachment") or "").strip()
    if attachment:
        path = Path(attachment).expanduser()
        if not path.is_file():
            raise RuntimeError(f"Allegato non trovato: {path}")
        mime, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (mime or "application/octet-stream").split("/", 1)
        message.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    body = {"raw": raw}
    if reply and params.get("thread_id"):
        body["threadId"] = str(params["thread_id"])
    sent = gmail.users().messages().send(userId="me", body=body).execute()
    return f"Email inviata a {message['To']} (id {sent.get('id')})."


def _calendar(params: dict, action: str) -> str:
    calendar = _service("calendar", "v3")
    calendar_id = str(params.get("calendar_id") or "primary")
    if action == "calendar_list":
        request = {"calendarId": calendar_id, "maxResults": _limit(params),
                   "singleEvents": True, "orderBy": "startTime"}
        if params.get("start"):
            request["timeMin"] = str(params["start"])
        data = calendar.events().list(**request).execute()
        rows = []
        for event in data.get("items", []):
            start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date", "")
            rows.append(f"{event.get('id')}: {start} - {event.get('summary', '(senza titolo)')} [{event.get('location', '')}]")
        return "\n".join(rows) or "Nessun evento trovato."
    event_id = str(params.get("file_id") or params.get("message_id") or "").strip()
    if action == "calendar_delete":
        calendar.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return "Evento eliminato."
    resource = {
        "summary": str(params.get("subject") or params.get("query") or "Evento JARVIS"),
        "description": str(params.get("body") or ""),
        "location": str(params.get("location") or ""),
        "start": {"dateTime": str(params.get("start") or ""), "timeZone": str(params.get("calendar_timezone") or "Europe/Rome")},
        "end": {"dateTime": str(params.get("end") or params.get("start") or ""), "timeZone": str(params.get("calendar_timezone") or "Europe/Rome")},
    }
    if action == "calendar_update":
        result = calendar.events().update(calendarId=calendar_id, eventId=event_id, body=resource).execute()
    else:
        result = calendar.events().insert(calendarId=calendar_id, body=resource).execute()
    return f"Evento {'aggiornato' if action == 'calendar_update' else 'creato'}: {result.get('summary')} ({result.get('id')})."


def _drive(params: dict, action: str) -> str:
    drive = _service("drive", "v3")
    if action == "drive_search":
        query = str(params.get("query") or "").replace("'", "\\'")
        q = f"name contains '{query}' and trashed = false" if query else "trashed = false"
        data = drive.files().list(q=q, pageSize=_limit(params), fields="files(id,name,mimeType,modifiedTime,webViewLink,size)").execute()
        return "\n".join(f"{f['id']}: {f['name']} [{f['mimeType']}] {f.get('webViewLink', '')}" for f in data.get("files", [])) or "Nessun file trovato."
    if action == "drive_folder":
        result = drive.files().create(body={"name": str(params.get("subject") or params.get("query") or "Nuova cartella"), "mimeType": "application/vnd.google-apps.folder"}, fields="id,name,webViewLink").execute()
        return f"Cartella creata: {result.get('name')} ({result.get('id')})."
    if action == "drive_download":
        file_id = str(params.get("file_id") or "")
        meta = drive.files().get(fileId=file_id, fields="name,mimeType,webViewLink").execute()
        webbrowser.open(meta.get("webViewLink") or f"https://drive.google.com/open?id={file_id}")
        return f"Aperto in Google Drive: {meta.get('name')} ({meta.get('webViewLink', '')})."
    path = Path(str(params.get("attachment") or "")).expanduser()
    if not path.is_file():
        raise RuntimeError("Indica un file locale da caricare in attachment.")
    from googleapiclient.http import MediaFileUpload
    metadata = {"name": path.name}
    if params.get("folder_id"):
        metadata["parents"] = [str(params["folder_id"])]
    result = drive.files().create(body=metadata, media_body=MediaFileUpload(str(path), mimetype=params.get("mime_type") or mimetypes.guess_type(path.name)[0]), fields="id,name,webViewLink").execute()
    return f"Caricato su Drive: {result.get('name')} ({result.get('id')})."


def _docs(params: dict, action: str) -> str:
    docs = _service("docs", "v1")
    if action == "docs_read":
        document = docs.documents().get(documentId=str(params.get("file_id") or "")).execute()
        chunks = []
        for item in document.get("body", {}).get("content", []):
            for element in item.get("paragraph", {}).get("elements", []):
                chunks.append(element.get("textRun", {}).get("content", ""))
        result = "".join(chunks).strip() or "Documento vuoto."
        return f"Titolo: {document.get('title')}\n{result}"
    if action == "docs_create":
        result = docs.documents().create(body={"title": str(params.get("subject") or "Documento JARVIS")}).execute()
        doc_id = result["documentId"]
    else:
        doc_id = str(params.get("file_id") or "")
    requests = [{"insertText": {"location": {"index": 1}, "text": str(params.get("body") or "")}}]
    if action == "docs_append":
        document = docs.documents().get(documentId=doc_id).execute()
        end = max(1, int(document.get("body", {}).get("content", [{}])[-1].get("endIndex", 1)) - 1)
        requests[0]["insertText"]["location"]["index"] = end
    if action != "docs_create" or params.get("body"):
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
    return f"Documento pronto: https://docs.google.com/document/d/{doc_id}/edit"


def _sheets(params: dict, action: str) -> str:
    sheets = _service("sheets", "v4")
    spreadsheet_id = str(params.get("file_id") or "")
    range_name = str(params.get("range") or "Sheet1!A1:Z50")
    if action == "sheets_read":
        data = sheets.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
        rows = data.get("values", [])
        return "\n".join(" | ".join(map(str, row)) for row in rows) or "Nessun dato trovato."
    values = params.get("values") or [[str(params.get("body") or "")]]
    result = sheets.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range=range_name, valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS", body={"values": values},
    ).execute() if action == "sheets_append" else sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=range_name, valueInputOption="USER_ENTERED", body={"values": values}
    ).execute()
    return f"Foglio aggiornato: {result.get('updatedRange') or result.get('tableRange', range_name)}."


def _slides(params: dict, action: str) -> str:
    slides = _service("slides", "v1")
    if action == "slides_read":
        presentation = slides.presentations().get(presentationId=str(params.get("file_id") or "")).execute()
        texts = []
        for slide in presentation.get("slides", []):
            for element in slide.get("pageElements", []):
                for part in element.get("shape", {}).get("text", {}).get("textElements", []):
                    texts.append(part.get("textRun", {}).get("content", ""))
        return f"Titolo: {presentation.get('title')}\n" + "".join(texts)
    result = slides.presentations().create(body={"title": str(params.get("subject") or "Presentazione JARVIS")}).execute()
    return f"Presentazione creata: https://docs.google.com/presentation/d/{result['presentationId']}/edit"


def _youtube(params: dict, action: str) -> str:
    youtube = _service("youtube", "v3")
    if action == "youtube_search":
        data = youtube.search().list(part="snippet", q=str(params.get("query") or ""), maxResults=_limit(params), type="video").execute()
        return "\n".join(f"{x['id'].get('videoId')}: {x['snippet'].get('title')} - https://youtu.be/{x['id'].get('videoId')}" for x in data.get("items", [])) or "Nessun video trovato."
    if action == "youtube_video":
        data = youtube.videos().list(part="snippet,statistics,contentDetails", id=str(params.get("file_id") or params.get("query") or "")).execute()
        if not data.get("items"):
            return "Video non trovato."
        item = data["items"][0]
        return f"{item['snippet'].get('title')}\n{item['snippet'].get('description', '')[:4000]}\nVisualizzazioni: {item.get('statistics', {}).get('viewCount', '0')}"
    path = Path(str(params.get("attachment") or "")).expanduser()
    if not path.is_file():
        raise RuntimeError("Indica il video locale da caricare in attachment.")
    from googleapiclient.http import MediaFileUpload
    result = youtube.videos().insert(
        part="snippet,status", body={"snippet": {"title": str(params.get("subject") or path.stem), "description": str(params.get("body") or "")}, "status": {"privacyStatus": "private"}},
        media_body=MediaFileUpload(str(path), chunksize=-1, resumable=True),
    ).execute()
    return f"Video caricato su YouTube: https://youtu.be/{result.get('id')}"


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action") or "").strip().lower()
    if action == "authenticate":
        _auth()
        return "Account Google collegato e autorizzato."
    if action == "gmail_search":
        result = _gmail_search(params, player)
    elif action == "gmail_read":
        result = _gmail_read(params, player)
    elif action == "gmail_summarize":
        params = dict(params)
        params.setdefault("query", "newer_than:7d")
        params.setdefault("limit", 15)
        result = _gmail_search(params, player)
    elif action == "gmail_send":
        result = _gmail_send(params)
    elif action == "gmail_reply":
        result = _gmail_send(params, reply=True)
    elif action.startswith("calendar_"):
        result = _calendar(params, action)
    elif action.startswith("drive_"):
        result = _drive(params, action)
    elif action.startswith("docs_"):
        result = _docs(params, action)
    elif action.startswith("sheets_"):
        result = _sheets(params, action)
    elif action.startswith("slides_"):
        result = _slides(params, action)
    elif action.startswith("youtube_"):
        result = _youtube(params, action)
    else:
        return f"Azione Google non riconosciuta: {action}."
    if player:
        try:
            player.write_log(f"[Google] {result[:180]}")
        except Exception:
            pass
    return result
