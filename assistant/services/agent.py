import json
import re
from typing import Any, Dict, List

from django.conf import settings

from accounts.models import MailAccount
from assistant.services.fallback_nlu import get_client_tz, is_local_ui_intent, run_fallback_nlu
from assistant.services.tools import (
    execute_close_email_tool,
    execute_compose_tool,
    execute_forward_open_email,
    execute_mark_read_open_email,
    execute_move_open_email,
    execute_open_email_tool,
    execute_read_email_detail,
    execute_reply_open_email,
    execute_save_contact_tool,
    execute_save_draft_tool,
    execute_schedule_tool,
    execute_search_tool,
    execute_star_open_email,
    execute_sync_now_tool,
)
from mail.models import Contact, EmailMessage
from mail.services.contacts import resolve_recipient

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "compose_email",
            "description": "Open the compose UI and visibly fill in recipient (email or contact name), subject, and body.",
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
            "name": "schedule_email",
            "description": "Schedule an email to be sent at a future ISO datetime (e.g. 2026-11-15T09:00:00).",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
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
            "description": "Pre-fill a reply to the currently open email in the detail view.",
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
            "description": "Forward the currently open email to a recipient name or email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_id": {"type": "integer"},
                    "to": {"type": "string"},
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
            "description": "Move an email to inbox, spam, or bin.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_id": {"type": "integer"},
                    "folder": {"type": "string", "enum": ["inbox", "spam", "bin"]},
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
            "description": "Save an email as a draft in the Drafts folder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
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
            "description": "Send the email currently filled in the compose form.",
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
]


def _build_context_summary(account: MailAccount, ui_context: Dict[str, Any]) -> str:
    from django.utils import timezone

    client_tz = get_client_tz(ui_context)
    local_now = timezone.now().astimezone(client_tz)
    current_view = ui_context.get("current_view", "inbox")
    open_email_id = ui_context.get("open_email_id") or (
        ui_context.get("chat_context") or {}
    ).get("open_email_id")
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
    if ui_context.get("active_filters"):
        parts.append(f"Active filters: {json.dumps(ui_context['active_filters'])}")
    compose_draft = ui_context.get("compose_draft") or {}
    if compose_draft:
        parts.append(
            "Current compose draft: "
            + json.dumps(
                {
                    "to": compose_draft.get("to", ""),
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
        )
    if name == "schedule_email":
        return execute_schedule_tool(
            account,
            to=args.get("to", ""),
            subject=args.get("subject", ""),
            body=args.get("body", ""),
            scheduled_at=args.get("scheduled_at", ""),
            client_tz=get_client_tz(ui_context),
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
        return execute_move_open_email(account, open_id, args.get("folder", "bin"))
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
        "to accomplish complex user goals. Always drive the UI using tools rather than only describing actions.\n\n"
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
        for tc in choice.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            result = _execute_tool(account, tc.function.name, args, ctx)
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
        "When drafting or scheduling an email from user intent, write a natural subject and body.\n\n"
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
        for fc in fn_calls:
            args = dict(fc.args or {})
            result = _execute_tool(account, fc.name, args, ctx)
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
    ):
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
