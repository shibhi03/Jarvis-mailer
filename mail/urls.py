from django.urls import path
from mail import realtime_views, views

urlpatterns = [
    path("", views.index, name="mail-home"),
    path("api/emails/", views.list_emails, name="list-emails"),
    path("api/emails/send/", views.send_email, name="send-email"),
    path("api/emails/sync/", views.sync_now, name="sync-emails"),
    path("api/emails/<int:email_id>/", views.email_detail, name="email-detail"),
    path("api/emails/<int:email_id>/toggle-read/", views.toggle_read, name="toggle-read"),
    path("api/contacts/", views.contacts_list_create, name="contacts-list-create"),
    path("api/contacts/<int:contact_id>/", views.contact_delete, name="contact-delete"),
    path("api/mail/stream/", realtime_views.mail_stream, name="mail-stream"),
    path("api/mail/simulate-incoming/", realtime_views.simulate_incoming_email, name="simulate-incoming"),
    path("api/webhooks/gmail/", realtime_views.gmail_pubsub_webhook, name="gmail-webhook"),
]
