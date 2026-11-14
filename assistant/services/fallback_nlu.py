import re
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Dict, Optional, Tuple

from django.utils import timezone

from accounts.models import MailAccount
from assistant.services.tools import (
    execute_close_email_tool,
    execute_compose_tool,
    execute_forward_open_email,
    execute_mark_read_open_email,
    execute_move_open_email,
    execute_open_email_tool,
    execute_read_email_detail,
    execute_reply_open_email,
    execute_rewrite_compose_tool,
    execute_save_contact_tool,
    execute_save_draft_tool,
    execute_schedule_tool,
    execute_search_tool,
    execute_star_open_email,
    execute_sync_now_tool,
)
from mail.models import EmailMessage
from mail.services.contacts import resolve_recipient
from mail.services.queries import query_emails


def get_client_tz(ui_context: Dict[str, Any]):
    offset = ui_context.get("tz_offset_minutes")
    if isinstance(offset, (int, float)):
        return dt_timezone(timedelta(minutes=-int(offset)))
    return timezone.get_current_timezone()


def is_local_ui_intent(message: str, history: Optional[list] = None) -> bool:
    """Route deterministic mail UI controls locally instead of calling an LLM."""
    text = (message or "").strip()
    lower = text.lower()
    if _merge_pending_schedule_followup(text, history or []):
        return True
    if re.search(r"\b(?:summari[sz]e|rewrite|rephrase|romanticize|romanticise|make it more)\b", lower):
        return False
    if re.search(r"\b(?:schedule|scheduled)\b.*\b(?:mail|email|message|send)\b", lower):
        return True
    if re.fullmatch(r"(?:close(?:\s+(?:this|it|email|mail|the\s+open\s+(?:email|mail)|detail))?|go\s+back)", lower):
        return True
    if any(term in lower for term in ("dark mode", "dark theme", "light mode", "light theme", "sync mail", "refresh inbox")):
        return True
    if re.fullmatch(r"(?:open\s+|show\s+|go\s+to\s+)?contacts(?:\s+book)?", lower):
        return True
    if re.fullmatch(r"(?:send\s+it|send\s+now|confirm\s+send|yes\s+send|discard|cancel\s+compose|clear\s+compose)", lower):
        return True
    if re.search(r"\b(?:star|unstar|mark\s+(?:this\s+)?(?:as\s+)?(?:read|unread)|move\s+to|spam\s+this|not\s+spam|restore|trash\s+this|delete\s+this)\b", lower):
        return True
    if re.search(r"\b(?:open|show|go\s+to)\b", lower) and any(
        term in lower for term in ("inbox", "sent", "draft", "starred", "spam", "bin", "trash", "scheduled", "latest", "newest", "recent", "email", "mail", "message", "contacts")
    ):
        return True
    if re.search(r"\b(?:show|find|search|filter|clear|reset)\b", lower) and any(
        term in lower for term in ("email", "mail", "inbox", "sent", "unread", "read", "from", "subject")
    ):
        return True
    if re.search(r"\b(?:save|add)\s+contact\b|\bremember\b.*@", lower):
        return True
    return False

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

NON_SENDER_WORDS = {
    "the", "last", "this", "past", "today", "yesterday", "nov", "november",
    "dec", "december", "jan", "january", "feb", "february", "mar", "march",
    "apr", "april", "may", "jun", "june", "jul", "july", "aug", "august",
    "sep", "sept", "september", "oct", "october",
}


def _extract_quoted(text: str) -> str:
    return text.strip().strip("'\"").strip("\u2018\u2019\u201c\u201d")


