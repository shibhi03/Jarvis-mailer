import json

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from assistant.services.agent import process_assistant_command
from mail.services.provider import get_active_account


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
    result = process_assistant_command(account, message, ui_context)
    return JsonResponse(result)
