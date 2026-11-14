from django.contrib import admin
from accounts.models import MailAccount


@admin.register(MailAccount)
class MailAccountAdmin(admin.ModelAdmin):
    list_display = ("email", "display_name", "provider", "is_active", "updated_at")
    list_filter = ("provider", "is_active")
