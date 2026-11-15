import os

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from accounts.models import MailAccount
from mail.models import EmailMessage
from mail.services.gmail_provider import GmailMailProvider
from mail.services.provider import get_active_account


def _oauth_client_config() -> dict:
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
        }
    }


@require_GET
def google_login(request):
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        return JsonResponse(
            {
                "error": "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env."
            },
            status=400,
        )

    flow = Flow.from_client_config(
        _oauth_client_config(),
        scopes=settings.GMAIL_SCOPES,
        redirect_uri=settings.GOOGLE_REDIRECT_URI,
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    request.session["google_oauth_state"] = state
    request.session["google_oauth_code_verifier"] = flow.code_verifier
    return redirect(auth_url)


@require_GET
def google_callback(request):
    if settings.DEBUG:
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

    code = request.GET.get("code")
    if not code:
        return JsonResponse({"error": "Missing authorization code"}, status=400)

    flow = Flow.from_client_config(
        _oauth_client_config(),
        scopes=settings.GMAIL_SCOPES,
        state=request.session.get("google_oauth_state"),
        redirect_uri=settings.GOOGLE_REDIRECT_URI,
    )
    flow.code_verifier = request.session.get("google_oauth_code_verifier")
    flow.fetch_token(code=code)
    creds = flow.credentials

    oauth2_service = build("oauth2", "v2", credentials=creds, cache_discovery=False)
    user_info = oauth2_service.userinfo().get().execute()
    email = user_info.get("email")
    name = user_info.get("name", email)

    MailAccount.objects.filter(provider=MailAccount.PROVIDER_GMAIL).update(is_active=False)
    account, _ = MailAccount.objects.update_or_create(
        email=email,
        defaults={
            "display_name": name,
            "provider": MailAccount.PROVIDER_GMAIL,
            "access_token": creds.token or "",
            "refresh_token": creds.refresh_token or "",
            "token_expiry": creds.expiry,
            "is_active": True,
        },
    )

    provider = GmailMailProvider(account)
    try:
        provider.sync_messages(max_results=20)
        provider.fetch_user_profile()
        if settings.GMAIL_PUBSUB_TOPIC:
            provider.start_watch(settings.GMAIL_PUBSUB_TOPIC)
    except Exception:
        pass

    return redirect("/")


@csrf_exempt
@require_POST
def disconnect_gmail(request):
    MailAccount.objects.filter(provider=MailAccount.PROVIDER_GMAIL).update(is_active=False)
    return JsonResponse({"status": "disconnected", "active_provider": "demo"})


@require_GET
def auth_status(request):
    account = get_active_account()
    unread_count = EmailMessage.objects.filter(
        account=account, folder=EmailMessage.FOLDER_INBOX, is_read=False
    ).count()
    messages_count = EmailMessage.objects.filter(account=account).count()
    contacts_count = account.contacts.count()

    profile_details = {}
    if account.provider == MailAccount.PROVIDER_GMAIL:
        try:
            profile_details = GmailMailProvider(account).fetch_user_profile()
            account.refresh_from_db()
        except Exception:
            profile_details = {}
        if not account.display_name or account.display_name.lower() == account.email.lower():
            sent_name = (
                EmailMessage.objects.filter(
                    account=account,
                    folder=EmailMessage.FOLDER_SENT,
                    sender_email__iexact=account.email,
                )
                .exclude(sender_name="")
                .exclude(sender_name__iexact=account.email)
                .values_list("sender_name", flat=True)
                .first()
            )
            if sent_name:
                account.display_name = sent_name.strip()
                account.save(update_fields=["display_name", "updated_at"])

    return JsonResponse(
        {
            "email": account.email,
            "display_name": profile_details.get("display_name") or account.display_name or account.email,
            "given_name": profile_details.get("given_name", ""),
            "family_name": profile_details.get("family_name", ""),
            "picture": profile_details.get("picture", ""),
            "verified_email": profile_details.get("verified_email", False),
            "messages_total": profile_details.get("messages_total", messages_count),
            "threads_total": profile_details.get("threads_total"),
            "unread_count": unread_count,
            "contacts_count": contacts_count,
            "provider": account.provider,
            "oauth_configured": bool(
                settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET
            ),
            "pubsub_configured": bool(settings.GMAIL_PUBSUB_TOPIC),
        }
    )
