import json
from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from accounts.models import MailAccount
from mail.models import Contact, EmailMessage
from mail.services.contacts import upsert_contact
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

    def test_draft_star_spam_bin_and_scheduled(self):
        # Draft
        draft_res = self.client.post(
            "/api/emails/draft/",
            data=json.dumps({"to": "bob@example.com", "subject": "Draft 1", "body": "WIP"}),
            content_type="application/json",
        )
        self.assertEqual(draft_res.status_code, 201)
        self.assertEqual(len(self.client.get("/api/emails/?folder=drafts").json()["emails"]), 1)

        # Star
        star_res = self.client.post(f"/api/emails/{self.e1.id}/star/").json()
        self.assertTrue(star_res["is_starred"])
        self.assertEqual(len(self.client.get("/api/emails/?folder=starred").json()["emails"]), 1)

        # Spam & Bin
        self.client.post(
            f"/api/emails/{self.e1.id}/move/",
            data=json.dumps({"folder": "spam"}),
            content_type="application/json",
        )
        self.assertEqual(len(self.client.get("/api/emails/?folder=spam").json()["emails"]), 1)
        self.assertEqual(len(self.client.get("/api/emails/?folder=starred").json()["emails"]), 0)

        self.client.post(
            f"/api/emails/{self.e1.id}/move/",
            data=json.dumps({"folder": "bin"}),
            content_type="application/json",
        )
        self.assertEqual(len(self.client.get("/api/emails/?folder=bin").json()["emails"]), 1)

        # Scheduled send (past due -> auto-dispatched on list)
        past_time = (timezone.now() - timedelta(minutes=1)).isoformat()
        sched_res = self.client.post(
            "/api/emails/schedule/",
            data=json.dumps(
                {
                    "to": "tim@example.com",
                    "subject": "Scheduled Hello",
                    "body": "Sent automatically",
                    "scheduled_at": past_time,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(sched_res.status_code, 201)
        self.assertEqual(len(self.client.get("/api/emails/?folder=scheduled").json()["emails"]), 0)
        self.assertTrue(
            EmailMessage.objects.filter(
                folder=EmailMessage.FOLDER_SENT, recipient_email="tim@example.com"
            ).exists()
        )

    def test_noreply_emails_excluded_from_contact_book(self):
        self.assertIsNone(upsert_contact(self.account, "GitHub", "noreply@github.com"))
        self.assertIsNone(upsert_contact(self.account, "Stripe", "no-reply@stripe.com"))
        self.assertIsNone(upsert_contact(self.account, "No Reply", "notifications@service.com"))
        self.assertIsNotNone(upsert_contact(self.account, "Sarah Chen", "sarah@example.com"))
        self.assertEqual(Contact.objects.filter(account=self.account).count(), 1)