def _parse_compose(message: str) -> Optional[Dict[str, str]]:
    to_addr = ""
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", message)
    if email_match:
        to_addr = email_match.group(0)
    else:
        name_match = re.search(
            r"\bto\s+([A-Za-z][A-Za-z0-9 .'-]{0,40}?)(?=\s*(?:,|$|\s+(?:at|by|on|today|tomorrow|in\s+\d+|with\s+subject|subject|about|regarding|with\s+body|body|saying|message|asking|telling|reminding|thanking|inviting|for|to\s+ask|to\s+tell)\b))",
            message,
            re.IGNORECASE,
        )
        if not name_match:
            name_match = re.search(
                r"^(?:mail|email)\s+(?!from\b|to\b)([A-Za-z][A-Za-z0-9 .'-]{0,40}?)(?=\s*(?:,|$|\s+(?:with\s+subject|subject|about|regarding|with\s+body|body|saying|message|asking|telling|reminding|thanking|inviting|for)\b))",
                message,
                re.IGNORECASE,
            )
        if name_match:
            candidate = name_match.group(1).strip()
            if candidate.lower() not in ("a", "an", "the", "mail", "email", "message"):
                to_addr = candidate

    if not to_addr:
        return None

    subject = ""
    subj_match = re.search(
        r"(?:with\s+)?(?:subject|about)\s*[:=]?\s*(?:'([^']*)'|\"([^\"]*)\"|\u2018([^\u2019]*)\u2019|\u201c([^\u201d]*)\u201d|([^\n]+?)(?=\s+(?:and\s+)?(?:body|saying|message)|$))",
        message,
        re.IGNORECASE,
    )
    if subj_match:
        subject = next((g for g in subj_match.groups() if g is not None), "").strip()

    body = ""
    body_match = re.search(
        r"(?:and\s+)?(?:body|message)\s*[:=]?\s*(?:'([^']*)'|\"([^\"]*)\"|\u2018([^\u2019]*)\u2019|\u201c([^\u201d]*)\u201d|(.+))$|\bsaying\s*[:=]?\s*('([^']*)'|\"([^\"]*)\"|\u2018([^\u2019]*)\u2019|\u201c([^\u201d]*)\u201d)$",
        message,
        re.IGNORECASE | re.DOTALL,
    )
    if body_match:
        body = next((g for g in body_match.groups() if g is not None), "").strip()

    intent = ""
    if not subject or not body:
        m_intent = re.search(
            r"(?:,\s*|(?:\b(?:asking|telling|saying|reminding|thanking|inviting|regarding|about)\b).*)$",
            message,
            re.IGNORECASE,
        )
        if m_intent:
            intent = m_intent.group(0).lstrip(", ").strip()

    return {
        "to": to_addr,
        "subject": _extract_quoted(subject),
        "body": _extract_quoted(body),
        "intent": intent,
    }


