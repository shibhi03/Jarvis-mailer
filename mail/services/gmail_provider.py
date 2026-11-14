import base64
from datetime import datetime, timezone as dt_timezone
from email.mime.text import MIMEText
from email.utils import parseaddr, parsedate_to_datetime
from typing import Optional, Tuple

from django.conf import settings
from django.utils import timezone
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from accounts.models import MailAccount
from mail.models import EmailMessage
from mail.services.provider import BaseMailProvider
from mail.services.realtime import realtime_broker


def _decode_base64url(data: str) -> str:
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding).decode("utf-8", errors="replace")


def _extract_bodies(payload: dict) -> Tuple[str, str]:
    """Recursively extract (plain_text, html) from a Gmail message payload."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    if mime_type == "text/plain" and body_data:
        return _decode_base64url(body_data), ""
    if mime_type == "text/html" and body_data:
        return "", _decode_base64url(body_data)

    plain_text, html_text = "", ""
    for part in payload.get("parts", []) or []:
        p_plain, p_html = _extract_bodies(part)
        if p_plain and not plain_text:
            plain_text = p_plain
        if p_html and not html_text:
            html_text = p_html
    return plain_text, html_text


class GmailMailProvider(BaseMailProvider):
    """Google Gmail API integration with OAuth2 & Pub/Sub incremental sync."""

    def _get_credentials(self) -> Credentials:
        expiry = self.account.token_expiry
        if expiry is not None and expiry.tzinfo is not None:
            expiry = expiry.astimezone(dt_timezone.utc).replace(tzinfo=None)

        creds = Credentials(
            token=self.account.access_token or None,
            refresh_token=self.account.refresh_token or None,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            scopes=settings.GMAIL_SCOPES,
            expiry=expiry,
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self.account.access_token = creds.token or ""
            new_expiry = creds.expiry
            if new_expiry is not None and new_expiry.tzinfo is None:
                new_expiry = new_expiry.replace(tzinfo=dt_timezone.utc)
            self.account.token_expiry = new_expiry
            self.account.save(update_fields=["access_token", "token_expiry", "updated_at"])
        return creds

    def _service(self):
        return build("gmail", "v1", credentials=self._get_credentials(), cache_discovery=False)

    def _upsert_gmail_message(self, service, msg_id: str, folder: str) -> Tuple[EmailMessage, bool]:
        raw = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        payload = raw.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

        sender_name, sender_email = parseaddr(headers.get("from", ""))
        recipient = headers.get("to", self.account.email)
        subject = headers.get("subject", "(No subject)")
        in_reply_to = headers.get("in-reply-to", "")

        date_str = headers.get("date", "")
        received_at = timezone.now()
        if date_str:
            try:
                parsed = parsedate_to_datetime(date_str)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=dt_timezone.utc)
                received_at = parsed
            except (TypeError, ValueError):
                pass
        elif raw.get("internalDate"):
            received_at = datetime.fromtimestamp(
                int(raw["internalDate"]) / 1000.0, tz=dt_timezone.utc
            )

        body_text, body_html = _extract_bodies(payload)
        snippet = raw.get("snippet", "") or " ".join(body_text.split())[:140]
        label_ids = raw.get("labelIds", [])
        is_read = "UNREAD" not in label_ids

        obj, created = EmailMessage.objects.update_or_create(
            account=self.account,
            provider_message_id=raw["id"],
            defaults={
                "thread_id": raw.get("threadId", raw["id"]),
                "folder": folder,
                "sender_name": sender_name or sender_email,
                "sender_email": sender_email or self.account.email,
                "recipient_email": recipient,
                "subject": subject,
                "snippet": snippet,
                "body_text": body_text or snippet,
                "body_html": body_html,
                "is_read": is_read,
                "in_reply_to": in_reply_to,
                "received_at": received_at,
            },
        )
        return obj, created

    def sync_messages(self, max_results: int = 20) -> int:
        service = self._service()
        added = 0
        for label, folder in [("INBOX", EmailMessage.FOLDER_INBOX), ("SENT", EmailMessage.FOLDER_SENT)]:
            resp = (
                service.users()
                .messages()
                .list(userId="me", labelIds=[label], maxResults=max_results)
                .execute()
            )
            for item in resp.get("messages", []) or []:
                _, created = self._upsert_gmail_message(service, item["id"], folder)
                if created:
                    added += 1

        profile = service.users().getProfile(userId="me").execute()
        if profile.get("historyId"):
            self.account.history_id = str(profile["historyId"])
            self.account.save(update_fields=["history_id", "updated_at"])
        return added

    def sync_history(self, new_history_id: str) -> int:
        """Incremental sync triggered by Google Cloud Pub/Sub push notification."""
        service = self._service()
        if not self.account.history_id:
            return self.sync_messages(max_results=10)

        resp = (
            service.users()
            .history()
            .list(
                userId="me",
                startHistoryId=self.account.history_id,
                historyTypes=["messageAdded"],
            )
            .execute()
        )
        added = 0
        for record in resp.get("history", []) or []:
            for added_item in record.get("messagesAdded", []) or []:
                msg_meta = added_item.get("message", {})
                labels = msg_meta.get("labelIds", [])
                folder = (
                    EmailMessage.FOLDER_SENT
                    if "SENT" in labels and "INBOX" not in labels
                    else EmailMessage.FOLDER_INBOX
                )
                email_obj, created = self._upsert_gmail_message(
                    service, msg_meta["id"], folder
                )
                if created:
                    added += 1
                    realtime_broker.publish("new_email", email_obj.to_dict())

        self.account.history_id = str(new_history_id)
        self.account.save(update_fields=["history_id", "updated_at"])
        return added

    def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
    ) -> EmailMessage:
        service = self._service()
        mime_msg = MIMEText(body)
        mime_msg["to"] = to.strip()
        mime_msg["subject"] = subject.strip() or "(No subject)"
        if in_reply_to:
            mime_msg["In-Reply-To"] = in_reply_to
            mime_msg["References"] = in_reply_to

        raw_encoded = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")
        send_body = {"raw": raw_encoded}
        if thread_id and not str(thread_id).startswith("thread-"):
            send_body["threadId"] = thread_id

        result = service.users().messages().send(userId="me", body=send_body).execute()
        sent_obj, _ = self._upsert_gmail_message(
            service, result["id"], EmailMessage.FOLDER_SENT
        )
        return sent_obj

    def mark_read(self, email: EmailMessage, is_read: bool = True) -> None:
        service = self._service()
        body = {"removeLabelIds": ["UNREAD"]} if is_read else {"addLabelIds": ["UNREAD"]}
        service.users().messages().modify(
            userId="me", id=email.provider_message_id, body=body
        ).execute()
        email.is_read = is_read
        email.save(update_fields=["is_read"])

    def start_watch(self, topic_name: str) -> dict:
        service = self._service()
        resp = (
            service.users()
            .watch(
                userId="me",
                body={"labelIds": ["INBOX"], "topicName": topic_name},
            )
            .execute()
        )
        if resp.get("historyId"):
            self.account.history_id = str(resp["historyId"])
            self.account.save(update_fields=["history_id", "updated_at"])
        return resp
