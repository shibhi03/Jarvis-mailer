from django.db import models


class MailAccount(models.Model):
    PROVIDER_DEMO = "demo"
    PROVIDER_GMAIL = "gmail"
    PROVIDER_CHOICES = [
        (PROVIDER_DEMO, "Demo / Local"),
        (PROVIDER_GMAIL, "Google Gmail"),
    ]

    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=255, blank=True)
    provider = models.CharField(
        max_length=20, choices=PROVIDER_CHOICES, default=PROVIDER_DEMO
    )
    access_token = models.TextField(blank=True)
    refresh_token = models.TextField(blank=True)
    token_expiry = models.DateTimeField(null=True, blank=True)
    history_id = models.CharField(max_length=100, blank=True)
    watch_expiration = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.email} ({self.provider})"
