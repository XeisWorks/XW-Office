"""Shared Microsoft Graph mail client with legacy-style MSAL device flow."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
import logging
import os
from pathlib import Path
import re
import threading
from typing import Any

import msal
import requests

logger = logging.getLogger(__name__)

_CACHE_IO_LOCK = threading.Lock()
_DEVICE_FLOW_LOCK = threading.Lock()
_STYLE_TAG_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
_COMMENT_TAG_RE = re.compile(r"<!--.*?-->", re.DOTALL)


class _HTMLTextExtractor(HTMLParser):
    BLOCK_TAGS = {
        "p",
        "div",
        "section",
        "header",
        "footer",
        "blockquote",
        "table",
        "tr",
        "li",
        "ul",
        "ol",
        "hr",
        "article",
        "aside",
    }
    TABLE_TD_TAGS = {"td", "th"}
    SKIP_TAGS = {"script", "style"}

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._last_char = ""
        self._newline_streak = 0
        self._pre = False
        self._skip_depth = 0
        self._pending_list = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not data:
            return
        text = data.replace("\xa0", " ")
        text = re.sub(r"[\ufeff\u200b]", "", text)
        if not self._pre:
            text = text.replace("\r", "").replace("\n", " ")
            text = re.sub(r"\s+", " ", text)
        if not text:
            return
        if self._pending_list:
            self._append("- ")
            self._pending_list = False
        if (
            self._last_char
            and not self._last_char.isspace()
            and not text[0].isspace()
            and text[0] not in ".,;:?!/\\|"
        ):
            text = " " + text
        self._append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "pre":
            self._pre = True
            self._append_newline(force=True)
            return
        if tag == "br":
            self._append_newline()
            return
        if tag == "li":
            self._append_newline()
            self._pending_list = True
            return
        if tag in self.TABLE_TD_TAGS:
            self._append(" | ")
            return
        if tag in self.BLOCK_TAGS or tag.startswith("h"):
            self._append_newline()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "pre":
            self._pre = False
            self._append_newline()
            return
        if tag in self.TABLE_TD_TAGS or tag == "br":
            return
        if tag in self.BLOCK_TAGS or tag.startswith("h"):
            self._append_newline()

    def _append_newline(self, *, force: bool = False) -> None:
        if not force and self._newline_streak >= 2:
            return
        self._chunks.append("\n")
        self._last_char = "\n"
        self._newline_streak += 1

    def _append(self, text: str) -> None:
        if not text:
            return
        self._chunks.append(text)
        self._last_char = text[-1]
        self._newline_streak = 0

    def get_text(self) -> str:
        return "".join(self._chunks)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def default_graph_cache_path() -> Path:
    env_override = (
        str(os.getenv("XW_OFFICE_MSAL_CACHE_PATH") or "").strip()
        or str(os.getenv("SEVDESK_MSAL_CACHE_PATH") or "").strip()
    )
    if env_override:
        path = Path(os.path.expandvars(os.path.expanduser(env_override)))
        if path.is_absolute():
            return path
        return (_repo_root() / path).resolve()
    return _repo_root() / "state" / "msal_cache.json"


def _utc_cutoff_iso(days: int) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _strip_html_noise(content: str) -> str:
    if not content:
        return ""
    content = _STYLE_TAG_RE.sub("", content)
    content = _COMMENT_TAG_RE.sub("", content)
    return content


def _looks_like_html(content: str, content_type: str | None) -> bool:
    if not content:
        return False
    if content_type and content_type.strip().lower() == "html":
        return True
    stripped = content.lstrip()
    return (stripped.startswith("<") and ">" in stripped[:10]) or "<!--" in content


def html_to_text(content: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(_strip_html_noise(content))
    parser.close()
    text = unescape(parser.get_text())
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


class GraphMailClient:
    """Authenticate via MSAL device flow and read/send mail via Microsoft Graph."""

    def __init__(
        self,
        *,
        tenant_id: str,
        client_id: str,
        mailbox_user: str | None = None,
        cache_path: Path | None = None,
        scopes: list[str] | None = None,
    ) -> None:
        self.tenant_id = str(tenant_id or "").strip()
        self.client_id = str(client_id or "").strip()
        mailbox_user = str(mailbox_user or "").strip()
        self.mailbox_user = mailbox_user or None
        self._mailbox_segment = f"users/{mailbox_user}" if mailbox_user else "me"
        self.scopes = scopes or ["Mail.Read", "Mail.Read.Shared", "Mail.Send", "Mail.Send.Shared"]
        self._cache_path = cache_path or default_graph_cache_path()
        self._cache = msal.SerializableTokenCache()
        self._load_cache()
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        self._app = msal.PublicClientApplication(
            client_id=self.client_id,
            authority=authority,
            token_cache=self._cache,
        )

    def list_inbox_messages(
        self,
        *,
        days: int = 20,
        exclude_sender: str | None = None,
        top: int = 50,
    ) -> list[dict[str, Any]]:
        cutoff = _utc_cutoff_iso(days)
        base_url = f"https://graph.microsoft.com/v1.0/{self._mailbox_segment}/mailFolders/inbox/messages"
        fallback_url = f"https://graph.microsoft.com/v1.0/{self._mailbox_segment}/messages"
        params = {
            "$select": "id,internetMessageId,subject,from,receivedDateTime,bodyPreview,body,conversationId,isRead,flag",
            "$orderby": "receivedDateTime desc",
            "$top": str(top),
            "$filter": f"receivedDateTime ge {cutoff}",
        }
        if exclude_sender:
            sender = exclude_sender.strip().lower()
            params["$filter"] = f"receivedDateTime ge {cutoff} and from/emailAddress/address ne '{sender}'"
        response = requests.get(base_url, headers=self._auth_headers(), params=params, timeout=30)
        if response.status_code == 404:
            response = requests.get(fallback_url, headers=self._auth_headers(), params=params, timeout=30)
        if response.status_code == 400 and exclude_sender:
            params["$filter"] = f"receivedDateTime ge {cutoff}"
            response = requests.get(base_url, headers=self._auth_headers(), params=params, timeout=30)
            if response.status_code == 404:
                response = requests.get(fallback_url, headers=self._auth_headers(), params=params, timeout=30)
        self._raise_for_status(response)
        payload = response.json()
        values = payload.get("value", []) if isinstance(payload, dict) else []
        return [item for item in values if isinstance(item, dict)]

    def get_message_body(self, message_id: str) -> str:
        message_id = str(message_id or "").strip()
        if not message_id:
            return ""
        url = f"https://graph.microsoft.com/v1.0/{self._mailbox_segment}/messages/{message_id}"
        params = {"$select": "body"}
        response = requests.get(url, headers=self._auth_headers(), params=params, timeout=30)
        self._raise_for_status(response)
        payload = response.json() if response.content else {}
        if not isinstance(payload, dict):
            return ""
        body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
        content = str(body.get("content") or "").strip()
        content_type = str(body.get("contentType") or "").strip()
        if _looks_like_html(content, content_type):
            return html_to_text(content)
        return content

    def list_pdf_attachments(self, message_id: str) -> list[dict[str, Any]]:
        message_id = str(message_id or "").strip()
        if not message_id:
            return []
        url = f"https://graph.microsoft.com/v1.0/{self._mailbox_segment}/messages/{message_id}/attachments"
        params = {"$select": "id,name,contentType,size"}
        response = requests.get(url, headers=self._auth_headers(), params=params, timeout=30)
        self._raise_for_status(response)
        payload = response.json() if response.content else {}
        values = payload.get("value", []) if isinstance(payload, dict) else []
        out: list[dict[str, Any]] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            content_type = str(item.get("contentType") or "").lower()
            name = str(item.get("name") or "")
            if content_type == "application/pdf" or name.lower().endswith(".pdf"):
                out.append(item)
        return out

    def download_attachment_bytes(self, message_id: str, attachment_id: str) -> bytes:
        message_id = str(message_id or "").strip()
        attachment_id = str(attachment_id or "").strip()
        if not message_id or not attachment_id:
            return b""
        url = (
            f"https://graph.microsoft.com/v1.0/{self._mailbox_segment}/messages/{message_id}"
            f"/attachments/{attachment_id}/$value"
        )
        response = requests.get(url, headers=self._auth_headers(), timeout=30)
        self._raise_for_status(response)
        return bytes(response.content or b"")

    def get_conversation_thread_text(self, conversation_id: str, *, days: int = 60, top: int = 50) -> str:
        conversation_id = str(conversation_id or "").strip()
        if not conversation_id:
            return ""
        cutoff = _utc_cutoff_iso(days)
        url = f"https://graph.microsoft.com/v1.0/{self._mailbox_segment}/messages"
        params = {
            "$select": "subject,receivedDateTime,from,body,bodyPreview",
            "$orderby": "receivedDateTime desc",
            "$top": str(max(1, min(top, 100))),
            "$filter": (
                f"conversationId eq '{conversation_id}' and receivedDateTime ge {cutoff}"
            ),
        }
        response = requests.get(url, headers=self._auth_headers(), params=params, timeout=30)
        if response.status_code == 400:
            params["$filter"] = f"conversationId eq '{conversation_id}'"
            response = requests.get(url, headers=self._auth_headers(), params=params, timeout=30)
        self._raise_for_status(response)
        payload = response.json() if response.content else {}
        values = payload.get("value", []) if isinstance(payload, dict) else []
        parts: list[str] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            from_obj = item.get("from") if isinstance(item.get("from"), dict) else {}
            email_obj = (
                from_obj.get("emailAddress") if isinstance(from_obj.get("emailAddress"), dict) else {}
            )
            sender = str(email_obj.get("address") or email_obj.get("name") or "").strip() or "Unbekannt"
            subject = str(item.get("subject") or "").strip()
            received = str(item.get("receivedDateTime") or "").strip()
            body_obj = item.get("body") if isinstance(item.get("body"), dict) else {}
            content = str(body_obj.get("content") or "").strip()
            content_type = str(body_obj.get("contentType") or "").strip()
            body_text = html_to_text(content) if _looks_like_html(content, content_type) else content
            if not body_text:
                body_text = str(item.get("bodyPreview") or "").strip()
            header = f"[{received}] {sender} | {subject}".strip()
            parts.append(f"{header}\n{body_text}".strip())
        return "\n\n---\n\n".join(part for part in parts if part).strip()

    def mark_message_followup_complete(self, message_id: str) -> None:
        message_id = str(message_id or "").strip()
        if not message_id:
            raise RuntimeError("Message-ID fehlt")
        now_utc = datetime.now(timezone.utc).replace(microsecond=0)
        url = f"https://graph.microsoft.com/v1.0/{self._mailbox_segment}/messages/{message_id}"
        payload = {
            "flag": {
                "flagStatus": "complete",
                "completedDateTime": {
                    "dateTime": now_utc.strftime("%Y-%m-%dT%H:%M:%S"),
                    "timeZone": "UTC",
                },
            },
            "isRead": True,
        }
        response = requests.patch(url, headers=self._auth_headers(), json=payload, timeout=30)
        self._raise_for_status(response)

    def send_mail(
        self,
        *,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: str = "",
        attachments: list[Any] | None = None,
    ) -> None:
        to_email = str(to_email or "").strip()
        subject = str(subject or "").strip()
        body_text = str(body_text or "").strip()
        body_html = str(body_html or "").strip()
        if not to_email:
            raise RuntimeError("Empfaenger fehlt.")
        if not subject:
            raise RuntimeError("Betreff fehlt.")
        if not (body_html or body_text):
            raise RuntimeError("Mail-Inhalt fehlt.")

        message: dict[str, Any] = {
            "subject": subject,
            "body": {
                "contentType": "HTML" if body_html else "Text",
                "content": body_html or body_text,
            },
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        }
        if self.mailbox_user:
            message["from"] = {"emailAddress": {"address": self.mailbox_user}}
        attachment_items = self._build_attachment_payloads(attachments or [])
        if attachment_items:
            message["attachments"] = attachment_items
        payload = {"message": message, "saveToSentItems": True}
        url = f"https://graph.microsoft.com/v1.0/{self._mailbox_segment}/sendMail"
        response = requests.post(url, headers=self._auth_headers(), json=payload, timeout=60)
        self._raise_for_status(response)

    def _build_attachment_payloads(self, attachments: list[Any]) -> list[dict[str, str]]:
        payloads: list[dict[str, str]] = []
        for attachment in attachments:
            content = bytes(getattr(attachment, "content", b"") or b"")
            if not content:
                continue
            filename = str(getattr(attachment, "filename", "") or "attachment.bin").strip()
            mime_type = str(getattr(attachment, "mime_type", "") or "application/octet-stream").strip()
            payloads.append(
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": filename,
                    "contentType": mime_type,
                    "contentBytes": base64.b64encode(content).decode("ascii"),
                }
            )
        return payloads

    def _load_cache(self) -> None:
        try:
            if not self._cache_path.exists():
                return
            with _CACHE_IO_LOCK:
                raw = self._cache_path.read_text(encoding="utf-8")
            if not raw.strip():
                return
            try:
                self._cache.deserialize(raw)
            except Exception as exc:  # noqa: BLE001
                logger.warning("MSAL cache load failed: %s", exc)
                self._quarantine_corrupt_cache()
        except Exception as exc:  # noqa: BLE001
            logger.warning("MSAL cache load failed: %s", exc)

    def _save_cache(self) -> None:
        if not self._cache.has_state_changed:
            return
        try:
            payload = self._cache.serialize()
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._cache_path.with_name(f"{self._cache_path.name}.tmp")
            with _CACHE_IO_LOCK:
                tmp_path.write_text(payload, encoding="utf-8")
                tmp_path.replace(self._cache_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MSAL cache save failed: %s", exc)

    def _quarantine_corrupt_cache(self) -> None:
        if not self._cache_path.exists():
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        bad_path = self._cache_path.with_name(
            f"{self._cache_path.stem}.corrupt_{stamp}{self._cache_path.suffix}"
        )
        try:
            with _CACHE_IO_LOCK:
                if self._cache_path.exists():
                    self._cache_path.replace(bad_path)
            logger.warning("MSAL cache marked corrupt: %s", bad_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MSAL cache quarantine failed: %s", exc)

    def _acquire_token_silent(self) -> dict[str, Any] | None:
        for account in self._app.get_accounts() or []:
            result = self._app.acquire_token_silent(self.scopes, account=account)
            if isinstance(result, dict) and result.get("access_token"):
                return result
        return None

    def has_silent_token(self) -> bool:
        """Return whether Graph can be used without starting device-flow auth."""
        return bool(self._acquire_token_silent())

    def _acquire_token(self) -> str:
        result = self._acquire_token_silent()
        if not result:
            with _DEVICE_FLOW_LOCK:
                self._load_cache()
                result = self._acquire_token_silent()
                if not result:
                    flow = self._app.initiate_device_flow(scopes=self.scopes)
                    if "user_code" not in flow:
                        raise RuntimeError("MSAL device flow konnte nicht gestartet werden")
                    print(flow.get("message"))
                    result = self._app.acquire_token_by_device_flow(flow)
        if not result or "access_token" not in result:
            detail = result.get("error_description") if isinstance(result, dict) else "unknown"
            raise RuntimeError(f"MS Graph Auth fehlgeschlagen: {detail}")
        self._save_cache()
        return str(result["access_token"])

    def _auth_headers(self) -> dict[str, str]:
        token = self._acquire_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if response.status_code >= 400:
            raise RuntimeError(f"Graph API Fehler {response.status_code}: {response.text[:300]}")
