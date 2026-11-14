import json
from typing import Any, Dict

from django.conf import settings

from accounts.models import MailAccount
from assistant.services.fallback_nlu import run_fallback_nlu
from assistant.services.tools import (
    execute_compose_tool,
    execute_forward_open_email,
    execute_open_email_tool,
    execute_reply_open_email,
    execute_save_contact_tool,
    execute_search_tool,
)
from mail.models import Contact, EmailMessage

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "compose_email",
            "description": "Open the compose UI and visibly fill in recipient, subject, and body.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_emails",
            "description": "Search and filter emails and update the main UI list with the results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "enum": ["inbox", "sent"]},
                    "q": {"type": "string"},
                    "sender": {"type": "string"},
                    "is_read": {"type": "boolean"},
                    "days": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_email",
            "description": "Navigate to and open a specific email (e.g. latest email, by sender name, or by date) in the detail view.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sender": {"type": "string"},
                    "q": {"type": "string"},
                    "folder": {"type": "string", "enum": ["inbox", "sent", "all"]},
                    "days": {"type": "integer"},
                    "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                    "date_to": {"type": "string", "description": "YYYY-MM-DD"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_contact",
            "description": "Save a person's name and email address to the Contact Book.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                },
                "required": ["name", "email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reply_to_open_email",
            "description": "Pre-fill a reply to the currently open email in the detail view.",
            "parameters": {
                "type": "object",
                "properties": {
                    "custom_body": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forward_open_email",
            "description": "Forward the currently open email to a recipient.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                },
            },
        },
    },
]


def _build_context_summary(account: MailAccount, ui_context: Dict[str, Any]) -> str:
    current_view = ui_context.get("current_view", "inbox")
    open_email_id = ui_context.get("open_email_id")
    parts = [f"Current UI view: {current_view}"]
    if open_email_id:
        email = EmailMessage.objects.filter(account=account, id=open_email_id).first()
        if email:
            parts.append(
                f"Currently open email (id={email.id}): From {email.sender_name} <{email.sender_email}>, "
                f"Subject: '{email.subject}', Snippet: '{email.snippet}'"
            )
    if ui_context.get("active_filters"):
        parts.append(f"Active filters: {json.dumps(ui_context['active_filters'])}")
    contacts = list(Contact.objects.filter(account=account).values_list("name", "email")[:20])
    if contacts:
        parts.append("Known contacts: " + ", ".join(f"{n} <{e}>" for n, e in contacts))
    return "\n".join(parts)


def _dispatch_tool(
    account: MailAccount, name: str, args: Dict[str, Any], ui_context: Dict[str, Any]
) -> Dict[str, Any]:
    if name == "compose_email":
        return execute_compose_tool(
            to=args.get("to", ""),
            subject=args.get("subject", ""),
            body=args.get("body", ""),
            account=account,
        )
    if name == "search_emails":
        return execute_search_tool(
            account,
            folder=args.get("folder", "inbox"),
            q=args.get("q"),
            sender=args.get("sender"),
            is_read=args.get("is_read"),
            days=args.get("days"),
        )
    if name == "open_email":
        return execute_open_email_tool(
            account,
            sender=args.get("sender"),
            q=args.get("q"),
            folder=args.get("folder"),
            days=args.get("days"),
            date_from=args.get("date_from"),
            date_to=args.get("date_to"),
        )
    if name == "save_contact":
        return execute_save_contact_tool(
            account,
            name=args.get("name", ""),
            email=args.get("email", ""),
        )
    if name == "reply_to_open_email":
        return execute_reply_open_email(
            account,
            open_email_id=ui_context.get("open_email_id"),
            custom_body=args.get("custom_body"),
        )
    if name == "forward_open_email":
        return execute_forward_open_email(
            account,
            open_email_id=ui_context.get("open_email_id"),
            to=args.get("to", ""),
        )
    return {"reply": "Done.", "ui_actions": [], "rich_cards": []}


def _run_openai(
    account: MailAccount, message: str, ui_context: Dict[str, Any]
) -> Dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    system_prompt = (
        "You are Jarvis, an AI co-pilot embedded in a mail web application. "
        "You control the UI directly via tool calls. Always call the appropriate tool "
        "when the user asks to compose, send, search, filter, open, reply, or forward emails.\n\n"
        + _build_context_summary(account, ui_context)
    )
    resp = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        tools=OPENAI_TOOLS,
        tool_choice="auto",
        temperature=0.1,
    )
    choice = resp.choices[0].message
    if choice.tool_calls:
        tc = choice.tool_calls[0]
        args = json.loads(tc.function.arguments or "{}")
        return _dispatch_tool(account, tc.function.name, args, ui_context)
    return {
        "reply": choice.content or "How can I help with your inbox?",
        "ui_actions": [],
        "rich_cards": [],
    }


def process_assistant_command(
    account: MailAccount, message: str, ui_context: Dict[str, Any]
) -> Dict[str, Any]:
    if settings.OPENAI_API_KEY:
        try:
            return _run_openai(account, message, ui_context)
        except Exception:
            pass
    return run_fallback_nlu(account, message, ui_context)
