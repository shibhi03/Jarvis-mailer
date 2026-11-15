import re
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Dict, Optional, Tuple

from django.utils import timezone

from accounts.models import MailAccount
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
    execute_rewrite_compose_tool,
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
from mail.models import EmailMessage
from mail.services.contacts import resolve_recipient
from mail.services.queries import query_emails


def get_client_tz(ui_context: Dict[str, Any]):
    offset = ui_context.get("tz_offset_minutes")
    if isinstance(offset, (int, float)):
        return dt_timezone(timedelta(minutes=-int(offset)))
    return timezone.get_current_timezone()


def _match_ui_button_intent(lower: str) -> Optional[str]:
    patterns = [
        (r"^\s*(?:new|start|open|create)\s+(?:a\s+)?(?:new\s+)?chat\b|\b(?:open|start|create)\s+(?:a\s+)?new\s+(?:chat|conversation)\b", "new_chat"),
        (r"\b(?:toggle)\s+(?:the\s+)?(?:dark|light)?\s*(?:mode|theme)\b", "toggle_theme"),
        (r"\bsimulate\b.*\b(?:push|incoming|email|mail)\b", "simulate_push"),
        (r"\bdisconnect\b.*\bgmail\b|\bswitch\s+to\s+demo\b", "disconnect_gmail"),
        (r"\bconnect\b.*\bgmail\b", "connect_gmail"),
        (r"\b(?:calendar\s+month|month\s+view|switch\s+to\s+month)\b", "calendar_month_mode"),
        (r"\b(?:calendar\s+list|event\s+list|list\s+view|switch\s+to\s+events?(?:\s+list)?)\b", "calendar_list_mode"),
        (r"\bnext\s+month\b", "calendar_next_month"),
        (r"\b(?:prev|previous)\s+month\b", "calendar_prev_month"),
        (r"\bnext\s+page\b", "next_page"),
        (r"\b(?:prev|previous)\s+page\b", "prev_page"),
        (r"\b(?:open|show)\s+(?:the\s+)?(?:add|new)\s+event\s+form\b", "open_add_event_form"),
        (r"\b(?:cancel|close)\s+(?:the\s+)?(?:add|new)?\s*event\s+form\b", "cancel_add_event_form"),
        (r"\bopen\s+(?:the\s+)?edit\s+event\s+form\b", "open_edit_event_form"),
        (r"\b(?:inform|notify)\s+(?:users|people|attendees)\s+(?:about\s+(?:this\s+|the\s+)?)?(?:event|update)\b", "inform_event_users"),
        (r"\bopen\s+(?:the\s+)?(?:event|related)\s+(?:email|mail)\b", "open_event_email"),
        (r"\b(?:approve|accept|review\s+and\s+add)\s+(?:the\s+)?(?:detected\s+|pending\s+)?meeting\b", "approve_detected_meeting"),
        (r"\bdismiss\s+(?:the\s+)?(?:detected\s+|pending\s+)?meeting(?:\s+banner)?\b", "dismiss_detected_meeting"),
        (r"\b(?:show|open|toggle|add)\s+(?:the\s+)?cc(?:\s+field|\s+row)?\b", "toggle_cc"),
        (r"\b(?:show|open|toggle|add)\s+(?:the\s+)?bcc(?:\s+field|\s+row)?\b", "toggle_bcc"),
        (r"^\s*save\s+(?:this\s+|the\s+)?draft\s*$", "save_draft"),
        (r"^\s*(?:click|press)?\s*reply(?:\s+to\s+(?:this|it)(?:\s+(?:email|mail|message))?)?(?:\s+button)?\s*$", "reply"),
        (r"^\s*(?:click|press)?\s*forward(?:\s+(?:this|it)(?:\s+(?:email|mail|message))?)?(?:\s+button)?\s*$", "forward"),
        (r"^\s*(?:click|press)?\s*restore(?:\s+(?:this|it|the\s+(?:email|mail|message)))?(?:\s+from\s+(?:the\s+)?(?:bin|trash))?\s*$", "restore_from_bin"),
        (r"^\s*(?:click|press)?\s*discard(?:\s+(?:the\s+|this\s+)?(?:compose|draft|email|message))?\s*$", "discard_compose"),
        (r"^\s*(?:click|press|open|show)?\s*(?:the\s+)?compose(?:\s+button)?\s*$", "compose"),
        (r"^\s*(?:go\s+)?back(?:\s+to\s+(?:the\s+)?(?:list|inbox|folder|emails?))?\s*$", "back_to_list"),
        (r"\bcancel\s+contact\s+edit(?:ing)?\b", "cancel_contact_edit"),
    ]
    for pattern, key in patterns:
        if re.search(pattern, lower):
            return key
    return None


