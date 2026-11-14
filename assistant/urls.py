from django.urls import path
from assistant import views

urlpatterns = [
    path("command/", views.assistant_command, name="assistant-command"),
]
