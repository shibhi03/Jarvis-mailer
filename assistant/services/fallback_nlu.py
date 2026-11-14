import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from django.utils import timezone

from accounts.models import MailAccount
from assistant.services.tools import (
    execute_compose_tool,
    execute_forward_open_email,
    execute_open_email_tool,
    execute_reply_open_email,
    execute_save_contact_tool,
    execute_search_tool,
)

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
            r"\b(?:to)\s+([A-Za-z][A-Za-z0-9 .'-]{0,40}?)(?=\s+(?:with\s+subject|subject|about|regarding|with\s+body|body|saying|message|$))",
            message,
            re.IGNORECASE,
        )
        if name_match:
            to_addr = name_match.group(1).strip()

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
        r"(?:and\s+)?(?:body|saying|message)\s*[:=]?\s*(?:'([^']*)'|\"([^\"]*)\"|\u2018([^\u2019]*)\u2019|\u201c([^\u201d]*)\u201d|(.+))$",
        message,
        re.IGNORECASE | re.DOTALL,
    )
    if body_match:
        body = next((g for g in body_match.groups() if g is not None), "").strip()

    return {"to": to_addr, "subject": _extract_quoted(subject), "body": _extract_quoted(body)}


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


def run_fallback_nlu(
    account: MailAccount, message: str, ui_context: Dict[str, Any]
) -> Dict[str, Any]:
    text = message.strip()
    lower = text.lower()
    open_email_id = ui_context.get("open_email_id")

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

    # 1. Reply to currently open email
    if re.search(r"\breply\b", lower):
        custom_body = None
        m_say = re.search(r"(?:saying|with|body)\s+['\"\u2018\u201c]?(.+?)['\"\u2019\u201d]?$", text, re.IGNORECASE | re.DOTALL)
        if m_say:
            custom_body = m_say.group(1).strip()
        return execute_reply_open_email(account, open_email_id, custom_body=custom_body)

    # 2. Forward currently open email (supports email OR contact name)
    if re.search(r"\bforward\b", lower):
        email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
        if email_match:
            to_addr = email_match.group(0)
        else:
            m_to = re.search(r"\bto\s+([A-Za-z][A-Za-z0-9 .'-]+)$", text, re.IGNORECASE)
            to_addr = m_to.group(1).strip() if m_to else ""
        return execute_forward_open_email(account, open_email_id, to=to_addr)

    # 3. Compose / Send email (supports email OR contact name)
    if any(k in lower for k in ("send ", "compose ", "write ", "draft ", "email to ", "mail to ")):
        parsed = _parse_compose(text)
        if parsed:
            return execute_compose_tool(
                to=parsed["to"],
                subject=parsed["subject"] or "Hello",
                body=parsed["body"] or "",
                mode="new",
                account=account,
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

    # 5. Open specific email (latest mail, by sender, by date, or by keyword)
    if re.search(r"\bopen\b", lower) and not any(v in lower for v in ("inbox", "sent", "compose", "contacts")):
        sender = _parse_sender(text)
        q = _parse_about_keyword(text)
        date_from, date_to = _parse_specific_date(lower)
        days = _parse_days(lower)
        is_latest = any(w in lower for w in ("latest", "newest", "recent", "last mail", "last email"))
        if sender or q or date_from or days or is_latest:
            return execute_open_email_tool(
                account,
                sender=sender,
                q=q,
                days=days,
                date_from=date_from,
                date_to=date_to,
            )

    # 6. Navigate to Sent or Inbox directly
    if re.fullmatch(r"(?:go\s+to\s+|open\s+|show\s+)?(?:my\s+)?sent(?:\s+emails?)?", lower):
        return execute_search_tool(account, folder="sent")
    if re.fullmatch(r"(?:go\s+to\s+|open\s+|show\s+)?(?:my\s+)?inbox", lower):
        return execute_search_tool(account, folder="inbox")

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