def is_local_ui_intent(message: str, history: Optional[list] = None) -> bool:
    """Route deterministic mail UI controls locally instead of calling an LLM."""
    text = (message or "").strip()
    lower = text.lower()
    if _merge_pending_schedule_followup(text, history or []):
        return True
    if _match_ui_button_intent(lower):
        return True
    if re.search(r"\b(?:summari[sz]e|rewrite|rephrase|romanticize|romanticise|make it more)\b", lower):
        return False
    if re.search(r"\b(?:clear|empty)\s+(?:the\s+)?(?:bin|trash)\b|\bdelete\s+(?:all|every)\s+(?:emails?|mails?|messages?)?\s*(?:in|from)\s+(?:the\s+)?(?:bin|trash)\b", lower):
        return True
    if re.search(r"\b(?:delete|remove|cancel)\b.*\b(?:calendar\s+)?(?:event|meeting|appointment)\b", lower) and "meeting email" not in lower:
        return True
    if re.search(r"\brestore\b", lower) and not re.search(r"\b(?:contact|event|meeting|calendar)\b", lower):
        return True
    if (
        re.search(
            r"\b(?:move|put|send|throw)\b.*\b(?:to|in|into)\s+(?:the\s+)?(?:bin|trash)\b|\b(?:trash|bin)\s+(?:the\s+|all\s+)?(?:mails?|emails?|messages?)\b",
            lower,
        )
        and not re.search(r"\b(?:contact|event|meeting|calendar)\b", lower)
    ):
        return True
    if re.search(r"\b(?:delete|remove|cancel)\b", lower) and (
        any(term in lower for term in ("mail", "mails", "email", "emails", "message", "messages", "draft", "drafts", "scheduled", "bin", "trash"))
        or bool(re.fullmatch(r"(?:delete|remove)\s+(?:this|it|that)", lower))
    ):
        return True
    if re.search(r"\b(?:delete|remove|edit|update|change|rename|modify)\b.*\bcontact\b", lower):
        return True
    if re.search(r"\b(?:edit|update|change|reschedule|modify|rename)\b.*\b(?:event|meeting|appointment)\b", lower) and "meeting email" not in lower:
        return True
    if re.search(r"\b(?:fetch|show|get|display|check|what\s+is|tell\s+me)\b.*\b(?:my\s+(?:details|profile|account|info|name|gmail)|gmail\s+(?:details|profile|info)|user\s+(?:details|profile|info)|account\s+(?:details|profile|info))\b|\bwho\s+am\s+i\b", lower):
        return True
    if re.search(r"\b(?:add|create|schedule|book|plan|set\s+up)\b.*\b(?:event|meeting|appointment)\b", lower) and "meeting email" not in lower and "meeting emails" not in lower:
        return True
    if (
        re.search(r"\b(?:list|show|view|open|check|what|any|upcoming|all)\b", lower)
        and re.search(r"\b(?:events?|calendar|meetings?|schedule)\b", lower)
        and not re.search(r"\b(?:mail|mails|email|emails|message|draft|send)\b", lower)
    ) or re.fullmatch(r"(?:calendar|events|upcoming\s+events|upcoming\s+meetings|meetings)", lower):
        return True
    if re.search(r"\b(?:open|show|go\s+to)\b.*\bmeeting\s+emails?\b", lower):
        return True
    if re.search(r"\b(?:schedule|scheduled)\b.*\b(?:mail|email|message|send|it|this|draft)\b", lower):
        return True
    if re.fullmatch(r"(?:close(?:\s+(?:this|it|email|mail|the\s+open\s+(?:email|mail)|detail))?|go\s+back)", lower):
        return True
    if any(term in lower for term in ("dark mode", "dark theme", "light mode", "light theme", "sync mail", "sync gmail", "refresh inbox", "clear filter", "reset filter")) or re.fullmatch(r"(?:sync|refresh)(?:\s+(?:gmail|mailbox|inbox|mails?|emails?))?", lower):
        return True
    if re.fullmatch(r"(?:open\s+|new\s+)?compose(?:\s+(?:email|mail|message))?", lower):
        return True
    if re.fullmatch(r"(?:open\s+|show\s+|go\s+to\s+)?contacts(?:\s+book)?", lower):
        return True
    if re.fullmatch(
        r"(?:send\s+it|send\s+now|confirm\s+send|yes\s+send|yes\s+send\s+it|confirm\s+and\s+(?:send|schedule)|"
        r"confirm\s+schedule|yes\s+schedule|schedule\s+it|schedule\s+now|yes|confirm|"
        r"discard|cancel\s+compose|clear\s+compose)",
        lower,
    ):
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
    "inbox", "sent", "draft", "drafts", "scheduled", "spam", "bin", "trash", "starred",
}


def _extract_quoted(text: str) -> str:
    return text.strip().strip("'\"").strip("\u2018\u2019\u201c\u201d")


def _strip_spans(text: str, spans: list) -> str:
    if not spans:
        return text
    ordered = sorted((s for s in spans if s), key=lambda x: x[0])
    out = []
    pos = 0
    for start, end in ordered:
        if start > pos:
            out.append(text[pos:start])
        out.append(" ")
        pos = max(pos, end)
    if pos < len(text):
        out.append(text[pos:])
    return "".join(out)


