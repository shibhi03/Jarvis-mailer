from django.urls import path
from assistant import views

urlpatterns = [
    path("chats/", views.chats_list, name="assistant-chats"),
    path("chats/new/", views.chats_create, name="assistant-chat-create"),
    path("chats/<int:conversation_id>/", views.chat_detail, name="assistant-chat-detail"),
    path("command/", views.assistant_command, name="assistant-command"),
]