def _parse_schedule_datetime(text: str, client_tz=None) -> Optional[str]:
    tz = client_tz or timezone.get_current_timezone()
    now = timezone.now().astimezone(tz)
    lower = text.lower()

    m_in = re.search(r"\bin\s+(\d+)\s+(minute|minutes|min|hour|hours|hr|hrs)\b", lower)
    if m_in:
        val = int(m_in.group(1))
        unit = m_in.group(2)
        delta = timedelta(minutes=val) if unit.startswith("min") else timedelta(hours=val)
        return (now + delta).replace(second=0, microsecond=0).isoformat()

    base_date = now.date()
    if "tomorrow" in lower:
        base_date = base_date + timedelta(days=1)
    elif "today" in lower:
        base_date = now.date()
    else:
        d_from, _ = _parse_specific_date(lower)
        if d_from:
            base_date = datetime.strptime(d_from, "%Y-%m-%d").date()

    hour, minute = 9, 0
    m_time = re.search(r"\b(?:at|by)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", lower)
    if not m_time:
        m_time = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lower)
    if m_time:
        hour = int(m_time.group(1))
        minute = int(m_time.group(2) or 0)
        ampm = (m_time.group(3) or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
    elif "morning" in lower:
        hour, minute = 9, 0
    elif "afternoon" in lower:
        hour, minute = 14, 0
    elif "evening" in lower:
        hour, minute = 18, 0
    elif "tonight" in lower:
        hour, minute = 20, 0

    if not m_time and not any(k in lower for k in ("tomorrow", "today", "morning", "afternoon", "evening", "tonight")) and not _parse_specific_date(lower)[0]:
        return None

    try:
        dt = datetime(base_date.year, base_date.month, base_date.day, hour, minute, tzinfo=tz)
    except ValueError:
        return None
    if dt <= now:
        return None
    return dt.isoformat()


def _parse_days(lower: str) -> Optional[int]:
    m = re.search(r"last\s+(\d+)\s+days?", lower)
    if m:
        return int(m.group(1))
    if "this week" in lower or "last week" in lower or "past week" in lower:
        return 7
    if "this month" in lower or "last month" in lower:
        return 30
    return None


def _parse_specific_date(lower: str) -> Tuple[Optional[str], Optional[str]]:
    today = timezone.localdate()
    if re.search(r"\btoday\b", lower):
        s = today.isoformat()
        return s, s
    if re.search(r"\byesterday\b", lower):
        s = (today - timedelta(days=1)).isoformat()
        return s, s

    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", lower)
    if iso_match:
        s = iso_match.group(1)
        return s, s

    # e.g. "Nov 12" or "November 12, 2026"
    m_md = re.search(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:,?\s*(\d{4}))?\b",
        lower,
    )
    if m_md:
        month = MONTH_MAP[m_md.group(1)]
        day = int(m_md.group(2))
        year = int(m_md.group(3)) if m_md.group(3) else today.year
        try:
            s = datetime(year, month, day).date().isoformat()
            return s, s
        except ValueError:
            pass

    # e.g. "12 Nov" or "12 November 2026"
    m_dm = re.search(
        r"\b(\d{1,2})\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:,?\s*(\d{4}))?\b",
        lower,
    )
    if m_dm:
        day = int(m_dm.group(1))
        month = MONTH_MAP[m_dm.group(2)]
        year = int(m_dm.group(3)) if m_dm.group(3) else today.year
        try:
            s = datetime(year, month, day).date().isoformat()
            return s, s
        except ValueError:
            pass

    return None, None


def _sent_recipient_phrase(text: str) -> str:
    match = re.search(
        r"\b(?:sent|send|message|email)\s+to\s+(.+?)(?=\s+(?:about|regarding|with|on|today|yesterday|last|latest|and\s+then)\b|[,.!?;]|$)",
        text,
        re.IGNORECASE,
    )
    return match.group(1).strip(" \t\r\n'\"`") if match else ""


def _find_latest_sent_message(account: MailAccount, recipient: str = "") -> Optional[EmailMessage]:
    qs = EmailMessage.objects.filter(account=account, folder=EmailMessage.FOLDER_SENT)
    recipient = (recipient or "").strip()
    if recipient:
        email_addr = recipient if "@" in recipient else resolve_recipient(account, recipient)[0]
        if email_addr:
            qs = qs.filter(recipient_email__icontains=email_addr)
        else:
            qs = qs.filter(recipient_email__icontains=recipient)
    return qs.order_by("-received_at", "-id").first()


def _merge_pending_schedule_followup(message: str, history: list) -> Optional[str]:
    """Rebuild a schedule request when the user answers a clarification prompt."""
    if not history or re.search(r"\b(?:schedule|scheduled)\b", message, re.IGNORECASE):
        return None

    latest_assistant = next(
        (item.get("content", "") for item in reversed(history)
         if item.get("role") == "assistant" and item.get("content")),
        "",
    )
    if not re.search(r"schedule it for|when should i schedule|choose a future time|please tell me", latest_assistant, re.IGNORECASE):
        return None

    # Let a natural-language answer fill the requested body, while keeping
    # unrelated UI commands ("show unread mail", "open Sent") independent.
    content_prompt = bool(re.search(r"what the email should say|what.*(?:email|mail).*(?:say|contain)", latest_assistant, re.IGNORECASE))
    if re.match(r"\s*(?:show|open|go to|find|search|filter|star|unstar|mark|close|switch|sync|refresh)\b", message, re.IGNORECASE):
        return None
    if not content_prompt and not re.search(r"\bto\b|\b(?:at|by|today|tomorrow|tonight|morning|afternoon|evening)\b|@|\b(?:asking|saying|subject|body|about|remind|invite|thank)\b", message, re.IGNORECASE):
        return None

    schedule_index = None
    for index in range(len(history) - 1, -1, -1):
        item = history[index]
        if item.get("role") == "user" and re.search(r"\b(?:schedule|scheduled)\b", item.get("content", ""), re.IGNORECASE):
            schedule_index = index
            break
    if schedule_index is None:
        return None

    pieces = [history[schedule_index].get("content", "")]
    pieces.extend(
        item.get("content", "") for item in history[schedule_index + 1:]
        if item.get("role") == "user" and item.get("content")
    )
    if content_prompt and not re.search(r"\b(?:body|message|saying|say|write|tell)\b", message, re.IGNORECASE):
        pieces.append(f'with body "{message.strip()}"')
    else:
        pieces.append(message)
    return " ".join(piece.strip() for piece in pieces if piece.strip())


