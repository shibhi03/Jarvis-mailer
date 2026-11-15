from django.utils import timezone

from accounts.models import MailAccount
from mail.models import EmailMessage
from mail.services.contacts import upsert_contact
from mail.services.provider import get_provider_for_account


def dispatch_due_scheduled_emails(account: MailAccount) -> int:
    """Send any scheduled emails whose scheduled_at <= now."""
    due = list(
        EmailMessage.objects.filter(
            account=account,
            folder=EmailMessage.FOLDER_SCHEDULED,
            scheduled_at__isnull=False,
            scheduled_at__lte=timezone.now(),
        )
    )
    if not due:
        return 0

    provider = get_provider_for_account(account)
    sent_count = 0
    for item in due:
        try:
            provider.send_message(
                to=item.recipient_email,
                subject=item.subject,
                body=item.body_text,
                thread_id=item.thread_id if not item.thread_id.startswith("thread-") else None,
                in_reply_to=item.in_reply_to or None,
                cc=item.cc_email or "",
                bcc=item.bcc_email or "",
            )
            for field_val in (item.recipient_email, item.cc_email, item.bcc_email):
                for addr in (field_val or "").split(","):
                    if addr.strip():
                        upsert_contact(account, "", addr.strip())
            item.delete()
            sent_count += 1
        except Exception:
            pass
    return sent_count
