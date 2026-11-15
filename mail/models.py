from datetime import timedelta

from django.db import models
from django.db.models import Q
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
    cc_email = models.TextField(blank=True, default="")
    bcc_email = models.TextField(blank=True, default="")
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
            "cc_email": self.cc_email,
            "bcc_email": self.bcc_email,
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


class CalendarEvent(models.Model):
    account = models.ForeignKey(MailAccount, on_delete=models.CASCADE, related_name="calendar_events")
    source_email = models.ForeignKey(
        EmailMessage, on_delete=models.SET_NULL, null=True, blank=True, related_name="calendar_events"
    )
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    attendees = models.TextField(blank=True, default="")
    start_at = models.DateTimeField(db_index=True)
    end_at = models.DateTimeField(null=True, blank=True)
    all_day = models.BooleanField(default=False)
    reminder_minutes = models.PositiveSmallIntegerField(default=15)
    reminder_acknowledged = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["account", "source_email"], name="unique_calendar_event_per_source_email")
        ]

    @staticmethod
    def _split_addresses(*raw_values: str) -> list:
        seen = set()
        result = []
        for raw in raw_values:
            if not raw:
                continue
            for part in str(raw).replace(";", ",").split(","):
                addr = part.strip()
                if not addr:
                    continue
                key = addr.lower()
                if key not in seen:
                    seen.add(key)
                    result.append(addr)
        return result

    def _associated_sent_emails(self) -> list:
        clean_title = (self.title or "").strip()
        subject_q = Q()
        if clean_title:
            subject_q = (
                Q(subject__iexact=clean_title)
                | Q(subject__iexact=f"Invitation: {clean_title}")
                | Q(subject__iexact=f"Update: {clean_title}")
                | Q(subject__iexact=f"Updated Event: {clean_title}")
            )
        sent_by_id = {}
        if self.source_email and self.source_email.folder == EmailMessage.FOLDER_SENT:
            sent_by_id[self.source_email.id] = self.source_email
            if self.source_email.thread_id:
                subject_q = subject_q | Q(thread_id=self.source_email.thread_id)
        if subject_q:
            qs = EmailMessage.objects.filter(
                account_id=self.account_id,
                folder=EmailMessage.FOLDER_SENT,
            ).filter(subject_q).order_by("-received_at", "-id")[:10]
            for msg in qs:
                sent_by_id.setdefault(msg.id, msg)
        return sorted(sent_by_id.values(), key=lambda m: (m.received_at, m.id), reverse=True)

    def to_dict(self) -> dict:
        source_is_received = (
            self.source_email is not None
            and self.source_email.folder != EmailMessage.FOLDER_SENT
        )
        is_user_created = not source_is_received
        received_email = self.source_email.to_dict(include_body=True) if source_is_received else None

        sent_objs = self._associated_sent_emails()
        sent_emails = [
            {
                "id": msg.id,
                "subject": msg.subject or "(No subject)",
                "recipient_email": msg.recipient_email,
                "cc_email": msg.cc_email,
                "bcc_email": msg.bcc_email,
                "received_at": msg.received_at.isoformat(),
                "snippet": msg.snippet or (msg.body_text[:140] if msg.body_text else ""),
                "body_text": msg.body_text,
            }
            for msg in sent_objs
        ]
        sent_raw_parts = [self.attendees]
        if self.source_email and self.source_email.folder == EmailMessage.FOLDER_SENT:
            sent_raw_parts.extend([
                self.source_email.recipient_email,
                self.source_email.cc_email,
                self.source_email.bcc_email,
            ])
        for msg in sent_objs:
            sent_raw_parts.extend([msg.recipient_email, msg.cc_email, msg.bcc_email])
        sent_to = ", ".join(self._split_addresses(*sent_raw_parts))

        if source_is_received:
            email_direction = "received"
        elif sent_emails or (self.attendees or "").strip() or (
            self.source_email and self.source_email.folder == EmailMessage.FOLDER_SENT
        ):
            email_direction = "sent"
        else:
            email_direction = None

        return {
            "id": self.id,
            "source_email_id": self.source_email_id,
            "title": self.title,
            "description": self.description,
            "attendees": self.attendees,
            "is_user_created": is_user_created,
            "email_direction": email_direction,
            "sent_to": sent_to,
            "sent_emails": sent_emails,
            "received_email": received_email,
            "start_at": self.start_at.isoformat(),
            "end_at": self.end_at.isoformat() if self.end_at else None,
            "all_day": self.all_day,
            "reminder_minutes": self.reminder_minutes,
            "reminder_at": (self.start_at - timedelta(minutes=self.reminder_minutes)).isoformat(),
        }