def _parse_sender(message: str) -> Optional[str]:
    m = re.search(
        r"\bfrom\s+([A-Za-z0-9_.+-]+(?:@[A-Za-z0-9.-]+)?)(?=\s+(?:about|regarding|with|from|on|in|this|last|today|yesterday|$))",
        message,
        re.IGNORECASE,
    )
    if m:
        candidate = m.group(1).strip()
        if candidate.lower() not in NON_SENDER_WORDS and not re.match(r"^\d{4}-\d{2}-\d{2}$", candidate):
            return candidate
    m_end = re.search(r"\bfrom\s+([A-Za-z0-9_.+-]+(?:@[A-Za-z0-9.-]+)?)\s*$", message, re.IGNORECASE)
    if m_end:
        candidate = m_end.group(1).strip()
        if candidate.lower() not in NON_SENDER_WORDS and not re.match(r"^\d{4}-\d{2}-\d{2}$", candidate):
            return candidate
    return None


def _parse_about_keyword(message: str) -> Optional[str]:
    m = re.search(
        r"\b(?:about|regarding|containing)\s+(?:the\s+)?(.+?)(?=\s+(?:from|on|in\s+the\s+last|$))",
        message,
        re.IGNORECASE,
    )
    if m:
        return _extract_quoted(m.group(1))
    return None


