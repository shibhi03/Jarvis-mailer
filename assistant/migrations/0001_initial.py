# Generated for persistent, account-scoped assistant chats.
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="AssistantConversation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(default="New chat", max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assistant_conversations", to="accounts.mailaccount")),
            ],
            options={"ordering": ["-updated_at", "-id"]},
        ),
        migrations.CreateModel(
            name="AssistantMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("user", "User"), ("assistant", "Assistant")], max_length=12)),
                ("content", models.TextField()),
                ("context", models.JSONField(blank=True, default=dict)),
                ("rich_cards", models.JSONField(blank=True, default=list)),
                ("agent_steps", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("conversation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="messages", to="assistant.assistantconversation")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
    ]
