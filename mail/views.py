import json
import uuid
from datetime import date, datetime, time, timedelta

from django.http import JsonResponse
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from mail.models import CalendarEvent, Contact, EmailMessage
from mail.services.contacts import sync_contacts_from_messages, upsert_contact
from mail.services.provider import get_active_account, get_provider_for_account
from mail.services.queries import query_emails
from mail.services.scheduler import dispatch_due_scheduled_emails
from mail.services.meeting_detection import detect_meeting_time


@ensure_csrf_cookie
@require_GET
def index(request):
    return render(request, "mail/index.html")


@require_GET
def list_emails(request):
    account = get_active_account()
    dispatch_due_scheduled_emails(account)
    folder = request.GET.get("folder", EmailMessage.FOLDER_INBOX)
    q = request.GET.get("q") or None
    sender = request.GET.get("sender") or None
    date_from = request.GET.get("date_from") or None
    date_to = request.GET.get("date_to") or None

    is_read_raw = request.GET.get("is_read", "").lower()
    is_read = None
    if is_read_raw == "true":
        is_read = True
    elif is_read_raw == "false":
        is_read = False

    days = None
    days_raw = request.GET.get("days")
    if days_raw:
        try:
            days = int(days_raw)
        except ValueError:
            days = None

    qs = query_emails(
        account,
        folder=folder,
        q=q,
        sender=sender,
        is_read=is_read,
        days=days,
        date_from=date_from,
        date_to=date_to,
    )
    try:
        page_size = min(100, max(1, int(request.GET.get("per_page", 25))))
    except (TypeError, ValueError):
        page_size = 25
    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    emails = [m.to_dict(include_body=False) for m in page_obj.object_list]
    unread_count = EmailMessage.objects.filter(
        account=account, folder=EmailMessage.FOLDER_INBOX, is_read=False
    ).count()

    return JsonResponse(
        {
            "emails": emails,
            "pagination": {"page": page_obj.number, "page_size": page_size,
                "total_count": paginator.count, "total_pages": paginator.num_pages,
                "has_next": page_obj.has_next(), "has_previous": page_obj.has_previous()},
            "unread_count": unread_count,
            "account": {
                "email": account.email,
                "display_name": account.display_name,
                "provider": account.provider,
            },
        }
    )


@require_GET
def email_detail(request, email_id: int):
    account = get_active_account()
    email = get_object_or_404(EmailMessage, id=email_id, account=account)

    if not email.is_read and email.folder == EmailMessage.FOLDER_INBOX:
        provider = get_provider_for_account(account)
        try:
            provider.mark_read(email, is_read=True)
        except Exception:
            email.is_read = True
            email.save(update_fields=["is_read"])

    thread_messages = (
        EmailMessage.objects.filter(account=account, thread_id=email.thread_id)
        .order_by("received_at", "id")
    )
    unread_count = EmailMessage.objects.filter(
        account=account, folder=EmailMessage.FOLDER_INBOX, is_read=False
    ).count()

    return JsonResponse(
        {
            "email": email.to_dict(include_body=True),
            "thread": [m.to_dict(include_body=True) for m in thread_messages],
            "unread_count": unread_count,
        }
    )


@require_POST
def send_email(request):
    account = get_active_account()
    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    to = (data.get("to") or "").strip()
    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or "").strip()
    thread_id = data.get("thread_id") or None
    in_reply_to = data.get("in_reply_to") or None

    if not to:
        return JsonResponse({"error": "Recipient 'to' is required"}, status=400)
    if not body and not subject:
        return JsonResponse({"error": "Subject or body is required"}, status=400)

    provider = get_provider_for_account(account)
    try:
        sent_msg = provider.send_message(
            to=to,
            subject=subject or "(No subject)",
            body=body,
            thread_id=thread_id,
            in_reply_to=in_reply_to,
        )
    except Exception as exc:
        return JsonResponse({"error": f"Failed to send email: {exc}"}, status=500)

    for addr in to.split(","):
        upsert_contact(account, "", addr.strip())

    draft_id = data.get("draft_id")
    if draft_id:
        EmailMessage.objects.filter(
            account=account,
            id=draft_id,
            folder__in=[EmailMessage.FOLDER_DRAFTS, EmailMessage.FOLDER_SCHEDULED],
        ).delete()

    return JsonResponse({"status": "sent", "email": sent_msg.to_dict(include_body=True)}, status=201)


