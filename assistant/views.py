import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from assistant.models import AssistantConversation, AssistantMessage
from assistant.services.agent import process_assistant_command
from mail.services.provider import get_active_account


def _conversation_dict(conversation):
    last_message = conversation.messages.order_by("-created_at", "-id").first()
    return {
        "id": conversation.id,
        "title": conversation.title,
        "updated_at": conversation.updated_at.isoformat(),
        "last_message": last_message.content[:120] if last_message else "",
    }


def _latest_chat_context(history):
    for turn in reversed(history):
        if turn.get("role") != AssistantMessage.ROLE_ASSISTANT:
            continue
        stored = turn.get("context") or {}
        context = dict(stored.get("ui_context") or {})
        context.pop("chat_context", None)
        for action in stored.get("ui_actions") or []:
            if action.get("type") == "open_email" and action.get("email"):
                context["open_email_id"] = action["email"].get("id")
                context["current_view"] = "detail"
            elif action.get("type") == "close_email":
                context["open_email_id"] = None
            elif action.get("type") == "navigate_view":
                context["current_view"] = action.get("view", context.get("current_view"))
            elif action.get("type") == "apply_filters":
                context["current_view"] = action.get("folder", "inbox")
                context["active_filters"] = {
                    key: action.get(key)
                    for key in ("q", "sender", "is_read", "days", "date_from", "date_to")
                    if action.get(key) not in (None, "")
                }
                context["open_email_id"] = None
            elif action.get("type") == "fill_compose":
                context["current_view"] = "compose"
                context["compose_draft"] = {
                    key: action.get(key, "") for key in ("to", "subject", "body")
                }
            elif action.get("type") == "update_compose_draft":
                context["current_view"] = "compose"
                context["compose_draft"] = {
                    key: action.get(key, "") for key in ("to", "subject", "body")
                }
        return context
    return {}


@require_GET
def chats_list(request):
    account = get_active_account()
    chats = AssistantConversation.objects.filter(account=account)[:100]
    return JsonResponse({"chats": [_conversation_dict(chat) for chat in chats]})


@require_POST
def chats_create(request):
    account = get_active_account()
    conversation = AssistantConversation.objects.create(account=account)
    return JsonResponse({"chat": _conversation_dict(conversation)}, status=201)


@require_GET
def chat_detail(request, conversation_id: int):
    account = get_active_account()
    conversation = get_object_or_404(
        AssistantConversation, id=conversation_id, account=account
    )
    messages = [
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "context": message.context,
            "rich_cards": message.rich_cards,
            "agent_steps": message.agent_steps,
            "created_at": message.created_at.isoformat(),
        }
        for message in conversation.messages.all()
    ]
    return JsonResponse({"chat": _conversation_dict(conversation), "messages": messages})


@require_POST
def assistant_command(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    message = (payload.get("message") or "").strip()
    ui_context = payload.get("ui_context") or {}
    if not message:
        return JsonResponse({"error": "Message is required"}, status=400)

    account = get_active_account()
    conversation_id = payload.get("conversation_id")
    if conversation_id:
        conversation = get_object_or_404(
            AssistantConversation, id=conversation_id, account=account
        )
    else:
        conversation = AssistantConversation.objects.create(account=account)

    history = list(
        conversation.messages.values("role", "content", "context").order_by(
            "created_at", "id"
        )
    )
    ui_context["chat_context"] = _latest_chat_context(history)
    AssistantMessage.objects.create(
        conversation=conversation,
        role=AssistantMessage.ROLE_USER,
        content=message,
        context=ui_context,
    )
    if conversation.title == "New chat":
        conversation.title = message[:117] + ("..." if len(message) > 120 else "")

    result = process_assistant_command(account, message, ui_context, history=history)
    action_log = []
    for step in result.get("agent_steps", []):
        action_log.append({"action": step, "at": timezone.now().isoformat()})
    for action in result.get("ui_actions", []):
        details = {key: action[key] for key in ("view", "folder", "id", "theme") if key in action}
        action_log.append({"action": action.get("type", "UI action"), "details": details, "at": timezone.now().isoformat()})
    AssistantMessage.objects.create(
        conversation=conversation,
        role=AssistantMessage.ROLE_ASSISTANT,
        content=result.get("reply", "Done."),
        context={"ui_context": ui_context, "ui_actions": result.get("ui_actions", []), "action_log": action_log},
        rich_cards=result.get("rich_cards", []),
        agent_steps=result.get("agent_steps", []),
    )
    conversation.updated_at = timezone.now()
    conversation.save(update_fields=["title", "updated_at"])
    result["conversation_id"] = conversation.id
    return JsonResponse(result)