def _run_single_step(
    account: MailAccount, message: str, ui_context: Dict[str, Any]
) -> Dict[str, Any]:
    text = message.strip()
    lower = text.lower()
    open_email_id = ui_context.get("open_email_id") or (
        ui_context.get("chat_context") or {}
    ).get("open_email_id")

    if re.search(
        r"\b(?:edit|rewrite|revise|rephrase|romanticize|romanticise|reword)\b|\bmake\s+(?:it|this)\b",
        lower,
    ):
        draft = ui_context.get("compose_draft") or (
            ui_context.get("chat_context") or {}
        ).get("compose_draft") or {}
        if draft:
            return execute_rewrite_compose_tool(
                to=draft.get("to", ""),
                subject=draft.get("subject", ""),
                body=draft.get("body", ""),
                instruction=text,
            )

    # Close the open email
    if re.fullmatch(r"(?:close(?:\s+(?:this|it|email|mail|the\s+open\s+(?:email|mail)|detail))?|go\s+back)", lower):
        return execute_close_email_tool()

    # Theme & Sync controls
    if any(k in lower for k in ("dark mode", "dark theme")):
        return {"reply": "Switched to Dark Mode.", "ui_actions": [{"type": "set_theme", "theme": "dark"}], "rich_cards": []}
    if any(k in lower for k in ("light mode", "light theme")):
        return {"reply": "Switched to Light Mode.", "ui_actions": [{"type": "set_theme", "theme": "light"}], "rich_cards": []}
    if re.search(r"\b(sync|refresh)\b", lower) and any(k in lower for k in ("mail", "email", "inbox", "sync", "refresh")):
        return execute_sync_now_tool(account)

    # Compose confirm / discard
    if re.fullmatch(r"(?:send\s+it|send\s+now|confirm\s+send|yes\s+send)", lower):
        return {"reply": "Sending your drafted email now.", "ui_actions": [{"type": "submit_compose"}], "rich_cards": []}
    if re.fullmatch(r"(?:discard|cancel\s+compose|clear\s+compose)", lower):
        return {"reply": "Discarded the compose draft.", "ui_actions": [{"type": "discard_compose"}], "rich_cards": []}
    if re.fullmatch(r"(?:open\s+|show\s+|go\s+to\s+)?contacts(?:\s+book)?", lower):
        return {"reply": "Opened your Contact Book.", "ui_actions": [{"type": "navigate_view", "view": "contacts"}], "rich_cards": []}

    # Handle scheduling before generic search/filter intents. A schedule request
    # can be incomplete (for example, "schedule a mail at 8pm today"); don't
    # silently reinterpret it as an inbox search when the recipient is missing.
    if re.search(r"\b(?:schedule|scheduled)\b", lower) and any(
        k in lower for k in ("mail", "email", "message", "send")
    ):
        client_tz = get_client_tz(ui_context)
        parsed = _parse_compose(text) or {"to": "", "subject": "", "body": "", "intent": ""}
        compose_draft = ui_context.get("compose_draft") or (ui_context.get("chat_context") or {}).get("compose_draft") or {}
        draft_to = (compose_draft.get("to") or "").strip()
        to_val = (parsed.get("to") or "").strip() or draft_to
        if parsed.get("to") and "@" not in parsed["to"] and draft_to:
            draft_local = draft_to.split("@", 1)[0].casefold()
            requested_name = parsed["to"].strip().casefold().replace(" ", "")
            if requested_name and requested_name in draft_local.replace(".", "").replace("_", ""):
                to_val = draft_to
        subject_val = (parsed.get("subject") or "").strip() or (compose_draft.get("subject") or "").strip()
        body_val = (parsed.get("body") or "").strip() or (compose_draft.get("body") or "").strip()
        sched_iso = _parse_schedule_datetime(text, client_tz=client_tz)
        if not sched_iso:
            if re.search(r"\b(?:at|by)\s+\d|\b(?:today|tomorrow|tonight|morning|afternoon|evening)\b", lower):
                return {
                    "reply": "That send time is earlier than now or I couldn't parse it. Please choose a future time, such as ‘tomorrow at 8pm’.",
                    "ui_actions": [],
                    "rich_cards": [],
                    "agent_steps": ["Recognized a scheduling request", "Requested a valid future send time"],
                }
            return {
                "reply": "When should I schedule the email? Please give me a time, such as ‘8pm today’ or ‘tomorrow at 9am’.",
                "ui_actions": [],
                "rich_cards": [],
                "agent_steps": ["Recognized a scheduling request", "Asked for a send time"],
            }
        missing = []
        if not to_val:
            missing.append("who to send it to")
        if not body_val and not parsed.get("intent"):
            missing.append("what the email should say")
        if missing:
            local_dt = datetime.fromisoformat(sched_iso)
            when = local_dt.strftime("%I:%M %p today" if local_dt.date() == timezone.now().astimezone(client_tz).date() else "%Y-%m-%d %I:%M %p").lstrip("0")
            return {
                "reply": f"I can schedule it for {when}. Please tell me { ' and '.join(missing) }.",
                "ui_actions": [],
                "rich_cards": [],
                "agent_steps": ["Recognized a scheduling request", "Asked for missing email details"],
            }
        if to_val and sched_iso:
            return execute_schedule_tool(
                account,
                to=to_val,
                subject=subject_val,
                body=body_val,
                scheduled_at=sched_iso,
                intent=parsed.get("intent") or None,
                client_tz=client_tz,
            )

    # Summarize email(s)
    if re.search(r"\bsummari[sz]e\b", lower):
        sender = _parse_sender(text)
        if open_email_id and not sender and "inbox" not in lower and "unread" not in lower:
            detail = execute_read_email_detail(account, email_id=open_email_id)
            if detail.get("found"):
                em = detail["email"]
                lines = [ln.strip() for ln in (em.get("body_text") or "").splitlines() if ln.strip()]
                summary_body = " ".join(lines[:3])[:260]
                return {
                    "reply": f"**Summary of \"{em['subject']}\"** (from {em['sender_name']}):\n{summary_body}",
                    "ui_actions": [],
                    "rich_cards": [{"type": "email_preview", "email": em}],
                    "agent_steps": [f"Read email '{em['subject']}'", "Generated concise summary"],
                }
        qs = query_emails(
            account,
            folder="inbox",
            sender=sender,
            is_read=(False if "unread" in lower else None),
            days=_parse_days(lower),
        )
        items = list(qs[:5])
        if not items:
            return {
                "reply": "No matching emails found to summarize.",
                "ui_actions": [],
                "rich_cards": [],
                "agent_steps": ["Searched inbox (0 matches)"],
            }
        bullets = "\n".join(
            f"- **{m.sender_name}** — *{m.subject}*: {m.snippet[:90]}" for m in items
        )
        return {
            "reply": f"Here is a summary of **{len(items)}** email(s):\n{bullets}",
            "ui_actions": [
                {
                    "type": "apply_filters",
                    "folder": "inbox",
                    "sender": sender or "",
                    "is_read": False if "unread" in lower else None,
                    "days": _parse_days(lower),
                    "emails": [m.to_dict(include_body=False) for m in items],
                }
            ],
            "rich_cards": [{"type": "email_preview", "email": m.to_dict(include_body=False)} for m in items[:3]],
            "agent_steps": [f"Queried {len(items)} email(s)", "Synthesized inbox summary"],
        }

    # 0. Save / remember contact
    if any(k in lower for k in ("save contact", "add contact", "remember ")) and "@" in text:
        email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
        if email_match:
            email_addr = email_match.group(0)
            name_part = re.sub(
                r"(?:save|add)\s+contact|remember|'?s?\s+email\s+(?:id\s+)?(?:is|as)|" + re.escape(email_addr),
                "",
                text,
                flags=re.IGNORECASE,
            ).strip(" .:-")
            return execute_save_contact_tool(account, name=name_part, email=email_addr)

    # Resolve actions that refer to the latest message in Sent, even when that
    # message is not already open in the detail pane.
    if re.search(r"\b(?:star|unstar)\b", lower) and "sent" in lower and any(
        word in lower for word in ("latest", "last", "most recent")
    ):
        recipient = _sent_recipient_phrase(text)
        target = _find_latest_sent_message(account, recipient)
        if not target:
            return {"reply": "I couldn't find a matching message in Sent.", "ui_actions": [], "rich_cards": []}
        opened = execute_open_email_tool(account, email_id=target.id)
        starred = execute_star_open_email(account, target.id, starred=not bool(re.search(r"\bunstar\b", lower)))
        return {
            "reply": f"{starred.get('reply', 'Updated the message.')} Opened **{target.subject}** from Sent.",
            "ui_actions": opened.get("ui_actions", []) + starred.get("ui_actions", []),
            "rich_cards": opened.get("rich_cards", []),
            "agent_steps": ["Found the latest matching sent message", "Opened it", "Updated its star"],
        }

    # 1. Reply to currently open email
    if re.search(r"\breply\b", lower):
        custom_body = None
        m_say = re.search(r"(?:saying|with|body)\s+['\"\u2018\u201c]?(.+?)['\"\u2019\u201d]?$", text, re.IGNORECASE | re.DOTALL)
        if m_say:
            custom_body = m_say.group(1).strip()
        return execute_reply_open_email(account, open_email_id, custom_body=custom_body)

    # 1b. Star / Read / Spam / Bin actions on open email
    if re.search(r"\b(unstar|remove star)\b", lower):
        return execute_star_open_email(account, open_email_id, starred=False)
    if re.search(r"\bstar\b", lower) and not any(w in lower for w in ("starred", "show", "open")):
        return execute_star_open_email(account, open_email_id, starred=True)
    if re.search(r"\bmark\s+(?:this\s+)?(?:as\s+)?unread\b", lower):
        return execute_mark_read_open_email(account, open_email_id, is_read=False)
    if re.search(r"\bmark\s+(?:this\s+)?(?:as\s+)?read\b", lower):
        return execute_mark_read_open_email(account, open_email_id, is_read=True)
    if re.search(r"\b(not spam|restore|move to inbox)\b", lower):
        return execute_move_open_email(account, open_email_id, "inbox")
    if re.search(r"\b(move to spam|mark as spam|spam this)\b", lower):
        return execute_move_open_email(account, open_email_id, "spam")
    if re.search(r"\b(move to bin|move to trash|delete this|trash this)\b", lower):
        return execute_move_open_email(account, open_email_id, "bin")

    # 2. Forward currently open email (supports email OR contact name)
    if re.search(r"\bforward\b", lower):
        email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
        if email_match:
            to_addr = email_match.group(0)
        else:
            m_to = re.search(r"\bto\s+([A-Za-z][A-Za-z0-9 .'-]+)$", text, re.IGNORECASE)
            to_addr = m_to.group(1).strip() if m_to else ""
        return execute_forward_open_email(account, open_email_id, to=to_addr)

    # 3. Compose / Send / Save Draft email (supports email OR contact name)
    if "save draft" in lower or "save as draft" in lower:
        parsed = _parse_compose(text) or {"to": "", "subject": "", "body": "", "intent": text}
        return execute_save_draft_tool(
            account,
            to=parsed["to"],
            subject=parsed["subject"],
            body=parsed["body"],
            intent=parsed.get("intent") or None,
        )

    if any(k in lower for k in ("send ", "compose ", "write ", "draft ", "email to ", "mail to ")) or re.match(r"^(?:mail|email)\s+(?!from\b)", lower):
        parsed = _parse_compose(text)
        if parsed:
            return execute_compose_tool(
                to=parsed["to"],
                subject=parsed["subject"],
                body=parsed["body"],
                mode="new",
                account=account,
                intent=parsed.get("intent") or None,
            )
        if "compose" in lower:
            return {
                "reply": "I've opened the compose view for you.",
                "ui_actions": [{"type": "navigate_view", "view": "compose"}],
                "rich_cards": [],
            }

    # 4. Clear filters
    if any(k in lower for k in ("clear filter", "reset filter", "show all email", "all emails")):
        return execute_search_tool(account, folder="inbox")

    # Open the message already selected in the UI when the user says "open it".
    if re.fullmatch(r"(?:open|show)\s+(?:it|this|that|this email|this message)", lower) and open_email_id:
        return execute_open_email_tool(account, email_id=open_email_id)

    # 5. Open a specific email, including the latest message in Sent.
    if re.search(r"\bopen\b", lower) and not any(v in lower for v in ("inbox", "compose", "contacts")):
        sender = _parse_sender(text)
        q = _parse_about_keyword(text)
        date_from, date_to = _parse_specific_date(lower)
        days = _parse_days(lower)
        is_latest = any(w in lower for w in ("latest", "newest", "recent", "last mail", "last email"))
        if "sent" in lower and is_latest:
            target = _find_latest_sent_message(account, _sent_recipient_phrase(text))
            if not target:
                return {"reply": "I couldn't find a matching message in Sent.", "ui_actions": [], "rich_cards": []}
            return execute_open_email_tool(account, email_id=target.id)
        if sender or q or date_from or days or is_latest:
            return execute_open_email_tool(
                account,
                sender=sender,
                q=q,
                folder="sent" if "sent" in lower else None,
                days=days,
                date_from=date_from,
                date_to=date_to,
            )

    # 6. Navigate to folders directly
    folder_nav_map = {
        "sent": "sent",
        "inbox": "inbox",
        "draft": "drafts",
        "drafts": "drafts",
        "starred": "starred",
        "spam": "spam",
        "bin": "bin",
        "trash": "bin",
        "scheduled": "scheduled",
    }
    m_nav = re.fullmatch(
        r"(?:go\s+to\s+|open\s+|show\s+)?(?:my\s+)?(inbox|sent|drafts?|starred|spam|bin|trash|scheduled)(?:\s+(?:emails?|mails?|folder))?",
        lower,
    )
    if m_nav:
        return execute_search_tool(account, folder=folder_nav_map[m_nav.group(1)])

    # 7. Search & Filter emails
    folder = "sent" if "sent" in lower else "inbox"
    is_read: Optional[bool] = None
    if "unread" in lower:
        is_read = False
    elif re.search(r"\bread\s+emails?\b", lower):
        is_read = True

    days = _parse_days(lower)
    date_from, date_to = _parse_specific_date(lower)
    sender = _parse_sender(text)
    q = _parse_about_keyword(text)

    if any([is_read is not None, days is not None, date_from, sender, q, "show" in lower, "find" in lower, "search" in lower, "filter" in lower]):
        return execute_search_tool(
            account,
            folder=folder,
            q=q,
            sender=sender,
            is_read=is_read,
            days=days,
            date_from=date_from,
            date_to=date_to,
        )

    return {
        "reply": (
            "I can control the mail UI for you! Try saying:\n"
            "- *\"Send an email to Sarah with subject 'Meeting Tomorrow' and body 'Let's meet at 3pm'\"*\n"
            "- *\"Save contact John john@example.com\"*\n"
            "- *\"Open the latest mail\"* or *\"Open the email from David from yesterday\"*\n"
            "- *\"Show only unread emails from this week\"*\n"
            "- *\"Reply to this\"* (while reading an email)"
        ),
        "ui_actions": [],
        "rich_cards": [],
    }


