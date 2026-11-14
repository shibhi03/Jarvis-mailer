import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from mail.models import EmailMessage
from mail.services.provider import get_active_account, get_provider_for_account
from mail.services.queries import query_emails


@ensure_csrf_cookie
@require_GET
def index(request):
    return render(request, "mail/index.html")


@require_GET
def list_emails(request):
    account = get_active_account()
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
    emails = [m.to_dict(include_body=False) for m in qs[:100]]
    unread_count = EmailMessage.objects.filter(
        account=account, folder=EmailMessage.FOLDER_INBOX, is_read=False
    ).count()

    return JsonResponse(
        {
            "emails": emails,
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
    sent_msg = provider.send_message(
        to=to,
        subject=subject or "(No subject)",
        body=body,
        thread_id=thread_id,
        in_reply_to=in_reply_to,
    )
    return JsonResponse({"status": "sent", "email": sent_msg.to_dict(include_body=True)}, status=201)


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
    added = provider.sync_messages(max_results=25)
    return JsonResponse({"status": "ok", "added": added, "provider": account.provider})