@require_POST
def save_draft(request):
    account = get_active_account()
    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    draft_id = data.get("draft_id")
    to = (data.get("to") or "").strip()
    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or "").strip()
    thread_id = data.get("thread_id") or f"thread-{uuid.uuid4().hex[:10]}"
    in_reply_to = data.get("in_reply_to") or ""

    if draft_id:
        draft = EmailMessage.objects.filter(
            account=account, id=draft_id, folder=EmailMessage.FOLDER_DRAFTS
        ).first()
    else:
        draft = None

    if draft:
        draft.recipient_email = to
        draft.subject = subject or "(No subject)"
        draft.body_text = body
        draft.snippet = " ".join(body.split())[:140]
        draft.received_at = timezone.now()
        draft.save()
    else:
        draft = EmailMessage.objects.create(
            account=account,
            provider_message_id=f"draft-{uuid.uuid4().hex[:10]}",
            thread_id=thread_id,
            folder=EmailMessage.FOLDER_DRAFTS,
            sender_name=account.display_name or "Me",
            sender_email=account.email,
            recipient_email=to,
            subject=subject or "(No subject)",
            snippet=" ".join(body.split())[:140],
            body_text=body,
            is_read=True,
            in_reply_to=in_reply_to,
            received_at=timezone.now(),
        )
    return JsonResponse({"status": "saved", "email": draft.to_dict(include_body=True)}, status=201)


@require_POST
def schedule_email(request):
    account = get_active_account()
    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    if data.get("confirmed") is not True:
        return JsonResponse({"error": "Review the draft and explicitly confirm before scheduling."}, status=400)

    to = (data.get("to") or "").strip()
    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or "").strip()
    scheduled_raw = (data.get("scheduled_at") or "").strip()
    if not to:
        return JsonResponse({"error": "Recipient 'to' is required"}, status=400)
    if not scheduled_raw:
        return JsonResponse({"error": "Scheduled date/time is required"}, status=400)

    try:
        scheduled_dt = datetime.fromisoformat(scheduled_raw.replace("Z", "+00:00"))
        if timezone.is_naive(scheduled_dt):
            scheduled_dt = timezone.make_aware(scheduled_dt, timezone.get_current_timezone())
    except ValueError:
        return JsonResponse({"error": "Invalid scheduled_at datetime format"}, status=400)
    if scheduled_dt <= timezone.now():
        return JsonResponse({"error": "Scheduled time must be in the future."}, status=400)
    if not subject or not body.strip():
        return JsonResponse({"error": "Subject and message are required before scheduling."}, status=400)

    msg = EmailMessage.objects.create(
        account=account,
        provider_message_id=f"sched-{uuid.uuid4().hex[:10]}",
        thread_id=data.get("thread_id") or f"thread-{uuid.uuid4().hex[:10]}",
        folder=EmailMessage.FOLDER_SCHEDULED,
        sender_name=account.display_name or "Me",
        sender_email=account.email,
        recipient_email=to,
        subject=subject or "(No subject)",
        snippet=" ".join(body.split())[:140],
        body_text=body,
        is_read=True,
        in_reply_to=data.get("in_reply_to") or "",
        scheduled_at=scheduled_dt,
        received_at=timezone.now(),
    )
    draft_id = data.get("draft_id")
    if draft_id:
        EmailMessage.objects.filter(
            account=account, id=draft_id, folder=EmailMessage.FOLDER_DRAFTS
        ).delete()
    return JsonResponse({"status": "scheduled", "email": msg.to_dict(include_body=True)}, status=201)


@require_POST
def toggle_star(request, email_id: int):
    account = get_active_account()
    email = get_object_or_404(EmailMessage, id=email_id, account=account)
    email.is_starred = not email.is_starred
    email.save(update_fields=["is_starred"])
    return JsonResponse({"id": email.id, "is_starred": email.is_starred})


