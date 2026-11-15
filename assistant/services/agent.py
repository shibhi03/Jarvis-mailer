import json
import re
from typing import Any, Dict, List

from django.conf import settings

from accounts.models import MailAccount
from assistant.services.fallback_nlu import get_client_tz, is_local_ui_intent, run_fallback_nlu
from assistant.services.tools import (
    execute_clear_bin_tool,
    execute_close_email_tool,
    execute_compose_tool,
    execute_create_calendar_event_tool,
    execute_delete_calendar_event_tool,
    execute_delete_contact_tool,
    execute_delete_email_tool,
    execute_disconnect_gmail_tool,
    execute_edit_calendar_event_tool,
    execute_edit_contact_tool,
    execute_forward_open_email,
    execute_list_calendar_events_tool,
    execute_mark_read_open_email,
    execute_move_open_email,
    execute_new_chat_tool,
    execute_open_email_tool,
    execute_read_email_detail,
    execute_reply_open_email,
    execute_restore_email_tool,
    execute_save_contact_tool,
    execute_save_draft_tool,
    execute_schedule_tool,
    execute_search_tool,
    execute_simulate_incoming_tool,
    execute_star_open_email,
    execute_sync_now_tool,
    execute_trigger_ui_button_tool,
    execute_user_profile_tool,
)
from mail.models import CalendarEvent, Contact, EmailMessage
from mail.services.contacts import resolve_recipient

