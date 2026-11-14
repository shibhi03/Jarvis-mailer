import base64
import json
import uuid

from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from accounts.models import MailAccount
from mail.models import EmailMessage
from mail.services.gmail_provider import GmailMailProvider
from mail.services.provider import get_active_account
from mail.services.realtime import realtime_broker


@require_GET
def mail_stream(request):
    """Server-Sent Events (SSE) stream for real-time inbox updates."""
    response = StreamingHttpResponse(
        realtime_broker.stream(heartbeat_seconds=15),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@csrf_exempt
@require_POST
def gmail_pubsub_webhook(request):
    """Receive Google Cloud Pub/Sub push notifications for Gmail."""
    token = request.GET.get("token") or request.headers.get("X-Webhook-Token", "")
    if settings.GMAIL_WEBHOOK_TOKEN and token != settings.GMAIL_WEBHOOK_TOKEN:
        return JsonResponse({"error": "Invalid webhook token"}, status=403)

    try:
        envelope = json.loads(request.body.decode("utf-8"))
        message_data = envelope.get("message", {}).get("data", "")
        decoded = json.loads(base64.b64decode(message_data).decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "Malformed Pub/Sub payload"}, status=400)

    email_address = decoded.get("emailAddress")
    history_id = decoded.get("historyId")
    if not email_address or not history_id:
        return JsonResponse({"status": "ignored"}, status=200)

    account = MailAccount.objects.filter(
        email=email_address, provider=MailAccount.PROVIDER_GMAIL, is_active=True
    ).first()
    if not account:
        return JsonResponse({"status": "account_not_found"}, status=200)

    provider = GmailMailProvider(account)
    added = provider.sync_history(str(history_id))
    return JsonResponse({"status": "ok", "added": added})


@require_POST
def simulate_incoming_email(request):
    """Simulate an incoming push email in Demo Mode and broadcast via SSE."""
    account = get_active_account()
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        payload = {}

    sender_name = payload.get("sender_name", "Sarah Chen")
    sender_email = payload.get("sender_email", "sarah.chen@nebulaknowlab.com")
    subject = payload.get("subject", "Live Push Notification: Urgent Sync")
    body = payload.get(
        "body",
        "Hey Alex, just testing real-time push delivery—this arrived without a manual refresh!",
    )

    msg = EmailMessage.objects.create(
        account=account,
        provider_message_id=f"push-{uuid.uuid4().hex[:10]}",
        thread_id=payload.get("thread_id") or f"thread-{uuid.uuid4().hex[:8]}",
        folder=EmailMessage.FOLDER_INBOX,
        sender_name=sender_name,
        sender_email=sender_email,
        recipient_email=account.email,
        subject=subject,
        snippet=" ".join(body.split())[:140],
        body_text=body,
        is_read=False,
        received_at=timezone.now(),
    )
    delivered = realtime_broker.publish("new_email", msg.to_dict())
    return JsonResponse({"status": "ok", "email": msg.to_dict(), "sse_clients": delivered})