@require_POST
def move_email(request, email_id: int):
    account = get_active_account()
    email = get_object_or_404(EmailMessage, id=email_id, account=account)
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        data = {}
    target = (data.get("folder") or "").strip().lower()

    if target == "delete":
        email.delete()
        return JsonResponse({"status": "deleted"})

    allowed = {
        EmailMessage.FOLDER_INBOX,
        EmailMessage.FOLDER_SPAM,
        EmailMessage.FOLDER_BIN,
        EmailMessage.FOLDER_DRAFTS,
    }
    if target not in allowed:
        return JsonResponse({"error": "Invalid target folder"}, status=400)

    email.folder = target
    email.save(update_fields=["folder"])
    return JsonResponse({"status": "moved", "id": email.id, "folder": email.folder})


@require_POST
def toggle_read(request, email_id: int):
    account = get_active_account()
    email = get_object_or_404(EmailMessage, id=email_id, account=account)
    target = not email.is_read

    provider = get_provider_for_account(account)
    try:
        provider.mark_read(email, is_read=target)
    except Exception:
        email.is_read = target
        email.save(update_fields=["is_read"])

    unread_count = EmailMessage.objects.filter(
        account=account, folder=EmailMessage.FOLDER_INBOX, is_read=False
    ).count()
    return JsonResponse({"id": email.id, "is_read": email.is_read, "unread_count": unread_count})


@require_POST
def sync_now(request):
    account = get_active_account()
    provider = get_provider_for_account(account)
    try:
        added = provider.sync_messages(max_results=25)
    except Exception as exc:
        return JsonResponse({"error": f"Sync failed: {exc}"}, status=500)
    sync_contacts_from_messages(account)
    return JsonResponse({"status": "ok", "added": added, "provider": account.provider})


@require_http_methods(["GET", "POST"])
def contacts_list_create(request):
    account = get_active_account()
    if request.method == "GET":
        if not Contact.objects.filter(account=account).exists():
            sync_contacts_from_messages(account)
        q = (request.GET.get("q") or "").strip()
        qs = Contact.objects.filter(account=account)
        if q:
            qs = qs.filter(name__icontains=q) | qs.filter(email__icontains=q)
        return JsonResponse({"contacts": [c.to_dict() for c in qs.order_by("name")[:100]]})

    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    notes = (data.get("notes") or "").strip()
    if not email or "@" not in email:
        return JsonResponse({"error": "Valid email is required"}, status=400)
    if not name:
        name = email.split("@")[0].replace(".", " ").title()

    contact, _ = Contact.objects.update_or_create(
        account=account,
        email=email.lower(),
        defaults={"name": name, "notes": notes},
    )
    return JsonResponse({"contact": contact.to_dict()}, status=201)


@require_http_methods(["DELETE"])
def contact_delete(request, contact_id: int):
    account = get_active_account()
    contact = get_object_or_404(Contact, id=contact_id, account=account)
    contact.delete()
    return JsonResponse({"status": "deleted"})


@require_GET
def meeting_emails(request):
    account = get_active_account()
    try:
        client_offset = int(request.GET.get("tz_offset_minutes", 0))
    except (TypeError, ValueError):
        client_offset = 0
    client_tz = timezone.get_fixed_timezone(-client_offset)
    added_ids = set(CalendarEvent.objects.filter(
        account=account, source_email__isnull=False
    ).values_list("source_email_id", flat=True))
    candidates = []
    emails = EmailMessage.objects.filter(
        account=account, folder=EmailMessage.FOLDER_INBOX
    ).order_by("-received_at", "-id")[:1000]
    for email in emails:
        meeting = detect_meeting_time(email, client_tz)
        if meeting:
            meeting["already_added"] = email.id in added_ids
            candidates.append(meeting)
    if request.GET.get("pending") == "1":
        now = timezone.now()
        candidates = [
            meeting for meeting in candidates
            if not meeting["already_added"] and datetime.fromisoformat(meeting["start_at"]) > now
        ]
    now = timezone.now()
    candidates.sort(key=lambda event: (
        datetime.fromisoformat(event["start_at"]) < now,
        datetime.fromisoformat(event["start_at"]) if datetime.fromisoformat(event["start_at"]) >= now
        else -datetime.fromisoformat(event["start_at"]).timestamp(),
    ))
    paginator = Paginator(candidates, 25)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    return JsonResponse({
        "meetings": page_obj.object_list,
        "pagination": {"page": page_obj.number, "total_pages": paginator.num_pages,
            "total_count": paginator.count, "has_next": page_obj.has_next(),
            "has_previous": page_obj.has_previous()},
    })


