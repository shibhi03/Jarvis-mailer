from django.db import models
from django.utils import timezone

from accounts.models import MailAccount


class EmailMessage(models.Model):
    FOLDER_INBOX = "inbox"
    FOLDER_SENT = "sent"
    FOLDER_DRAFTS = "drafts"
    FOLDER_SPAM = "spam"
    FOLDER_BIN = "bin"
    FOLDER_SCHEDULED = "scheduled"
    FOLDER_CHOICES = [
        (FOLDER_INBOX, "Inbox"),
        (FOLDER_SENT, "Sent"),
        (FOLDER_DRAFTS, "Drafts"),
        (FOLDER_SPAM, "Spam"),
        (FOLDER_BIN, "Bin"),
        (FOLDER_SCHEDULED, "Scheduled"),
    ]

    account = models.ForeignKey(
        MailAccount,
        on_delete=models.CASCADE,
        related_name="messages",
        null=True,
        blank=True,
    )
    provider_message_id = models.CharField(max_length=255, db_index=True)
    thread_id = models.CharField(max_length=255, db_index=True)
    folder = models.CharField(
        max_length=20, choices=FOLDER_CHOICES, default=FOLDER_INBOX, db_index=True
    )
    sender_name = models.CharField(max_length=255, blank=True)
    sender_email = models.EmailField(db_index=True)
    recipient_email = models.TextField()
    subject = models.CharField(max_length=500, blank=True)
    snippet = models.TextField(blank=True)
    body_text = models.TextField(blank=True)
    body_html = models.TextField(blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    is_starred = models.BooleanField(default=False, db_index=True)
    in_reply_to = models.CharField(max_length=255, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True, db_index=True)
    received_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at", "-id"]
        indexes = [
            models.Index(fields=["folder", "received_at"]),
            models.Index(fields=["folder", "is_read"]),
        ]

    def __str__(self) -> str:
        return f"[{self.folder}] {self.subject} ({self.sender_email})"

    def to_dict(self, include_body: bool = False) -> dict:
        data = {
            "id": self.id,
            "provider_message_id": self.provider_message_id,
            "thread_id": self.thread_id,
            "folder": self.folder,
            "sender_name": self.sender_name or self.sender_email.split("@")[0],
            "sender_email": self.sender_email,
            "recipient_email": self.recipient_email,
            "subject": self.subject or "(No subject)",
            "snippet": self.snippet or (self.body_text[:140] if self.body_text else ""),
            "is_read": self.is_read,
            "is_starred": self.is_starred,
            "in_reply_to": self.in_reply_to,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "received_at": self.received_at.isoformat(),
        }
        if include_body:
            data["body_text"] = self.body_text
            data["body_html"] = self.body_html
        return data


class Contact(models.Model):
    account = models.ForeignKey(
        MailAccount,
        on_delete=models.CASCADE,
        related_name="contacts",
    )
    name = models.CharField(max_length=255, db_index=True)
    email = models.EmailField()
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "email"]
        unique_together = [("account", "email")]

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "notes": self.notes,
        }