DRAFTING_TOOLS = {
    "compose_email",
    "reply_to_open_email",
    "forward_open_email",
    "schedule_email",
}

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "compose_email",
            "description": "Draft a new email in the compose UI with one or more To, optional CC, optional BCC recipients, subject, and body, and show a confirmation card. Use this when the user asks to draft, compose, write, or send an email. NEVER call submit_compose in the same turn; always wait for user confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "One or more recipient emails or contact names (comma-separated for multiple recipients)."},
                    "cc": {"type": "string", "description": "Optional CC recipient emails or contact names (comma-separated)."},
                    "bcc": {"type": "string", "description": "Optional BCC recipient emails or contact names (comma-separated)."},
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
            "name": "schedule_email",
            "description": "Prepare a scheduled email draft in the compose UI with one or more recipients (To, optional CC/BCC) and a future ISO datetime, and show a scheduling confirmation card. Always wait for user confirmation before scheduling.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "One or more recipient emails or contact names (comma-separated for multiple recipients)."},
                    "cc": {"type": "string", "description": "Optional CC recipient emails or contact names (comma-separated)."},
                    "bcc": {"type": "string", "description": "Optional BCC recipient emails or contact names (comma-separated)."},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "scheduled_at": {"type": "string"},
                },
                "required": ["to", "subject", "body", "scheduled_at"],
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
                    "folder": {
                        "type": "string",
                        "enum": ["inbox", "starred", "sent", "drafts", "scheduled", "spam", "bin"],
                    },
                    "q": {"type": "string"},
                    "sender": {"type": "string"},
                    "is_read": {"type": "boolean"},
                    "days": {"type": "integer"},
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_email_detail",
            "description": "Read the full body and conversation thread of an email to summarize or inspect it before acting.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_id": {"type": "integer"},
                    "sender": {"type": "string"},
                    "q": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_email",
            "description": "Navigate the main UI to open a specific email (latest, by sender, or by date).",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_id": {"type": "integer"},
                    "sender": {"type": "string"},
                    "q": {"type": "string"},
                    "folder": {"type": "string", "enum": ["inbox", "sent", "all"]},
                    "days": {"type": "integer"},
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_email",
            "description": "Close the currently open email detail view and return to the email list.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reply_to_open_email",
            "description": "Pre-fill a reply draft to the currently open email in the compose UI and wait for user confirmation before sending.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_id": {"type": "integer"},
                    "custom_body": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forward_open_email",
            "description": "Pre-fill a forward draft of the currently open email in the compose UI and wait for user confirmation before sending.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_id": {"type": "integer"},
                    "to": {"type": "string", "description": "One or more recipient emails or contact names (comma-separated for multiple recipients)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "star_email",
            "description": "Star or unstar an email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_id": {"type": "integer"},
                    "starred": {"type": "boolean"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_email",
            "description": "Move one or more emails to inbox, spam, or bin (by open email, email_id, subject, sender/contact name, or email address).",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_id": {"type": "integer"},
                    "folder": {"type": "string", "enum": ["inbox", "spam", "bin", "restore"]},
                    "subject": {"type": "string"},
                    "sender": {"type": "string"},
                    "email_address": {"type": "string"},
                    "name": {"type": "string"},
                    "q": {"type": "string"},
                    "move_all": {"type": "boolean"},
                },
                "required": ["folder"],
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
            "name": "lookup_contact",
            "description": "Look up a person's email address in the Contact Book by name.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_draft",
            "description": "Save an email directly into the Drafts folder (use compose_email instead when the user wants to draft an email interactively in Compose and confirm before sending).",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "One or more recipient emails or contact names (comma-separated for multiple recipients)."},
                    "cc": {"type": "string", "description": "Optional CC recipient emails or contact names (comma-separated)."},
                    "bcc": {"type": "string", "description": "Optional BCC recipient emails or contact names (comma-separated)."},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_read_status",
            "description": "Mark the currently open email as read or unread.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_id": {"type": "integer"},
                    "is_read": {"type": "boolean"},
                },
                "required": ["is_read"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_theme",
            "description": "Switch the UI between dark mode and light mode.",
            "parameters": {
                "type": "object",
                "properties": {"theme": {"type": "string", "enum": ["dark", "light"]}},
                "required": ["theme"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sync_mailbox",
            "description": "Sync / refresh emails from the connected mail provider.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_contacts",
            "description": "Navigate the UI to the Contact Book view.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_compose",
            "description": "Send an email that was ALREADY drafted in an earlier turn ONLY when the user explicitly confirms sending (e.g. 'send it', 'confirm send', 'yes send'). Never call this in the same turn that drafts, replies, forwards, or schedules an email.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discard_compose",
            "description": "Discard the current compose draft and return to the folder list.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_email",
            "description": "Move matching emails to Bin (by subject, email address/ID, sender/contact name, or query), or permanently delete scheduled, draft, or bin emails (or when permanent=true).",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_id": {"type": "integer"},
                    "folder": {
                        "type": "string",
                        "enum": ["inbox", "sent", "drafts", "scheduled", "spam", "bin", "all"],
                    },
                    "subject": {"type": "string"},
                    "sender": {"type": "string"},
                    "recipient": {"type": "string"},
                    "email_address": {"type": "string"},
                    "name": {"type": "string"},
                    "q": {"type": "string"},
                    "permanent": {"type": "boolean"},
                    "delete_all": {"type": "boolean"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "restore_email",
            "description": "Restore one or more emails from the Bin folder back to Inbox (by open email, email_id, subject, email address, or sender/contact name).",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_id": {"type": "integer"},
                    "subject": {"type": "string"},
                    "sender": {"type": "string"},
                    "email_address": {"type": "string"},
                    "name": {"type": "string"},
                    "q": {"type": "string"},
                    "restore_all": {"type": "boolean"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_bin",
            "description": "Permanently delete all emails in the Bin folder.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_contact",
            "description": "Edit an existing contact's name, email address, or notes in the Contact Book.",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                    "target_name": {"type": "string"},
                    "target_email": {"type": "string"},
                    "new_name": {"type": "string"},
                    "new_email": {"type": "string"},
                    "new_notes": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_calendar_events",
            "description": "Open the Calendar view and list upcoming events and meetings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "upcoming_only": {"type": "boolean"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "Create a new event on the Calendar, and optionally prepare an email draft in Compose to inform attendees (waiting for user confirmation before sending).",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start_at": {"type": "string"},
                    "description": {"type": "string"},
                    "reminder_minutes": {"type": "integer"},
                    "attendees": {"type": "string"},
                    "inform_via_email": {"type": "boolean"},
                },
                "required": ["title", "start_at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_calendar_event",
            "description": "Edit a user-created Calendar event (title, date/time, description, reminder, attendees), and optionally prepare an email draft in Compose to inform attendees about the update (waiting for user confirmation before sending).",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "integer"},
                    "target_title": {"type": "string"},
                    "new_title": {"type": "string"},
                    "start_at": {"type": "string"},
                    "description": {"type": "string"},
                    "reminder_minutes": {"type": "integer"},
                    "attendees": {"type": "string"},
                    "inform_via_email": {"type": "boolean"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_calendar_event",
            "description": "Delete an event from the Calendar by id or title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "integer"},
                    "title": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_contact",
            "description": "Delete a contact from the Contact Book by id, name, or email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_new_chat",
            "description": "Start a brand new Jarvis chat conversation.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_incoming_email",
            "description": "Trigger a simulated incoming push email into Inbox (same as clicking Simulate Push Email button).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "disconnect_gmail",
            "description": "Disconnect the Gmail account and switch to Demo Mode.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_ui_button",
            "description": "Click or trigger any UI button or panel control in Jarvis Mailer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "button": {
                        "type": "string",
                        "enum": [
                            "compose",
                            "inbox",
                            "starred",
                            "sent",
                            "drafts",
                            "scheduled",
                            "meetings",
                            "calendar",
                            "calendar_list_mode",
                            "calendar_month_mode",
                            "spam",
                            "bin",
                            "contacts",
                            "connect_gmail",
                            "sync_gmail",
                            "disconnect_gmail",
                            "simulate_push",
                            "toggle_theme",
                            "approve_detected_meeting",
                            "dismiss_detected_meeting",
                            "clear_filters",
                            "clear_bin",
                            "next_page",
                            "prev_page",
                            "back_to_list",
                            "star_email",
                            "reply",
                            "forward",
                            "toggle_read",
                            "mark_spam",
                            "move_to_bin",
                            "restore_from_bin",
                            "discard_compose",
                            "toggle_cc",
                            "toggle_bcc",
                            "save_draft",
                            "cancel_contact_edit",
                            "calendar_prev_month",
                            "calendar_next_month",
                            "open_add_event_form",
                            "cancel_add_event_form",
                            "open_edit_event_form",
                            "inform_event_users",
                            "open_event_email",
                            "delete_event",
                            "new_chat",
                        ],
                    }
                },
                "required": ["button"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_profile",
            "description": "Fetch and show the user's connected Gmail / account details such as display name, email, and mailbox statistics.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _build_context_summary(account: MailAccount, ui_context: Dict[str, Any]) -> str:
    from django.utils import timezone

    client_tz = get_client_tz(ui_context)
    local_now = timezone.now().astimezone(client_tz)
    current_view = ui_context.get("current_view", "inbox")
    open_email_id = ui_context.get("open_email_id") or (
        ui_context.get("chat_context") or {}
    ).get("open_email_id")
    selected_event_id = ui_context.get("selected_calendar_event_id")
    parts = [
        f"User local time: {local_now.isoformat()}",
        f"Current UI view: {current_view}",
    ]
    if open_email_id:
        email = EmailMessage.objects.filter(account=account, id=open_email_id).first()
        if email:
            parts.append(
                f"Currently open email (id={email.id}): From {email.sender_name} <{email.sender_email}>, "
                f"Subject: '{email.subject}', Snippet: '{email.snippet}'"
            )
    if selected_event_id:
        ev = CalendarEvent.objects.filter(account=account, id=selected_event_id).first()
        if ev:
            parts.append(
                f"Currently selected calendar event (id={ev.id}): Title '{ev.title}', Starts: {ev.start_at.isoformat()}"
            )
    if ui_context.get("active_filters"):
        parts.append(f"Active filters: {json.dumps(ui_context['active_filters'])}")
    compose_draft = ui_context.get("compose_draft") or {}
    if compose_draft:
        parts.append(
            "Current compose draft: "
            + json.dumps(
                {
                    "to": compose_draft.get("to", ""),
                    "cc": compose_draft.get("cc", ""),
                    "bcc": compose_draft.get("bcc", ""),
                    "subject": compose_draft.get("subject", ""),
                    "body": (compose_draft.get("body", "") or "")[:1200],
                }
            )
        )
    if ui_context.get("chat_context"):
        parts.append(f"Recent context in this chat: {json.dumps(ui_context['chat_context'], default=str)[:1800]}")
    contacts = list(Contact.objects.filter(account=account).values_list("name", "email")[:20])
    if contacts:
        parts.append("Known contacts: " + ", ".join(f"{n} <{e}>" for n, e in contacts))
    return "\n".join(parts)


def _history_turn_content(turn: Dict[str, Any]) -> str:
    content = turn.get("content", "")
    context = turn.get("context") or {}
    if turn.get("role") != "user" or not isinstance(context, dict):
        return content
    compact_context = {
        key: context[key]
        for key in ("current_view", "open_email_id", "active_filters", "compose_draft")
        if context.get(key)
    }
    if compact_context:
        return f"{content}\n[UI context for this message: {json.dumps(compact_context, default=str)[:1800]}]"
    return content


def _execute_tool(
    account: MailAccount, name: str, args: Dict[str, Any], ui_context: Dict[str, Any]
) -> Dict[str, Any]:
    open_id = (
        args.get("email_id")
        or ui_context.get("open_email_id")
        or (ui_context.get("chat_context") or {}).get("open_email_id")
    )
    if name == "compose_email":
        return execute_compose_tool(
            to=args.get("to", ""),
            subject=args.get("subject", ""),
            body=args.get("body", ""),
            account=account,
            cc=args.get("cc", ""),
            bcc=args.get("bcc", ""),
        )
    if name == "schedule_email":
        return execute_schedule_tool(
            account,
            to=args.get("to", ""),
            subject=args.get("subject", ""),
            body=args.get("body", ""),
            scheduled_at=args.get("scheduled_at", ""),
            client_tz=get_client_tz(ui_context),
            cc=args.get("cc", ""),
            bcc=args.get("bcc", ""),
        )
    if name == "search_emails":
        return execute_search_tool(
            account,
            folder=args.get("folder", "inbox"),
            q=args.get("q"),
            sender=args.get("sender"),
            is_read=args.get("is_read"),
            days=args.get("days"),
            date_from=args.get("date_from"),
            date_to=args.get("date_to"),
        )
    if name == "read_email_detail":
        detail = execute_read_email_detail(
            account,
            email_id=args.get("email_id") or ui_context.get("open_email_id"),
            sender=args.get("sender"),
            q=args.get("q"),
        )
        return {"observation": detail, "ui_actions": [], "rich_cards": []}
    if name == "open_email":
        res = execute_open_email_tool(
            account,
            email_id=args.get("email_id"),
            sender=args.get("sender"),
            q=args.get("q"),
            folder=args.get("folder"),
            days=args.get("days"),
            date_from=args.get("date_from"),
            date_to=args.get("date_to"),
        )
        if res.get("ui_actions") and res["ui_actions"][0].get("email"):
            ui_context["open_email_id"] = res["ui_actions"][0]["email"]["id"]
        return res
    if name == "close_email":
        ui_context["open_email_id"] = None
        return execute_close_email_tool()
    if name == "reply_to_open_email":
        return execute_reply_open_email(
            account,
            open_email_id=open_id,
            custom_body=args.get("custom_body"),
        )
    if name == "forward_open_email":
        return execute_forward_open_email(
            account,
            open_email_id=open_id,
            to=args.get("to", ""),
        )
    if name == "star_email":
        return execute_star_open_email(account, open_id, starred=args.get("starred", True))
    if name == "move_email":
        return execute_move_open_email(
            account,
            args.get("email_id") or open_id,
            args.get("folder", "bin"),
            subject=args.get("subject"),
            sender=args.get("sender"),
            email_address=args.get("email_address"),
            name=args.get("name"),
            q=args.get("q"),
            move_all=bool(args.get("move_all")),
        )
    if name == "save_contact":
        return execute_save_contact_tool(
            account, name=args.get("name", ""), email=args.get("email", "")
        )
    if name == "lookup_contact":
        email_addr, contact, candidates = resolve_recipient(account, args.get("name", ""))
        return {
            "observation": {
                "resolved_email": email_addr,
                "contact": contact.to_dict() if contact else None,
                "candidates": [c.to_dict() for c in candidates],
            },
            "ui_actions": [],
            "rich_cards": [],
        }
    if name == "save_draft":
        return execute_save_draft_tool(
            account,
            to=args.get("to", ""),
            subject=args.get("subject", ""),
            body=args.get("body", ""),
            cc=args.get("cc", ""),
            bcc=args.get("bcc", ""),
        )
    if name == "mark_read_status":
        return execute_mark_read_open_email(account, open_id, is_read=args.get("is_read", False))
    if name == "set_theme":
        theme = args.get("theme", "dark")
        return {"reply": f"Switched to {theme} mode.", "ui_actions": [{"type": "set_theme", "theme": theme}], "rich_cards": []}
    if name == "sync_mailbox":
        return execute_sync_now_tool(account)
    if name == "open_contacts":
        return {"reply": "Opened your Contact Book.", "ui_actions": [{"type": "navigate_view", "view": "contacts"}], "rich_cards": []}
    if name == "submit_compose":
        return {"reply": "Sending your email now.", "ui_actions": [{"type": "submit_compose"}], "rich_cards": []}
    if name == "discard_compose":
        return {"reply": "Discarded compose draft.", "ui_actions": [{"type": "discard_compose"}], "rich_cards": []}
    if name == "delete_email":
        has_scope = any(
            args.get(k)
            for k in ("email_id", "folder", "subject", "sender", "recipient", "email_address", "name", "q", "delete_all")
        )
        target_id = args.get("email_id") if has_scope else open_id
        return execute_delete_email_tool(
            account,
            email_id=target_id,
            folder=args.get("folder"),
            sender=args.get("sender"),
            recipient=args.get("recipient"),
            subject=args.get("subject"),
            email_address=args.get("email_address"),
            name=args.get("name"),
            q=args.get("q"),
            permanent=bool(args.get("permanent")),
            delete_all=bool(args.get("delete_all")),
        )
    if name == "restore_email":
        has_scope = any(
            args.get(k)
            for k in ("email_id", "subject", "sender", "email_address", "name", "q", "restore_all")
        )
        target_id = args.get("email_id") if has_scope else open_id
        return execute_restore_email_tool(
            account,
            email_id=target_id,
            subject=args.get("subject"),
            sender=args.get("sender"),
            email_address=args.get("email_address"),
            name=args.get("name"),
            q=args.get("q"),
            restore_all=bool(args.get("restore_all")),
        )
    if name == "clear_bin":
        return execute_clear_bin_tool(account)
    if name == "edit_contact":
        return execute_edit_contact_tool(
            account,
            contact_id=args.get("contact_id"),
            target_name=args.get("target_name", ""),
            target_email=args.get("target_email", ""),
            new_name=args.get("new_name", ""),
            new_email=args.get("new_email", ""),
            new_notes=args.get("new_notes"),
        )
    if name == "list_calendar_events":
        return execute_list_calendar_events_tool(
            account,
            upcoming_only=args.get("upcoming_only", True),
            client_tz=get_client_tz(ui_context),
        )
    if name == "create_calendar_event":
        return execute_create_calendar_event_tool(
            account,
            title=args.get("title", ""),
            start_at=args.get("start_at", ""),
            description=args.get("description", ""),
            reminder_minutes=args.get("reminder_minutes", 15),
            attendees=args.get("attendees", ""),
            inform_via_email=bool(args.get("inform_via_email")),
            client_tz=get_client_tz(ui_context),
        )
    if name == "edit_calendar_event":
        return execute_edit_calendar_event_tool(
            account,
            event_id=args.get("event_id") or ui_context.get("selected_calendar_event_id"),
            target_title=args.get("target_title", ""),
            new_title=args.get("new_title", ""),
            start_at=args.get("start_at", ""),
            description=args.get("description"),
            reminder_minutes=args.get("reminder_minutes"),
            attendees=args.get("attendees"),
            inform_via_email=bool(args.get("inform_via_email")),
            client_tz=get_client_tz(ui_context),
        )
    if name == "delete_calendar_event":
        return execute_delete_calendar_event_tool(
            account,
            event_id=args.get("event_id") or ui_context.get("selected_calendar_event_id"),
            title=args.get("title", ""),
        )
    if name == "delete_contact":
        return execute_delete_contact_tool(
            account,
            contact_id=args.get("contact_id"),
            name=args.get("name", ""),
            email=args.get("email", ""),
        )
    if name == "start_new_chat":
        return execute_new_chat_tool(account)
    if name == "simulate_incoming_email":
        return execute_simulate_incoming_tool(account)
    if name == "disconnect_gmail":
        return execute_disconnect_gmail_tool(account)
    if name == "trigger_ui_button":
        return execute_trigger_ui_button_tool(
            account,
            args.get("button", ""),
            open_email_id=open_id,
            selected_event_id=ui_context.get("selected_calendar_event_id"),
            current_view=ui_context.get("current_view", "inbox"),
        )
    if name == "get_user_profile":
        return execute_user_profile_tool(account)
    return {"reply": "Done.", "ui_actions": [], "rich_cards": []}


def _run_openai_agent(
    account: MailAccount,
    message: str,
    ui_context: Dict[str, Any],
    history: List[Dict[str, str]],
) -> Dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    system_prompt = (
        "You are Jarvis, an autonomous agentic AI co-pilot embedded in a mail web application. "
        "You can plan and execute multiple tool calls in sequence (e.g., search -> read_email_detail -> reply_to_open_email) "
        "to accomplish complex user goals. Always drive the UI using tools rather than only describing actions. "
        "CRITICAL RULE: Whenever you draft, compose, reply to, forward, revise, or prepare to schedule an email, "
        "NEVER send or schedule it immediately in the same turn. Stop after calling the drafting or scheduling tool "
        "so the user can review the draft and explicitly confirm.\n\n"
        + _build_context_summary(account, ui_context)
    )
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for turn in (history or [])[-24:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": _history_turn_content(turn)})
    messages.append({"role": "user", "content": message})

    ctx = dict(ui_context)
    all_actions: List[Dict[str, Any]] = []
    all_cards: List[Dict[str, Any]] = []
    agent_steps: List[str] = []
    last_tool_reply = ""
    drafted_in_turn = False

    for _ in range(6):
        resp = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            tools=OPENAI_TOOLS,
            tool_choice="auto",
            temperature=0.1,
        )
        choice = resp.choices[0].message
        if not choice.tool_calls:
            return {
                "reply": choice.content or last_tool_reply or "Done.",
                "ui_actions": all_actions,
                "rich_cards": all_cards,
                "agent_steps": agent_steps or ["Completed"],
            }

        messages.append(choice.model_dump(exclude_none=True))
        batch_has_draft = any(
            tc.function.name in DRAFTING_TOOLS
            or tc.function.name in ("create_calendar_event", "edit_calendar_event")
            for tc in choice.tool_calls
        )
        for tc in choice.tool_calls:
            if tc.function.name == "submit_compose" and (
                batch_has_draft
                or drafted_in_turn
                or not re.search(r"\b(?:send\s+it|send\s+now|confirm|yes)\b", message, re.IGNORECASE)
            ):
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps({"skipped": "Waiting for explicit user confirmation before sending."}),
                    }
                )
                continue
            args = json.loads(tc.function.arguments or "{}")
            result = _execute_tool(account, tc.function.name, args, ctx)
            if tc.function.name in DRAFTING_TOOLS or any(
                a.get("type") == "fill_compose" for a in result.get("ui_actions", [])
            ):
                drafted_in_turn = True
            agent_steps.append(tc.function.name.replace("_", " ").title())
            all_actions.extend(result.get("ui_actions", []))
            all_cards.extend(result.get("rich_cards", []))
            if result.get("reply"):
                last_tool_reply = result["reply"]

            obs = result.get("observation") or {
                "reply": result.get("reply", "ok"),
                "actions": [a["type"] for a in result.get("ui_actions", [])],
            }
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(obs, default=str)[:4000],
                }
            )
        if drafted_in_turn:
            return {
                "reply": last_tool_reply or "Please review the draft and confirm before sending or scheduling.",
                "ui_actions": all_actions,
                "rich_cards": all_cards,
                "agent_steps": agent_steps,
            }

    return {
        "reply": last_tool_reply or "Completed multi-step workflow.",
        "ui_actions": all_actions,
        "rich_cards": all_cards,
        "agent_steps": agent_steps,
    }


