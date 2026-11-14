from django.urls import path
from mail import realtime_views, views

urlpatterns = [
    path("", views.index, name="mail-home"),
    path("api/emails/", views.list_emails, name="list-emails"),
    path("api/emails/send/", views.send_email, name="send-email"),
    path("api/emails/draft/", views.save_draft, name="save-draft"),
    path("api/emails/schedule/", views.schedule_email, name="schedule-email"),
    path("api/meetings/", views.meeting_emails, name="meeting-emails"),
    path("api/calendar/events/", views.calendar_events, name="calendar-events"),
    path("api/calendar/reminders/", views.due_calendar_reminders, name="calendar-reminders"),
    path("api/calendar/reminders/<int:event_id>/ack/", views.acknowledge_calendar_reminder, name="calendar-reminder-ack"),
    path("api/emails/sync/", views.sync_now, name="sync-emails"),
    path("api/emails/<int:email_id>/", views.email_detail, name="email-detail"),
    path("api/emails/<int:email_id>/toggle-read/", views.toggle_read, name="toggle-read"),
    path("api/emails/<int:email_id>/star/", views.toggle_star, name="toggle-star"),
    path("api/emails/<int:email_id>/move/", views.move_email, name="move-email"),
    path("api/contacts/", views.contacts_list_create, name="contacts-list-create"),
    path("api/contacts/<int:contact_id>/", views.contact_delete, name="contact-delete"),
    path("api/mail/stream/", realtime_views.mail_stream, name="mail-stream"),
    path("api/mail/simulate-incoming/", realtime_views.simulate_incoming_email, name="simulate-incoming"),
    path("api/webhooks/gmail/", realtime_views.gmail_pubsub_webhook, name="gmail-webhook"),
]