def _parse_compose(message: str) -> Optional[Dict[str, str]]:
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

    spans = []
    if subj_match:
        spans.append(subj_match.span())
    if body_match:
        spans.append(body_match.span())
    recipient_text = _strip_spans(message, spans)

    stop_lookahead = (
        r"(?=(?:\s*,?\s*\b(?:"
        r"(?:and\s+)?(?:with\s+)?cc\b|(?:and\s+)?(?:with\s+)?bcc\b|"
        r"(?:with\s+)?subject\b|about\b|regarding\b|"
        r"(?:with\s+)?body\b|saying\b|message\b|"
        r"asking\b|telling\b|reminding\b|thanking\b|inviting\b|"
        r"today\b|tomorrow\b|tonight\b|for\b|to\s+(?:ask|tell)\b"
        r")|\s+\b(?:at|by|on)\s+\d|\s+\bin\s+\d+|$))"
    )

    cc_addr = ""
    bcc_addr = ""
    cc_match = re.search(
        r"(?:^|[\s,])(?:and\s+)?(?:with\s+)?cc(?:\s+to)?\s*[:=]?\s*(.+?)" + stop_lookahead,
        recipient_text,
        re.IGNORECASE,
    )
    if cc_match:
        cc_addr = cc_match.group(1).strip(" ,.;")

    bcc_match = re.search(
        r"(?:^|[\s,])(?:and\s+)?(?:with\s+)?bcc(?:\s+to)?\s*[:=]?\s*(.+?)" + stop_lookahead,
        recipient_text,
        re.IGNORECASE,
    )
    if bcc_match:
        bcc_addr = bcc_match.group(1).strip(" ,.;")

    cc_bcc_spans = []
    if cc_match:
        cc_bcc_spans.append(cc_match.span())
    if bcc_match:
        cc_bcc_spans.append(bcc_match.span())
    to_text = _strip_spans(recipient_text, cc_bcc_spans)

    to_addr = ""
    to_match = re.search(
        r"\bto\s+(.+?)" + stop_lookahead,
        to_text,
        re.IGNORECASE,
    )
    if not to_match:
        to_match = re.search(
            r"^(?:mail|email)\s+(?!from\b|to\b)(.+?)" + stop_lookahead,
            to_text,
            re.IGNORECASE,
        )
    if to_match:
        candidate = to_match.group(1).strip(" ,.;")
        if candidate.lower() not in ("a", "an", "the", "mail", "email", "message"):
            to_addr = candidate
    else:
        emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", to_text)
        if emails:
            to_addr = ", ".join(dict.fromkeys(emails))

    if not (to_addr or cc_addr or bcc_addr):
        return None

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
        "cc": cc_addr,
        "bcc": bcc_addr,
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
    if re.match(r"\s*(?:show|open|go to|find|search|filter|star|unstar|mark|close|switch|sync|refresh|delete|clear|empty|restore|move|trash|edit|update|add|create|list|fetch|who)\b", message, re.IGNORECASE):
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


def _parse_edit_contact(text: str) -> Dict[str, Any]:
    emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    after = re.sub(
        r"^.*?\bcontact\b(?:\s+(?:for|named|called))?\s*",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    ).strip()

    new_notes: Optional[str] = None
    m_notes = re.search(
        r"\bnotes?\s*(?:to|as|=|:)?\s*['\"]?([^'\"\n;]+)['\"]?$",
        after,
        re.IGNORECASE,
    )
    if m_notes:
        new_notes = m_notes.group(1).strip(" '\"")
        after_no_notes = after[: m_notes.start()].strip()
    else:
        after_no_notes = after

    target_name = ""
    target_email = ""
    new_name = ""
    new_email = ""

    m_new_name = re.search(
        r"\bname\s+(?:to|as|=|:)\s*['\"]?([^'\"\n@]+?)['\"]?(?=\s+(?:and\b|email\b|notes?\b|$))",
        after_no_notes,
        re.IGNORECASE,
    )
    if m_new_name:
        new_name = m_new_name.group(1).strip(" '\"")

    if not emails and not m_new_name:
        m_ren = re.match(
            r"(.+?)\s+(?:to|as)\s+['\"]?([^'\"@\n]+?)['\"]?$",
            after_no_notes,
            re.IGNORECASE,
        )
        if m_ren:
            target_name = m_ren.group(1).strip(" '\".,:-")
            new_name = m_ren.group(2).strip(" '\"")

    if len(emails) >= 2:
        target_email = emails[0]
        new_email = emails[1]
    elif len(emails) == 1:
        em = emails[0]
        if after_no_notes.lower().startswith(em.lower()):
            target_email = em
            if not new_name:
                m_after_em = re.search(
                    r"(?:to|as)\s+['\"]?([^'\"@\n]+?)['\"]?(?=\s+(?:notes?\b|$))",
                    after_no_notes[len(em) :],
                    re.IGNORECASE,
                )
                if m_after_em:
                    new_name = m_after_em.group(1).strip(" '\"")
        else:
            new_email = em

    if not target_email and not target_name:
        split_pat = r"(?:['\u2019]?s\s+)?\b(?:name|email|mail|notes?|to|as|with)\b"
        if emails:
            split_pat += "|" + re.escape(emails[0])
        cut = re.split(split_pat, after_no_notes, maxsplit=1, flags=re.IGNORECASE)[0]
        target_name = cut.strip(" '\".,:-")

    return {
        "target_name": target_name,
        "target_email": target_email,
        "new_name": new_name,
        "new_email": new_email,
        "new_notes": new_notes,
    }


