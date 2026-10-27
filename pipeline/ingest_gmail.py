"""Gmail ingest: newsletters under one label, read-only scope."""
import base64
from email.utils import parseaddr, parsedate_to_datetime

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from . import db
from .config import ROOT
from .text_utils import html_to_text

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDS = ROOT / "credentials.json"
TOKEN = ROOT / "token.json"


def get_service(interactive: bool):
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES) if TOKEN.exists() else None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            creds = None  # Testing-mode apps: refresh tokens die after 7 days
    if not creds or not creds.valid:
        if not interactive:
            raise RuntimeError(
                "Gmail token missing or expired. Run `python run.py --auth-gmail` once in a terminal."
            )
        flow = InstalledAppFlow.from_client_secrets_file(CREDS, SCOPES)
        creds = flow.run_local_server(port=0)
    TOKEN.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _body(payload) -> str:
    """Prefer text/html (newsletters are HTML-first), fall back to text/plain."""
    html, plain = [], []

    def walk(part):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime == "text/html":
            html.append(_decode(data))
        elif data and mime == "text/plain":
            plain.append(_decode(data))
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    if html:
        return html_to_text("\n".join(html))
    return "\n".join(plain)


def build_query(gmail_cfg: dict) -> str:
    """Priority: raw query > sender list > label. Sender list is the Meco-proof option."""
    days = gmail_cfg.get("lookback_days", 3)
    if gmail_cfg.get("query"):
        return f'({gmail_cfg["query"]}) newer_than:{days}d'
    senders = gmail_cfg.get("senders") or []
    if senders:
        return f'from:({" OR ".join(senders)}) newer_than:{days}d'
    return f'label:"{gmail_cfg.get("label", "Newsletters")}" newer_than:{days}d'


def list_labels(interactive: bool = True) -> list[tuple[str, str]]:
    service = get_service(interactive)
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    return sorted((l["name"], l["id"]) for l in labels)


def ingest(conn, gmail_cfg: dict, interactive: bool = False, log=print) -> int:
    service = get_service(interactive)
    query = build_query(gmail_cfg)
    log(f"[gmail] query: {query}")
    added, page_token = 0, None
    while True:
        resp = service.users().messages().list(
            userId="me", q=query, pageToken=page_token, maxResults=100
        ).execute()
        for ref in resp.get("messages", []):
            uid = f"gmail:{ref['id']}"
            if conn.execute("SELECT 1 FROM items WHERE uid=?", (uid,)).fetchone():
                continue
            msg = service.users().messages().get(userId="me", id=ref["id"], format="full").execute()
            headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
            sender_name, sender_addr = parseaddr(headers.get("from", ""))
            try:
                published = parsedate_to_datetime(headers["date"]).isoformat()
            except Exception:
                published = None
            if db.insert_item(
                conn, uid=uid, source_type="gmail", source_name=sender_name or sender_addr,
                title=headers.get("subject", "(no subject)"),
                url=f"https://mail.google.com/mail/u/0/#all/{ref['id']}",
                published=published, text=_body(msg["payload"]),
            ):
                added += 1
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    log(f"[gmail] added {added}")
    return added
