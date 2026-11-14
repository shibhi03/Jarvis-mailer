import json
from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from accounts.models import MailAccount
from mail.models import EmailMessage


class AssistantCommandTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.account = MailAccount.objects.create(
            email="alex@jarvismail.dev",
            display_name="Alex Rivera",
            provider=MailAccount.PROVIDER_DEMO,
            is_active=True,
        )
        now = timezone.now()
        self.sarah_email = EmailMessage.objects.create(
            account=self.account,
            provider_message_id="s1",
            thread_id="t-sarah",
            folder=EmailMessage.FOLDER_INBOX,
            sender_name="Sarah Chen",
            sender_email="sarah@nebulaknowlab.com",
            recipient_email=self.account.email,
            subject="Q4 Project Update",
            body_text="Here is the project update for Q4.",
            is_read=False,
            received_at=now - timedelta(days=1),
        )
        self.david_older = EmailMessage.objects.create(
            account=self.account,
            provider_message_id="d1",
            thread_id="t-d1",
            folder=EmailMessage.FOLDER_INBOX,
            sender_name="David Kim",
            sender_email="david@design.io",
            recipient_email=self.account.email,
            subject="Old Wireframes",
            body_text="Initial draft.",
            is_read=True,
            received_at=now - timedelta(days=12),
        )
        self.david_latest = EmailMessage.objects.create(
            account=self.account,
            provider_message_id="d2",
            thread_id="t-d2",
            folder=EmailMessage.FOLDER_INBOX,
            sender_name="David Kim",
            sender_email="david@design.io",
            recipient_email=self.account.email,
            subject="Latest Dark Mode Palette",
            body_text="Updated tokens.",
            is_read=False,
            received_at=now - timedelta(hours=5),
        )

    def _ask(self, message, ui_context=None):
        return self.client.post(
            "/api/assistant/command/",
            data=json.dumps({"message": message, "ui_context": ui_context or {}}),
            content_type="application/json",
        ).json()

    def test_compose_and_fill_with_confirmation(self):
        res = self._ask(
            "Send an email to john@example.com with subject 'Meeting Tomorrow' and body 'Let's meet at 3pm'"
        )
        action_types = [a["type"] for a in res["ui_actions"]]
        self.assertIn("navigate_view", action_types)
        self.assertIn("fill_compose", action_types)

        fill = next(a for a in res["ui_actions"] if a["type"] == "fill_compose")
        self.assertEqual(fill["to"], "john@example.com")
        self.assertEqual(fill["subject"], "Meeting Tomorrow")
        self.assertEqual(fill["body"], "Let's meet at 3pm")
        self.assertEqual(res["rich_cards"][0]["type"], "send_confirmation")

    def test_search_last_10_days(self):
        res = self._ask("Show me emails from the last 10 days")
        action = res["ui_actions"][0]
        self.assertEqual(action["type"], "apply_filters")
        self.assertEqual(action["days"], 10)
        self.assertEqual(len(action["emails"]), 2)

    def test_find_sarah_project_update(self):
        res = self._ask("Find the email from Sarah about the project update")
        action = res["ui_actions"][0]
        self.assertEqual(action["type"], "apply_filters")
        self.assertEqual(len(action["emails"]), 1)
        self.assertEqual(action["emails"][0]["id"], self.sarah_email.id)

    def test_open_latest_email_from_david(self):
        res = self._ask("Open the latest email from David")
        action = res["ui_actions"][0]
        self.assertEqual(action["type"], "open_email")
        self.assertEqual(action["email"]["id"], self.david_latest.id)

    def test_context_aware_reply_to_open_email(self):
        res = self._ask(
            "Reply to this",
            ui_context={"current_view": "detail", "open_email_id": self.sarah_email.id},
        )
        fill = next(a for a in res["ui_actions"] if a["type"] == "fill_compose")
        self.assertEqual(fill["mode"], "reply")
        self.assertEqual(fill["to"], "sarah@nebulaknowlab.com")
        self.assertEqual(fill["subject"], "Re: Q4 Project Update")
        self.assertEqual(fill["thread_id"], "t-sarah")

    def test_unread_this_week_filter(self):
        res = self._ask("Show only unread emails from this week")
        action = res["ui_actions"][0]
        self.assertEqual(action["type"], "apply_filters")
        self.assertFalse(action["is_read"])
        self.assertEqual(action["days"], 7)
        self.assertEqual(len(action["emails"]), 2)