def run_fallback_nlu(
    account: MailAccount, message: str, ui_context: Dict[str, Any], history: Optional[list] = None
) -> Dict[str, Any]:
    """Agentic multi-step NLU planner: splits compound instructions and chains context."""
    pending_schedule = _merge_pending_schedule_followup(message, history or [])
    if pending_schedule:
        result = _run_single_step(account, pending_schedule, ui_context)
        result.setdefault("agent_steps", ["Continued the pending scheduling request"])
        return result

    parts = [
        p.strip()
        for p in re.split(r"\s*(?:,\s*and\s+then\s+|\s+and\s+then\s+|;\s*|\s+then\s+|\s*,\s*and\s+(?=(?:open|reply|forward|star|move|summarize|summarise|send|draft|save)\b))", message, flags=re.IGNORECASE)
        if p.strip()
    ]
    if len(parts) <= 1:
        res = _run_single_step(account, message, ui_context)
        if "agent_steps" not in res:
            res["agent_steps"] = [
                a["type"].replace("_", " ").title() for a in res.get("ui_actions", [])
            ] or ["Analyzed request"]
        return res

    ctx = dict(ui_context)
    all_actions = []
    all_cards = []
    replies = []
    steps = []

    for part in parts:
        step_res = _run_single_step(account, part, ctx)
        if step_res.get("reply"):
            replies.append(step_res["reply"])
        for action in step_res.get("ui_actions", []):
            all_actions.append(action)
            if action.get("type") == "open_email" and action.get("email"):
                ctx["open_email_id"] = action["email"]["id"]
                ctx["current_view"] = "detail"
            elif action.get("type") == "apply_filters" and action.get("emails"):
                ctx["open_email_id"] = action["emails"][0]["id"]
        all_cards.extend(step_res.get("rich_cards", []))
        steps.extend(
            step_res.get("agent_steps")
            or [a["type"].replace("_", " ").title() for a in step_res.get("ui_actions", [])]
            or [f"Executed: {part[:32]}"]
        )

    return {
        "reply": "\n\n".join(replies),
        "ui_actions": all_actions,
        "rich_cards": all_cards,
        "agent_steps": steps,
    }
