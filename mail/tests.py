import json
from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from accounts.models import MailAccount
from mail.models import EmailMessage
from mail.services.realtime import realtime_broker


class MailApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.account = MailAccount.objects.create(
            email="alex@jarvismail.dev",
            display_name="Alex Rivera",
            provider=MailAccount.PROVIDER_DEMO,
            is_active=True,
        )
        now = timezone.now()
        self.e1 = EmailMessage.objects.create(
            account=self.account,
            provider_message_id="m1",
            thread_id="t1",
            folder=EmailMessage.FOLDER_INBOX,
            sender_name="Sarah Chen",
            sender_email="sarah@example.com",
            recipient_email=self.account.email,
            subject="Project Update",
            body_text="All milestones are on track.",
            is_read=False,
            received_at=now - timedelta(days=2),
        )
        self.e2 = EmailMessage.objects.create(
            account=self.account,
            provider_message_id="m2",
            thread_id="t1",
            folder=EmailMessage.FOLDER_SENT,
            sender_name="Alex Rivera",
            sender_email=self.account.email,
            recipient_email="sarah@example.com",
            subject="Re: Project Update",
            body_text="Great news!",
            is_read=True,
            received_at=now - timedelta(days=1),
        )
        self.e3 = EmailMessage.objects.create(
            account=self.account,
            provider_message_id="m3",
            thread_id="t2",
            folder=EmailMessage.FOLDER_INBOX,
            sender_name="Old Billing",
            sender_email="billing@old.com",
            recipient_email=self.account.email,
            subject="Invoice",
            body_text="Paid.",
            is_read=True,
            received_at=now - timedelta(days=20),
        )

    def test_list_inbox_and_sent(self):
        inbox = self.client.get("/api/emails/?folder=inbox").json()
        self.assertEqual(len(inbox["emails"]), 2)
        self.assertEqual(inbox["unread_count"], 1)

        sent = self.client.get("/api/emails/?folder=sent").json()
        self.assertEqual(len(sent["emails"]), 1)
        self.assertEqual(sent["emails"][0]["subject"], "Re: Project Update")

    def test_filters(self):
        res_days = self.client.get("/api/emails/?folder=inbox&days=10").json()
        self.assertEqual(len(res_days["emails"]), 1)
        self.assertEqual(res_days["emails"][0]["sender_email"], "sarah@example.com")

        res_unread = self.client.get("/api/emails/?folder=inbox&is_read=false").json()
        self.assertEqual(len(res_unread["emails"]), 1)

        res_q = self.client.get("/api/emails/?folder=inbox&q=milestones").json()
        self.assertEqual(len(res_q["emails"]), 1)

    def test_email_detail_thread_and_mark_read(self):
        res = self.client.get(f"/api/emails/{self.e1.id}/").json()
        self.assertEqual(len(res["thread"]), 2)
        self.e1.refresh_from_db()
        self.assertTrue(self.e1.is_read)

    def test_send_email(self):
        res = self.client.post(
            "/api/emails/send/",
            data=json.dumps(
                {
                    "to": "john@example.com",
                    "subject": "Meeting Tomorrow",
                    "body": "Let's meet at 3pm",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        self.assertTrue(
            EmailMessage.objects.filter(
                folder=EmailMessage.FOLDER_SENT, recipient_email="john@example.com"
            ).exists()
        )

    def test_simulate_incoming_publishes_sse(self):
        q = realtime_broker.subscribe()
        try:
            res = self.client.post(
                "/api/mail/simulate-incoming/",
                data=json.dumps({"subject": "Realtime Test"}),
                content_type="application/json",
            )
            self.assertEqual(res.status_code, 200)
            event = q.get_nowait()
            self.assertEqual(event["event"], "new_email")
            self.assertEqual(event["data"]["subject"], "Realtime Test")
        finally:
            realtime_broker.unsubscribe(q)
