from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("mail", "0003_emailmessage_is_starred_emailmessage_scheduled_at_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="CalendarEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=500)),
                ("description", models.TextField(blank=True)),
                ("start_at", models.DateTimeField(db_index=True)),
                ("end_at", models.DateTimeField(blank=True, null=True)),
                ("all_day", models.BooleanField(default=False)),
                ("reminder_minutes", models.PositiveSmallIntegerField(default=15)),
                ("reminder_acknowledged", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="calendar_events", to="accounts.mailaccount")),
                ("source_email", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="calendar_events", to="mail.emailmessage")),
            ],
            options={"ordering": ["start_at", "id"]},
        ),
        migrations.AddConstraint(
            model_name="calendarevent",
            constraint=models.UniqueConstraint(fields=("account", "source_email"), name="unique_calendar_event_per_source_email"),
        ),
    ]