def _run_gemini_agent(
    account: MailAccount,
    message: str,
    ui_context: Dict[str, Any],
    history: List[Dict[str, str]],
) -> Dict[str, Any]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    declarations = [
        types.FunctionDeclaration(
            name=t["function"]["name"],
            description=t["function"]["description"],
            parameters_json_schema=t["function"]["parameters"],
        )
        for t in OPENAI_TOOLS
    ]
    system_prompt = (
        "You are Jarvis, an autonomous agentic AI co-pilot embedded in a mail web application. "
        "Convert any natural language user request into the appropriate tool calls in sequence to control the UI, "
        "manage contacts, compose/draft/schedule/reply/forward/star/move/summarize emails. "
        "When drafting or scheduling an email from user intent, write a natural subject and body. "
        "CRITICAL RULE: Whenever you draft, compose, reply to, forward, revise, or prepare to schedule an email, "
        "NEVER send or schedule it immediately in the same turn. Stop after calling the drafting or scheduling tool "
        "so the user can review the draft and explicitly confirm.\n\n"
        + _build_context_summary(account, ui_context)
    )

    contents: List[Any] = []
    for turn in (history or [])[-24:]:
        role = "model" if turn.get("role") == "assistant" else "user"
        if turn.get("content"):
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=_history_turn_content(turn))]))
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=message)]))

    ctx = dict(ui_context)
    all_actions: List[Dict[str, Any]] = []
    all_cards: List[Dict[str, Any]] = []
    agent_steps: List[str] = []
    last_tool_reply = ""
    drafted_in_turn = False

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[types.Tool(function_declarations=declarations)],
        temperature=0.1,
    )

    for _ in range(6):
        resp = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=contents,
            config=config,
        )
        fn_calls = resp.function_calls or []
        if not fn_calls:
            return {
                "reply": (resp.text or "").strip() or last_tool_reply or "Done.",
                "ui_actions": all_actions,
                "rich_cards": all_cards,
                "agent_steps": agent_steps or ["Completed"],
            }

        contents.append(resp.candidates[0].content)
        fn_response_parts = []
        batch_has_draft = any(
            fc.name in DRAFTING_TOOLS
            or fc.name in ("create_calendar_event", "edit_calendar_event")
            for fc in fn_calls
        )
        for fc in fn_calls:
            if fc.name == "submit_compose" and (
                batch_has_draft
                or drafted_in_turn
                or not re.search(r"\b(?:send\s+it|send\s+now|confirm|yes)\b", message, re.IGNORECASE)
            ):
                fn_response_parts.append(
                    types.Part.from_function_response(
                        name=fc.name,
                        response={"result": {"skipped": "Waiting for explicit user confirmation before sending."}},
                    )
                )
                continue
            args = dict(fc.args or {})
            result = _execute_tool(account, fc.name, args, ctx)
            if fc.name in DRAFTING_TOOLS or any(
                a.get("type") == "fill_compose" for a in result.get("ui_actions", [])
            ):
                drafted_in_turn = True
            agent_steps.append(fc.name.replace("_", " ").title())
            all_actions.extend(result.get("ui_actions", []))
            all_cards.extend(result.get("rich_cards", []))
            if result.get("reply"):
                last_tool_reply = result["reply"]

            obs = result.get("observation") or {
                "reply": result.get("reply", "ok"),
                "actions": [a["type"] for a in result.get("ui_actions", [])],
            }
            fn_response_parts.append(
                types.Part.from_function_response(name=fc.name, response={"result": obs})
            )
        contents.append(types.Content(role="user", parts=fn_response_parts))
        if drafted_in_turn:
            return {
                "reply": last_tool_reply or "Please review the draft and confirm before sending or scheduling.",
                "ui_actions": all_actions,
                "rich_cards": all_cards,
                "agent_steps": agent_steps,
            }

    return {
        "reply": last_tool_reply or "Completed multi-step workflow.",
        "ui_actions": all_actions,
        "rich_cards": all_cards,
        "agent_steps": agent_steps,
    }


