from django.urls import path
from mail import realtime_views

urlpatterns = [
    path("api/mail/stream/", realtime_views.mail_stream, name="mail-stream"),
    path("api/mail/simulate-incoming/", realtime_views.simulate_incoming_email, name="simulate-incoming"),
    path("api/webhooks/gmail/", realtime_views.gmail_pubsub_webhook, name="gmail-webhook"),
]