@require_http_methods(["GET", "POST"])
def calendar_events(request):
    account = get_active_account()
    if request.method == "GET":
        if request.GET.get("view") == "list":
            try:
                page_number = max(1, int(request.GET.get("page", 1)))
            except (TypeError, ValueError):
                page_number = 1
            paginator = Paginator(
                CalendarEvent.objects.filter(account=account).select_related("source_email"), 25
            )
            page_obj = paginator.get_page(page_number)
            return JsonResponse({
                "events": [event.to_dict() for event in page_obj.object_list],
                "pagination": {"page": page_obj.number, "total_pages": paginator.num_pages,
                    "total_count": paginator.count, "has_next": page_obj.has_next(),
                    "has_previous": page_obj.has_previous()},
            })
        try:
            year, month = [int(part) for part in request.GET.get("month", "").split("-")]
            first_day = date(year, month, 1)
        except (TypeError, ValueError):
            today = timezone.localdate()
            first_day = date(today.year, today.month, 1)
        next_month = date(first_day.year + (first_day.month == 12), 1 if first_day.month == 12 else first_day.month + 1, 1)
        try:
            client_offset = int(request.GET.get("tz_offset_minutes", 0))
        except (TypeError, ValueError):
            client_offset = 0
        tz = timezone.get_fixed_timezone(-client_offset)
        start = timezone.make_aware(datetime.combine(first_day, time.min), tz)
        end = timezone.make_aware(datetime.combine(next_month, time.min), tz)
        events = CalendarEvent.objects.filter(
            account=account, start_at__gte=start, start_at__lt=end
        ).select_related("source_email")
        return JsonResponse({"events": [event.to_dict() for event in events]})

    try:
        data = json.loads(request.body.decode("utf-8"))
        if data.get("confirmed") is not True:
            return JsonResponse({"error": "Confirm the event before adding it to your calendar."}, status=400)
        email_id = data.get("email_id")
        email = get_object_or_404(EmailMessage, id=email_id, account=account) if email_id else None
        start_at = datetime.fromisoformat((data.get("start_at") or "").replace("Z", "+00:00"))
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({"error": "A valid source email and meeting time are required."}, status=400)
    if timezone.is_naive(start_at):
        start_at = timezone.make_aware(start_at, timezone.get_current_timezone())
    if start_at <= timezone.now():
        return JsonResponse({"error": "Event time must be in the future."}, status=400)
    try:
        reminder_minutes = int(data.get("reminder_minutes", 15))
    except (TypeError, ValueError):
        reminder_minutes = 15
    if reminder_minutes not in (0, 5, 10, 15, 30, 60):
        return JsonResponse({"error": "Choose a reminder from the available options."}, status=400)
    if email:
        event, created = CalendarEvent.objects.get_or_create(
            account=account,
            source_email=email,
            defaults={
                "title": email.subject or "Meeting from email",
                "description": email.body_text or email.snippet,
                "start_at": start_at,
                "all_day": bool(data.get("all_day")),
                "reminder_minutes": reminder_minutes,
            },
        )
        if not created:
            return JsonResponse({"error": "This email is already on your calendar.", "event": event.to_dict()}, status=409)
    else:
        title = (data.get("title") or "").strip()
        if not title:
            return JsonResponse({"error": "Event title is required."}, status=400)
        event = CalendarEvent.objects.create(
            account=account, title=title,
            description=(data.get("description") or "").strip(),
            start_at=start_at, all_day=bool(data.get("all_day")),
            reminder_minutes=reminder_minutes,
        )
    return JsonResponse({"event": event.to_dict()}, status=201)


@require_GET
def due_calendar_reminders(request):
    account = get_active_account()
    now = timezone.now()
    due = CalendarEvent.objects.filter(
        account=account, reminder_acknowledged=False,
        start_at__gt=now, start_at__lte=now + timedelta(days=1),
    )
    events = [event for event in due if event.start_at - timedelta(minutes=event.reminder_minutes) <= now]
    return JsonResponse({"reminders": [event.to_dict() for event in events]})


@require_POST
def acknowledge_calendar_reminder(request, event_id: int):
    account = get_active_account()
    event = get_object_or_404(CalendarEvent, id=event_id, account=account)
    event.reminder_acknowledged = True
    event.save(update_fields=["reminder_acknowledged"])
    return JsonResponse({"status": "acknowledged"})
