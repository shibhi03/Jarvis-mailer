from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import MailAccount
from mail.models import EmailMessage
from mail.services.provider import get_active_account


class Command(BaseCommand):
    help = "Seed realistic demo emails for Jarvis Mailer"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Clear existing demo emails before seeding",
        )

    def handle(self, *args, **options):
        account = get_active_account()
        if account.provider != MailAccount.PROVIDER_DEMO:
            account, _ = MailAccount.objects.get_or_create(
                email="you@jarvismail.dev",
                defaults={
                    "display_name": "Alex Rivera",
                    "provider": MailAccount.PROVIDER_DEMO,
                    "is_active": False,
                },
            )

        if options["reset"]:
            EmailMessage.objects.filter(account=account).delete()

        if EmailMessage.objects.filter(account=account).exists() and not options["reset"]:
            self.stdout.write(self.style.NOTICE("Demo emails already exist. Use --reset to reseed."))
            return

        now = timezone.now()
        samples = [
            # Multi-message thread with Sarah Chen
            {
                "provider_message_id": "demo-msg-001",
                "thread_id": "thread-project-update",
                "folder": EmailMessage.FOLDER_INBOX,
                "sender_name": "Sarah Chen",
                "sender_email": "sarah.chen@nebulaknowlab.com",
                "recipient_email": account.email,
                "subject": "Q4 Project Update & Architecture Review",
                "body_text": (
                    "Hi Alex,\n\n"
                    "Here is the latest project update for Q4:\n"
                    "1. Real-time sync pipeline is passing all integration checks.\n"
                    "2. The AI co-pilot UI actions are ready for user testing.\n"
                    "3. Let's review the deployment checklist tomorrow at 11am.\n\n"
                    "Best,\nSarah"
                ),
                "is_read": False,
                "received_at": now - timedelta(hours=3),
            },
            {
                "provider_message_id": "demo-msg-001b",
                "thread_id": "thread-project-update",
                "folder": EmailMessage.FOLDER_SENT,
                "sender_name": account.display_name or "Alex Rivera",
                "sender_email": account.email,
                "recipient_email": "sarah.chen@nebulaknowlab.com",
                "subject": "Re: Q4 Project Update & Architecture Review",
                "body_text": (
                    "Thanks Sarah! I'll prepare the latency benchmarks before tomorrow's 11am review."
                ),
                "is_read": True,
                "received_at": now - timedelta(hours=2),
            },
            # David Kim (latest email from David)
            {
                "provider_message_id": "demo-msg-002",
                "thread_id": "thread-david-design",
                "folder": EmailMessage.FOLDER_INBOX,
                "sender_name": "David Kim",
                "sender_email": "david.kim@designstudio.io",
                "recipient_email": account.email,
                "subject": "Updated Dark Mode Palette & Sidebar Spacing",
                "body_text": (
                    "Hey Alex,\n\n"
                    "I pushed the updated Figma tokens for the dark mode palette and the 380px assistant sidebar.\n"
                    "Can you check the contrast on the unread badges when you have a moment?\n\n"
                    "Cheers,\nDavid"
                ),
                "is_read": False,
                "received_at": now - timedelta(days=1, hours=4),
            },
            {
                "provider_message_id": "demo-msg-003",
                "thread_id": "thread-david-older",
                "folder": EmailMessage.FOLDER_INBOX,
                "sender_name": "David Kim",
                "sender_email": "david.kim@designstudio.io",
                "recipient_email": account.email,
                "subject": "Initial Wireframes for Mail Client",
                "body_text": "Hi Alex, sharing the first draft of the three-pane layout.",
                "is_read": True,
                "received_at": now - timedelta(days=9),
            },
            # Unread within this week
            {
                "provider_message_id": "demo-msg-004",
                "thread_id": "thread-elena-api",
                "folder": EmailMessage.FOLDER_INBOX,
                "sender_name": "Elena Rostova",
                "sender_email": "elena@cloudinfra.dev",
                "recipient_email": account.email,
                "subject": "Pub/Sub Webhook Endpoint Verification",
                "body_text": (
                    "Hello,\n\n"
                    "Your Cloud Pub/Sub push subscription is now verified and delivering notifications to /api/webhooks/gmail/.\n"
                    "Average delivery latency is 140ms.\n\n"
                    "Regards,\nElena"
                ),
                "is_read": False,
                "received_at": now - timedelta(days=2, hours=6),
            },
            # Read within last 10 days
            {
                "provider_message_id": "demo-msg-005",
                "thread_id": "thread-john-meeting",
                "folder": EmailMessage.FOLDER_INBOX,
                "sender_name": "John Miller",
                "sender_email": "john@example.com",
                "recipient_email": account.email,
                "subject": "Sync on Product Roadmap",
                "body_text": (
                    "Hi Alex,\n\n"
                    "Let me know when you're free this week to walk through the Q1 roadmap items.\n\n"
                    "Thanks,\nJohn"
                ),
                "is_read": True,
                "received_at": now - timedelta(days=5),
            },
            {
                "provider_message_id": "demo-msg-006",
                "thread_id": "thread-github-pr",
                "folder": EmailMessage.FOLDER_INBOX,
                "sender_name": "GitHub",
                "sender_email": "notifications@github.com",
                "recipient_email": account.email,
                "subject": "[jarvis-mailer] PR #14: Add SSE real-time inbox stream",
                "body_text": (
                    "ramdarshan-nebulaknowlab approved pull request #14.\n"
                    "All 24 unit tests passed."
                ),
                "is_read": True,
                "received_at": now - timedelta(days=8),
            },
            # Older than 10 days
            {
                "provider_message_id": "demo-msg-007",
                "thread_id": "thread-stripe-invoice",
                "folder": EmailMessage.FOLDER_INBOX,
                "sender_name": "Stripe Billing",
                "sender_email": "billing@stripe.com",
                "recipient_email": account.email,
                "subject": "Your October Cloud Invoice is ready",
                "body_text": "Your payment of $29.00 was processed successfully.",
                "is_read": True,
                "received_at": now - timedelta(days=16),
            },
            {
                "provider_message_id": "demo-msg-008",
                "thread_id": "thread-sent-welcome",
                "folder": EmailMessage.FOLDER_SENT,
                "sender_name": account.display_name or "Alex Rivera",
                "sender_email": account.email,
                "recipient_email": "john@example.com",
                "subject": "Re: Onboarding Docs",
                "body_text": "Sent over the architecture overview and local setup guide!",
                "is_read": True,
                "received_at": now - timedelta(days=4),
            },
        ]

        for item in samples:
            snippet = " ".join(item["body_text"].split())[:140]
            EmailMessage.objects.create(
                account=account,
                snippet=snippet,
                **item,
            )

        self.stdout.write(self.style.SUCCESS(f"Seeded {len(samples)} demo emails for {account.email}."))
