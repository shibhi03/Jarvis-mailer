from datetime import datetime, time, timedelta
from typing import Optional

from django.db.models import Q, QuerySet
from django.utils import timezone

from accounts.models import MailAccount
from mail.models import EmailMessage


def _parse_date(value: Optional[str], end_of_day: bool = False) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed_date = datetime.strptime(value.strip(), "%Y-%m-%d").date()
        dt = datetime.combine(parsed_date, time.max if end_of_day else time.min)
        return timezone.make_aware(dt, timezone.get_current_timezone())
    except ValueError:
        return None


def query_emails(
    account: MailAccount,
    *,
    folder: Optional[str] = EmailMessage.FOLDER_INBOX,
    q: Optional[str] = None,
    sender: Optional[str] = None,
    is_read: Optional[bool] = None,
    days: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> QuerySet[EmailMessage]:
    """Filter emails for an account using shared criteria for UI and AI Assistant."""
    qs = EmailMessage.objects.filter(account=account)

    if folder == "starred":
        qs = qs.filter(is_starred=True).exclude(
            folder__in=[EmailMessage.FOLDER_SPAM, EmailMessage.FOLDER_BIN]
        )
    elif folder in (
        EmailMessage.FOLDER_INBOX,
        EmailMessage.FOLDER_SENT,
        EmailMessage.FOLDER_DRAFTS,
        EmailMessage.FOLDER_SPAM,
        EmailMessage.FOLDER_BIN,
        EmailMessage.FOLDER_SCHEDULED,
    ):
        qs = qs.filter(folder=folder)
    else:
        qs = qs.exclude(folder__in=[EmailMessage.FOLDER_SPAM, EmailMessage.FOLDER_BIN])

    if q:
        term = q.strip()
        qs = qs.filter(
            Q(subject__icontains=term)
            | Q(body_text__icontains=term)
            | Q(sender_name__icontains=term)
            | Q(sender_email__icontains=term)
            | Q(recipient_email__icontains=term)
        )

    if sender:
        s = sender.strip()
        qs = qs.filter(Q(sender_name__icontains=s) | Q(sender_email__icontains=s))

    if is_read is not None:
        qs = qs.filter(is_read=is_read)

    if days is not None and days > 0:
        cutoff = timezone.now() - timedelta(days=days)
        qs = qs.filter(received_at__gte=cutoff)

    dt_from = _parse_date(date_from, end_of_day=False)
    if dt_from:
        qs = qs.filter(received_at__gte=dt_from)

    dt_to = _parse_date(date_to, end_of_day=True)
    if dt_to:
        qs = qs.filter(received_at__lte=dt_to)

    return qs.order_by("-received_at", "-id")
