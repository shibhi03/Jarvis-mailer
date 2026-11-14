import uuid
from abc import ABC, abstractmethod
from typing import Optional

from django.utils import timezone

from accounts.models import MailAccount
from mail.models import EmailMessage


class BaseMailProvider(ABC):
    """Abstract interface for mail providers (Gmail, Demo, etc.)."""

    def __init__(self, account: MailAccount):
        self.account = account

    @abstractmethod
    def sync_messages(self, max_results: int = 30) -> int:
        """Sync recent messages from the provider into local DB. Returns count added."""

    @abstractmethod
    def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
    ) -> EmailMessage:
        """Send an email via the provider and store it in Sent."""

    @abstractmethod
    def mark_read(self, email: EmailMessage, is_read: bool = True) -> None:
        """Mark a message as read or unread."""


class DemoMailProvider(BaseMailProvider):
    """Local database-backed mail provider for instant setup and testing."""

    def sync_messages(self, max_results: int = 30) -> int:
        return 0

    def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
    ) -> EmailMessage:
        now = timezone.now()
        msg_id = f"demo-{uuid.uuid4().hex[:12]}"
        resolved_thread = thread_id or f"thread-{uuid.uuid4().hex[:10]}"
        snippet = " ".join(body.split())[:140]

        sent_email = EmailMessage.objects.create(
            account=self.account,
            provider_message_id=msg_id,
            thread_id=resolved_thread,
            folder=EmailMessage.FOLDER_SENT,
            sender_name=self.account.display_name or "Jarvis User",
            sender_email=self.account.email,
            recipient_email=to.strip(),
            subject=subject.strip() or "(No subject)",
            snippet=snippet,
            body_text=body,
            is_read=True,
            in_reply_to=in_reply_to or "",
            received_at=now,
        )
        return sent_email

    def mark_read(self, email: EmailMessage, is_read: bool = True) -> None:
        if email.is_read != is_read:
            email.is_read = is_read
            email.save(update_fields=["is_read"])


def get_active_account() -> MailAccount:
    """Return the active MailAccount, prioritizing connected Gmail over Demo."""
    gmail_account = MailAccount.objects.filter(
        provider=MailAccount.PROVIDER_GMAIL, is_active=True
    ).first()
    if gmail_account:
        return gmail_account

    demo_account, _ = MailAccount.objects.get_or_create(
        email="you@jarvismail.dev",
        defaults={
            "display_name": "Alex Rivera",
            "provider": MailAccount.PROVIDER_DEMO,
            "is_active": True,
        },
    )
    return demo_account