def process_assistant_command(
    account: MailAccount,
    message: str,
    ui_context: Dict[str, Any],
    history: List[Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    # Navigation, filtering and other deterministic UI controls do not need a
    # provider call. Language work (drafting, rewriting, summarizing) does.
    if is_local_ui_intent(message, history or []):
        result = run_fallback_nlu(account, message, ui_context, history=history or [])
        result.setdefault("agent_steps", []).insert(0, "Handled locally (no AI API call)")
        return result
    # These target-specific Sent actions need recipient-aware lookup, which
    # the generic LLM tools do not currently expose.
    if re.search(
        r"\b(?:star|unstar|open|show)\b.*\b(?:latest|last|most recent)\b.*\bsent\b",
        message,
        re.IGNORECASE,
    ):
        return run_fallback_nlu(account, message, ui_context, history=history or [])
    if (
        ui_context.get("compose_draft")
        or (ui_context.get("chat_context") or {}).get("compose_draft")
    ) and re.search(
        r"\b(?:edit|rewrite|revise|rephrase|romanticize|romanticise|reword)\b|\bmake\s+(?:it|this)\b",
        message,
        re.IGNORECASE,
    ) and not re.search(r"\b(?:contact|event|meeting)\b", message, re.IGNORECASE):
        return run_fallback_nlu(account, message, ui_context, history=history or [])
    provider = settings.AI_PROVIDER
    api_key = settings.OPENAI_API_KEY if provider == "openai" else settings.GEMINI_API_KEY
    provider_name = "OpenAI" if provider == "openai" else "Gemini"
    if not api_key:
        return {
            "reply": f"{provider_name} is selected, but its API key is missing. Set the matching key in .env and restart Jarvis.",
            "ui_actions": [], "rich_cards": [],
            "agent_steps": [f"Selected provider: {provider_name}", "Missing API key"],
        }
    try:
        result = (
            _run_openai_agent(account, message, ui_context, history or [])
            if provider == "openai"
            else _run_gemini_agent(account, message, ui_context, history or [])
        )
        result["agent_steps"] = [f"Used {provider_name}"] + (result.get("agent_steps") or [])
        return result
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        detail = f" (HTTP {status})" if status else ""
        return {
            "reply": f"The selected {provider_name} request failed{detail}. Check its API key, model, and network connection. No other provider was tried.",
            "ui_actions": [], "rich_cards": [],
            "agent_steps": [f"Selected provider: {provider_name}", "Provider request failed"],
        }
