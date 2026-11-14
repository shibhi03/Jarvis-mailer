from django.contrib import admin
from mail.models import EmailMessage


@admin.register(EmailMessage)
class EmailMessageAdmin(admin.ModelAdmin):
    list_display = ("subject", "sender_email", "folder", "is_read", "received_at")
    list_filter = ("folder", "is_read")
    search_fields = ("subject", "sender_email", "sender_name", "body_text")
