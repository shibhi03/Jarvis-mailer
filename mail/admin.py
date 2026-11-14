from django.contrib import admin
from mail.models import CalendarEvent, Contact, EmailMessage


@admin.register(EmailMessage)
class EmailMessageAdmin(admin.ModelAdmin):
    list_display = ("subject", "sender_email", "folder", "is_read", "received_at")
    list_filter = ("folder", "is_read")
    search_fields = ("subject", "sender_email", "sender_name", "body_text")


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "account", "updated_at")
    search_fields = ("name", "email")


@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = ("title", "account", "start_at", "reminder_minutes", "source_email")
    list_filter = ("all_day", "reminder_acknowledged")
    search_fields = ("title", "description")