def _parse_create_event(text: str, client_tz) -> Dict[str, Any]:
    lower = text.lower()
    sched_iso = _parse_schedule_datetime(text, client_tz=client_tz)
    inform_via_email = bool(
        re.search(r"\b(?:inform|notify|draft|email|mail|invite|send)\b", lower)
    )

    emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    attendee_tokens = list(emails)
    generic_group_words = {
        "users", "the users", "everyone", "all", "team", "them",
        "attendees", "participants", "people", "contacts", "guests",
        "by drafting an email", "by email",
    }
    m_att = re.search(
        r"\b(?:inform|notify|invite|email|mail)\s+(?:to\s+)?([A-Za-z][A-Za-z0-9 .,'-]{1,60}?)(?=\s+(?:by\b|via\b|about\b|regarding\b|for\b|at\b|on\b|tomorrow\b|today\b|$)|[.!?]|$)",
        text,
        re.IGNORECASE,
    )
    if m_att:
        raw_att = m_att.group(1).strip(" ,.")
        if raw_att and raw_att.lower() not in generic_group_words and "@" not in raw_att:
            attendee_tokens.append(raw_att)

    m_qt = re.search(
        r"\b(?:event|meeting|appointment)\b\s*(?:called|named|titled)?\s*['\"\u2018\u201c]([^'\"\u2019\u201d]+)['\"\u2019\u201d]",
        text,
        re.IGNORECASE,
    )
    if m_qt:
        title = m_qt.group(1).strip()
    else:
        m_after = re.search(
            r"\b(?:new\s+)?(?:event|meeting|appointment)\b\s*(?:called|named|titled|for)?\s+(.+)$",
            text,
            re.IGNORECASE,
        )
        candidate = m_after.group(1) if m_after else text
        candidate = re.split(
            r"\s+\b(?:at|on|by|tomorrow|today|tonight|in\s+\d+|and\s+(?:inform|notify|draft|email|mail|invite|send)|with\s+[\w.+-]+@)\b",
            candidate,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        title = candidate.strip(" '\".,:-")
        if title.lower() in ("a", "an", "the", "new", "to", "for", "and", ""):
            title = "New Event"

    return {
        "title": title,
        "start_at": sched_iso or "",
        "attendees": ", ".join(dict.fromkeys(attendee_tokens)),
        "inform_via_email": inform_via_email,
    }


def _parse_edit_event(text: str, client_tz) -> Dict[str, Any]:
    lower = text.lower()
    sched_iso = _parse_schedule_datetime(text, client_tz=client_tz) or ""
    inform_via_email = bool(
        re.search(
            r"\b(?:inform|notify|draft|email|mail|invite|send|tell\s+(?:them|people|users|attendees|everyone|the\s+other))\b",
            lower,
        )
    )
    quoted = re.findall(r"['\"\u2018\u201c]([^'\"\u2019\u201d]+)['\"\u2019\u201d]", text)
    target_title = ""
    new_title = ""
    if len(quoted) >= 2:
        target_title = quoted[0].strip()
        new_title = quoted[1].strip()
    elif len(quoted) == 1:
        if re.search(r"\btitle\s+(?:to|as)\s+['\"\u2018\u201c]", lower):
            new_title = quoted[0].strip()
        else:
            target_title = quoted[0].strip()

    if not target_title:
        m_after = re.search(
            r"\b(?:event|meeting|appointment)\b\s*(?:called|named|titled)?\s+(.+)$",
            text,
            re.IGNORECASE,
        )
        if m_after:
            cand = re.split(
                r"\s+\b(?:title|to|at|on|by|tomorrow|today|tonight|description|reminder|and\s+(?:inform|notify|draft|email|mail|invite|send|tell))\b",
                m_after.group(1),
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(" '\".,:-")
            if cand.lower() not in ("", "this", "the", "that", "it", "selected", "my", "current"):
                target_title = cand

    if not new_title:
        m_nt = re.search(
            r"\btitle\s+(?:to|as|=)\s+(.+?)(?=\s+\b(?:at|on|by|tomorrow|today|and|description)\b|$)",
            text,
            re.IGNORECASE,
        )
        if m_nt:
            new_title = _extract_quoted(m_nt.group(1))

    emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    attendee_tokens = list(emails)
    generic_group_words = {
        "users", "the users", "everyone", "all", "team", "them",
        "attendees", "participants", "people", "other people", "the other people",
        "contacts", "guests", "about the update", "about it", "about update",
    }
    m_att = re.search(
        r"\b(?:inform|notify|invite|email|mail|tell)\s+(?:to\s+)?([A-Za-z][A-Za-z0-9 .,'-]{1,60}?)(?=\s+(?:about\b|regarding\b|by\b|via\b|for\b|at\b|on\b|tomorrow\b|today\b|$)|[.!?]|$)",
        text,
        re.IGNORECASE,
    )
    if m_att:
        raw_att = m_att.group(1).strip(" ,.")
        if raw_att and raw_att.lower() not in generic_group_words and "@" not in raw_att:
            attendee_tokens.append(raw_att)

    return {
        "target_title": target_title,
        "new_title": new_title,
        "start_at": sched_iso,
        "attendees": ", ".join(dict.fromkeys(attendee_tokens)) if attendee_tokens else None,
        "inform_via_email": inform_via_email,
    }


def _parse_mail_target_filters(text: str) -> Dict[str, Any]:
    """Extract numeric email_id, subject, email_address, sender/contact name, recipient, or search term."""
    lower = text.lower()
    all_matching = bool(re.search(r"\b(?:all|every|mails|emails|messages)\b", lower))

    email_id: Optional[int] = None
    m_num_id = re.search(
        r"\b(?:(?:email|mail|message)\s*(?:id|#)|id)\s*[:=#]?\s*(\d+)\b|#(\d+)\b",
        text,
        re.IGNORECASE,
    )
    if m_num_id:
        raw_num = next((g for g in m_num_id.groups() if g), "")
        if raw_num.isdigit():
            email_id = int(raw_num)

    recipient = ""
    m_rec = re.search(
        r"\bto\s+(?!the\s+(?:bin|trash|inbox)\b|bin\b|trash\b|inbox\b)([A-Za-z0-9_.+-]+(?:@[A-Za-z0-9.-]+)?)",
        text,
        re.IGNORECASE,
    )
    if m_rec:
        cand_rec = m_rec.group(1).strip(" .,")
        if cand_rec.lower() not in ("a", "an", "the", "bin", "trash", "inbox"):
            recipient = cand_rec

    email_address = ""
    emails_found = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    if emails_found:
        if recipient and "@" in recipient:
            others = [addr for addr in emails_found if addr.lower() != recipient.lower()]
            email_address = others[0] if others else recipient
        else:
            email_address = emails_found[0]

    subject = ""
    m_subj = re.search(
        r"\b(?:with\s+)?(?:subject|titled|named|called)\s*(?:is|as|:|=)?\s*"
        r"(?:'([^']+)'|\"([^\"]+)\"|\u2018([^\u2019]+)\u2019|\u201c([^\u201d]+)\u201d|"
        r"(.+?)(?=\s+(?:to\s+(?:the\s+)?(?:bin|trash|inbox)\b|from\s+(?:the\s+)?(?:bin|trash|inbox)\b|from\b|by\b|with\b|$)|$))",
        text,
        re.IGNORECASE,
    )
    if m_subj:
        subject = next((g for g in m_subj.groups() if g is not None), "").strip(" '\".,:-")

    name = ""
    m_poss = re.search(
        r"\b(?:move|put|send|throw|delete|remove|trash|bin|restore)\s+(?:the\s+|all\s+)?([A-Za-z][A-Za-z0-9 ._-]{0,40}?)(?:'s|\u2019s)\s+(?:mails?|emails?|messages?)\b",
        text,
        re.IGNORECASE,
    )
    if m_poss:
        name = m_poss.group(1).strip(" '\".,:-")

    if not name:
        m_person = re.search(
            r"\b(?:from|by|sent\s+by)\s+"
            r"(?!the\s+(?:bin|trash|inbox|drafts|scheduled|spam)\b|bin\b|trash\b|inbox\b|drafts?\b|scheduled\b|spam\b|subject\b|(?:email|mail)\s+id\b)"
            r"(?:'([^']+)'|\"([^\"]+)\"|\u2018([^\u2019]+)\u2019|\u201c([^\u201d]+)\u201d|"
            r"([A-Za-z][A-Za-z0-9 ._-]{0,48}?))"
            r"(?=\s+(?:to\s+(?:the\s+)?(?:bin|trash|inbox)\b|from\s+(?:the\s+)?(?:bin|trash|inbox)\b|with\s+(?:subject|email)\b|subject\b|titled\b|about\b|regarding\b|$)|[,.!?]|$)",
            text,
            re.IGNORECASE,
        )
        if m_person:
            cand_name = next((g for g in m_person.groups() if g is not None), "").strip(" '\".,:-")
            if cand_name and "@" not in cand_name and cand_name.lower() not in NON_SENDER_WORDS:
                name = cand_name

    if not name:
        m_named = re.search(
            r"\b(?:(?:sender|contact|person|user)\s+(?:name\s+)?|with\s+name\s+)(?:is|as|:|=)?\s*"
            r"(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z][A-Za-z0-9 ._-]{0,48}?))"
            r"(?=\s+(?:to\s+(?:the\s+)?(?:bin|trash|inbox)\b|from\s+(?:the\s+)?(?:bin|trash|inbox)\b|$)|[,.!?]|$)",
            text,
            re.IGNORECASE,
        )
        if m_named:
            cand_named = next((g for g in m_named.groups() if g is not None), "").strip(" '\".,:-")
            if cand_named and "@" not in cand_named:
                name = cand_named

    if not subject:
        m_quote = re.search(r"(?:'([^']+)'|\"([^\"]+)\"|\u2018([^\u2019]+)\u2019|\u201c([^\u201d]+)\u201d)", text)
        if m_quote:
            quoted = next((g for g in m_quote.groups() if g is not None), "").strip()
            if quoted and quoted.lower() not in (email_address.lower(), name.lower()):
                subject = quoted

    q_val = _parse_about_keyword(text) or ""
    if not q_val:
        m_about = re.search(
            r"\b(?:about|regarding|concerning|on\s+topic)\s+(.+?)"
            r"(?=\s+(?:to\s+(?:the\s+)?(?:bin|trash|inbox)\b|from\s+(?:the\s+)?(?:bin|trash|inbox)\b|back\s+to\s+inbox\b|$)|$)",
            text,
            re.IGNORECASE,
        )
        if m_about:
            cand_about = re.sub(r"['\"\u2018\u2019\u201c\u201d]", "", m_about.group(1)).strip(" .,:-")
            if cand_about:
                q_val = cand_about
    if q_val:
        q_val = re.sub(
            r"\s+(?:to|from|in|into)\s+(?:the\s+)?(?:bin|trash|inbox)$",
            "",
            q_val,
            flags=re.IGNORECASE,
        ).strip(" '\".,:-")

    if not any([email_id, email_address, subject, name, recipient, q_val]):
        stripped = re.sub(
            r"\b(?:please|kindly|move|put|send|throw|delete|remove|trash|bin|restore|permanently|forever|purge|"
            r"to\s+(?:the\s+)?(?:bin|trash|inbox)|from\s+(?:the\s+)?(?:bin|trash|inbox)|back\s+to\s+inbox|"
            r"about|regarding|concerning|with|subject|titled|named|called|from|to|in|into|of|by|"
            r"all|every|the|this|that|my|a|an|emails?|mails?|messages?|drafts?|scheduled|spam|inbox)\b",
            " ",
            text,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", stripped).strip(" '\".,:-")
        if cleaned and cleaned.lower() not in ("it", "this", "that", "one", "ones", "them"):
            q_val = cleaned

    return {
        "email_id": email_id,
        "subject": subject or None,
        "email_address": email_address or None,
        "name": name or None,
        "recipient": recipient or None,
        "q": q_val or None,
        "all_matching": all_matching,
    }


def _run_single_step(
    account: MailAccount, message: str, ui_context: Dict[str, Any]
) -> Dict[str, Any]:
    text = message.strip()
    lower = text.lower()
    open_email_id = ui_context.get("open_email_id") or (
        ui_context.get("chat_context") or {}
    ).get("open_email_id")
    selected_event_id = ui_context.get("selected_calendar_event_id")

    ui_btn = _match_ui_button_intent(lower)
    if ui_btn:
        return execute_trigger_ui_button_tool(
            account,
            ui_btn,
            open_email_id=open_email_id,
            selected_event_id=selected_event_id,
            current_view=ui_context.get("current_view", "inbox"),
        )

    if re.search(
        r"\b(?:edit|rewrite|revise|rephrase|romanticize|romanticise|reword)\b|\bmake\s+(?:it|this)\b",
        lower,
    ) and not re.search(r"\b(?:contact|event|meeting|bin|trash|scheduled|drafts?)\b", lower):
        draft = ui_context.get("compose_draft") or (
            ui_context.get("chat_context") or {}
        ).get("compose_draft") or {}
        if draft:
            return execute_rewrite_compose_tool(
                to=draft.get("to", ""),
                cc=draft.get("cc", ""),
                bcc=draft.get("bcc", ""),
                subject=draft.get("subject", ""),
                body=draft.get("body", ""),
                instruction=text,
                scheduled_at=draft.get("scheduled_at", ""),
            )

    # Clear Bin permanently
    if re.search(
        r"\b(?:clear|empty)\s+(?:the\s+)?(?:bin|trash)\b|\bdelete\s+(?:all|every)\s+(?:emails?|mails?|messages?)?\s*(?:in|from)\s+(?:the\s+)?(?:bin|trash)\b",
        lower,
    ):
        return execute_clear_bin_tool(account)

    # Delete calendar event
    if (
        re.search(r"\b(?:delete|remove|cancel)\b.*\b(?:calendar\s+)?(?:event|meeting|appointment)\b", lower)
        and "meeting email" not in lower
        and "meeting emails" not in lower
    ):
        m_qt = re.search(r"['\"\u2018\u201c]([^'\"\u2019\u201d]+)['\"\u2019\u201d]", text)
        ev_title = m_qt.group(1).strip() if m_qt else ""
        if not ev_title:
            m_after = re.search(
                r"\b(?:calendar\s+)?(?:event|meeting|appointment)\b\s*(?:called|named|titled)?\s*(.*)$",
                text,
                re.IGNORECASE,
            )
            cand = (m_after.group(1) if m_after else "").strip(" '\".,:-")
            if cand.lower() not in ("", "this", "the", "that", "it", "selected", "current", "from calendar"):
                ev_title = re.sub(r"\s+from\s+(?:my\s+)?calendar$", "", cand, flags=re.IGNORECASE).strip(" '\".,:-")
        return execute_delete_calendar_event_tool(
            account,
            event_id=None if ev_title else selected_event_id,
            title=ev_title,
        )

    # Edit / update / reschedule calendar event (with optional update email draft)
    if (
        re.search(r"\b(?:edit|update|change|reschedule|modify|rename)\b.*\b(?:event|meeting|appointment)\b", lower)
        and "meeting email" not in lower
        and "meeting emails" not in lower
    ):
        client_tz = get_client_tz(ui_context)
        ev_edit = _parse_edit_event(text, client_tz=client_tz)
        return execute_edit_calendar_event_tool(
            account,
            event_id=None if ev_edit["target_title"] else selected_event_id,
            target_title=ev_edit["target_title"],
            new_title=ev_edit["new_title"],
            start_at=ev_edit["start_at"],
            attendees=ev_edit["attendees"],
            inform_via_email=ev_edit["inform_via_email"],
            client_tz=client_tz,
        )

    # Restore email(s) from Bin back to Inbox
    if re.search(r"\brestore\b", lower) and not re.search(
        r"\b(?:contact|event|meeting|calendar)\b", lower
    ):
        targets = _parse_mail_target_filters(text)
        has_specific = any(
            [
                targets["email_id"],
                targets["subject"],
                targets["email_address"],
                targets["name"],
                targets["q"],
            ]
        )
        return execute_restore_email_tool(
            account,
            email_id=targets["email_id"] or (open_email_id if not has_specific and not targets["all_matching"] else None),
            subject=targets["subject"],
            email_address=targets["email_address"],
            name=targets["name"],
            q=targets["q"],
            restore_all=targets["all_matching"],
        )

    # Move email(s) to Bin OR delete email / scheduled mail / draft
    is_move_to_bin = bool(
        re.search(
            r"\b(?:move|put|send|throw)\b.*\b(?:to|in|into)\s+(?:the\s+)?(?:bin|trash)\b|\b(?:trash|bin)\s+(?:the\s+|all\s+)?(?:mails?|emails?|messages?)\b",
            lower,
        )
    )
    if is_move_to_bin or (
        re.search(r"\b(?:delete|remove|cancel)\b", lower)
        and (
            any(w in lower for w in ("mail", "mails", "email", "emails", "message", "messages", "draft", "drafts", "scheduled", "bin", "trash"))
            or bool(re.fullmatch(r"(?:delete|remove)\s+(?:this|it|that)", lower))
        )
    ):
        folder = None
        if not is_move_to_bin:
            if "scheduled" in lower:
                folder = "scheduled"
            elif "draft" in lower:
                folder = "drafts"
            elif "sent" in lower:
                folder = "sent"
            elif "bin" in lower or "trash" in lower:
                folder = "bin"
            elif "spam" in lower:
                folder = "spam"
            elif "inbox" in lower:
                folder = "inbox"

        targets = _parse_mail_target_filters(text)
        delete_all = bool(re.search(r"\b(?:all|every)\b", lower) or targets["all_matching"])
        permanent = bool(
            not is_move_to_bin
            and (
                re.search(r"\b(?:permanently|forever|purge)\b", lower)
                or folder in ("scheduled", "drafts", "bin")
            )
        )
        has_specific = any(
            [
                targets["email_id"],
                folder,
                targets["subject"],
                targets["email_address"],
                targets["name"],
                targets["recipient"],
                targets["q"],
                delete_all,
            ]
        )
        if not has_specific:
            if not open_email_id:
                action_word = "move to Bin" if is_move_to_bin else "delete"
                return {
                    "reply": f"Open an email first or tell me the subject, email address, ID, or sender name to {action_word}.",
                    "ui_actions": [],
                    "rich_cards": [],
                }
            use_open_id = open_email_id
        else:
            use_open_id = targets["email_id"]

        return execute_delete_email_tool(
            account,
            email_id=use_open_id,
            folder=folder,
            recipient=targets["recipient"],
            subject=targets["subject"],
            email_address=targets["email_address"],
            name=targets["name"],
            q=targets["q"],
            permanent=permanent,
            delete_all=delete_all,
            move_to_bin_only=is_move_to_bin,
        )

    # Delete contact
    if re.search(r"\b(?:delete|remove)\b.*\bcontact\b", lower):
        em_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
        c_email = em_match.group(0) if em_match else ""
        c_name = ""
        if not c_email:
            after = re.sub(
                r"^.*?\bcontact\b(?:\s+(?:for|named|called))?\s*",
                "",
                text,
                count=1,
                flags=re.IGNORECASE,
            ).strip(" '\".,:-")
            after = re.sub(r"\s+from\s+(?:my\s+)?contacts?(?:\s+book)?$", "", after, flags=re.IGNORECASE).strip(" '\".,:-")
            c_name = after
        return execute_delete_contact_tool(account, name=c_name, email=c_email)

    # Edit contact
    if re.search(r"\b(?:edit|update|change|rename|modify)\b.*\bcontact\b", lower):
        parsed_contact = _parse_edit_contact(text)
        return execute_edit_contact_tool(account, **parsed_contact)

    # Fetch user / connected Gmail details
    if re.search(
        r"\b(?:fetch|show|get|display|check|what\s+is|tell\s+me|sync|refresh)\b.*\b(?:my\s+(?:details|profile|account|info|name|gmail)|gmail\s+(?:details|profile|info)|user\s+(?:details|profile|info)|account\s+(?:details|profile|info))\b|\bwho\s+am\s+i\b",
        lower,
    ):
        return execute_user_profile_tool(account)

    # Create / add calendar event (and optionally draft email to inform attendees)
    if (
        re.search(r"\b(?:add|create|schedule|book|plan|set\s+up)\b.*\b(?:event|meeting|appointment)\b", lower)
        and "meeting email" not in lower
        and "meeting emails" not in lower
    ):
        client_tz = get_client_tz(ui_context)
        ev_args = _parse_create_event(text, client_tz=client_tz)
        return execute_create_calendar_event_tool(
            account,
            title=ev_args["title"],
            start_at=ev_args["start_at"],
            attendees=ev_args["attendees"],
            inform_via_email=ev_args["inform_via_email"],
            client_tz=client_tz,
        )

    # Open Meeting Emails vs list Calendar events / meetings
    if re.search(r"\b(?:open|show|go\s+to)\b.*\bmeeting\s+emails?\b", lower):
        return {
            "reply": "Opened Meeting Emails so you can review detected meeting invites.",
            "ui_actions": [{"type": "navigate_view", "view": "meetings"}],
            "rich_cards": [],
        }

    if (
        re.search(r"\b(?:list|show|view|open|check|what|any|upcoming|all)\b", lower)
        and re.search(r"\b(?:events?|calendar|meetings?|schedule)\b", lower)
        and not re.search(r"\b(?:mail|mails|email|emails|message|draft|send)\b", lower)
    ) or re.fullmatch(r"(?:calendar|events|upcoming\s+events|upcoming\s+meetings|meetings)", lower):
        upcoming_only = ("upcoming" in lower) or ("past" not in lower and "all events" not in lower)
        return execute_list_calendar_events_tool(
            account,
            upcoming_only=upcoming_only,
            client_tz=get_client_tz(ui_context),
        )

    # Close the open email
    if re.fullmatch(r"(?:close(?:\s+(?:this|it|email|mail|the\s+open\s+(?:email|mail)|detail))?|go\s+back)", lower):
        return execute_close_email_tool()

    # Theme & Sync controls
    if any(k in lower for k in ("dark mode", "dark theme")):
        return {"reply": "Switched to Dark Mode.", "ui_actions": [{"type": "set_theme", "theme": "dark"}], "rich_cards": []}
    if any(k in lower for k in ("light mode", "light theme")):
        return {"reply": "Switched to Light Mode.", "ui_actions": [{"type": "set_theme", "theme": "light"}], "rich_cards": []}
    if re.search(
        r"^\s*(?:please\s+)?(?:sync|refresh)\b|\b(?:sync|refresh)\s+(?:my\s+|the\s+)?(?:mail|mails|email|emails|mailbox|inbox|gmail)\b",
        lower,
    ) and not re.search(r"\b(?:schedule|draft|compose|send)\b", lower):
        return execute_sync_now_tool(account)

    # Compose confirm / discard
    compose_draft = ui_context.get("compose_draft") or (
        ui_context.get("chat_context") or {}
    ).get("compose_draft") or {}
    if re.fullmatch(
        r"(?:confirm\s+schedule|yes\s+schedule|schedule\s+it|schedule\s+now|confirm\s+and\s+schedule)",
        lower,
    ) or (re.fullmatch(r"(?:yes|confirm)", lower) and compose_draft.get("scheduled_at")):
        return {
            "reply": "Confirmed — scheduling your drafted email now.",
            "ui_actions": [{"type": "confirm_schedule"}],
            "rich_cards": [],
        }
    if re.fullmatch(
        r"(?:send\s+it|send\s+now|confirm\s+send|yes\s+send|yes\s+send\s+it|confirm\s+and\s+send|yes|confirm)",
        lower,
    ):
        return {
            "reply": "Confirmed — sending your drafted email now.",
            "ui_actions": [{"type": "submit_compose"}],
            "rich_cards": [],
        }
    if re.fullmatch(r"(?:discard|cancel\s+compose|clear\s+compose)", lower):
        return {"reply": "Discarded the compose draft.", "ui_actions": [{"type": "discard_compose"}], "rich_cards": []}
    if re.fullmatch(r"(?:open\s+|show\s+|go\s+to\s+)?contacts(?:\s+book)?", lower):
        return {"reply": "Opened your Contact Book.", "ui_actions": [{"type": "navigate_view", "view": "contacts"}], "rich_cards": []}

    # Handle scheduling before generic search/filter intents. A schedule request
    # can be incomplete (for example, "schedule a mail at 8pm today"); don't
    # silently reinterpret it as an inbox search when the recipient is missing.
    if re.search(r"\b(?:schedule|scheduled)\b", lower) and any(
        k in lower for k in ("mail", "email", "message", "send", "it", "this", "draft")
    ):
        client_tz = get_client_tz(ui_context)
        parsed = _parse_compose(text) or {"to": "", "cc": "", "bcc": "", "subject": "", "body": "", "intent": ""}
        draft_to = (compose_draft.get("to") or "").strip()
        to_val = (parsed.get("to") or "").strip() or draft_to
        if parsed.get("to") and "@" not in parsed["to"] and draft_to and "," not in parsed["to"] and " and " not in parsed["to"].lower():
            draft_local = draft_to.split("@", 1)[0].casefold()
            requested_name = parsed["to"].strip().casefold().replace(" ", "")
            if requested_name and requested_name in draft_local.replace(".", "").replace("_", ""):
                to_val = draft_to
        cc_val = (parsed.get("cc") or "").strip() or (compose_draft.get("cc") or "").strip()
        bcc_val = (parsed.get("bcc") or "").strip() or (compose_draft.get("bcc") or "").strip()
        subject_val = (parsed.get("subject") or "").strip() or (
            "" if parsed.get("intent") else (compose_draft.get("subject") or "").strip()
        )
        body_val = (parsed.get("body") or "").strip() or (
            "" if parsed.get("intent") else (compose_draft.get("body") or "").strip()
        )
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
                cc=cc_val,
                bcc=bcc_val,
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

    # 2. Forward currently open email (supports single/multiple email OR contact name)
    if re.search(r"\bforward\b", lower):
        emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
        m_to = re.search(r"\bto\s+(.+)$", text, re.IGNORECASE)
        if m_to:
            to_addr = m_to.group(1).strip(" ,.;")
        elif emails:
            to_addr = ", ".join(dict.fromkeys(emails))
        else:
            to_addr = ""
        return execute_forward_open_email(account, open_email_id, to=to_addr)

    # 3. Compose / Send / Save Draft email (supports multiple To, CC, BCC)
    if "save draft" in lower or "save as draft" in lower:
        parsed = _parse_compose(text) or {"to": "", "cc": "", "bcc": "", "subject": "", "body": "", "intent": text}
        return execute_save_draft_tool(
            account,
            to=parsed["to"],
            subject=parsed["subject"],
            body=parsed["body"],
            intent=parsed.get("intent") or None,
            cc=parsed.get("cc", ""),
            bcc=parsed.get("bcc", ""),
        )

    if any(k in lower for k in ("send ", "compose ", "write ", "draft ", "email to ", "mail to ")) or re.match(r"^(?:mail|email)\s+(?!from\b)", lower) or re.fullmatch(r"(?:open\s+|new\s+)?compose(?:\s+(?:email|mail|message))?", lower):
        parsed = _parse_compose(text)
        if parsed:
            return execute_compose_tool(
                to=parsed["to"],
                subject=parsed["subject"],
                body=parsed["body"],
                mode="new",
                account=account,
                intent=parsed.get("intent") or None,
                cc=parsed.get("cc", ""),
                bcc=parsed.get("bcc", ""),
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
    drafted_in_turn = False

    for part in parts:
        step_res = _run_single_step(account, part, ctx)
        filtered_actions = []
        for action in step_res.get("ui_actions", []):
            action_type = action.get("type")
            if drafted_in_turn and action_type in ("submit_compose", "confirm_schedule"):
                continue
            if action_type in ("fill_compose", "update_compose_draft"):
                drafted_in_turn = True
            filtered_actions.append(action)
            all_actions.append(action)
            if action_type == "open_email" and action.get("email"):
                ctx["open_email_id"] = action["email"]["id"]
                ctx["current_view"] = "detail"
            elif action_type == "apply_filters" and action.get("emails"):
                ctx["open_email_id"] = action["emails"][0]["id"]
        if step_res.get("reply") and not (
            drafted_in_turn
            and not filtered_actions
            and any(
                a.get("type") in ("submit_compose", "confirm_schedule")
                for a in step_res.get("ui_actions", [])
            )
        ):
            replies.append(step_res["reply"])
        all_cards.extend(step_res.get("rich_cards", []))
        steps.extend(
            step_res.get("agent_steps")
            or [a["type"].replace("_", " ").title() for a in filtered_actions]
            or [f"Executed: {part[:32]}"]
        )

    return {
        "reply": "\n\n".join(replies),
        "ui_actions": all_actions,
        "rich_cards": all_cards,
        "agent_steps": steps,
    }
