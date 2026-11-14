import re
from typing import Any, Dict, Optional

from accounts.models import MailAccount
from assistant.services.tools import (
    execute_compose_tool,
    execute_forward_open_email,
    execute_open_email_tool,
    execute_reply_open_email,
    execute_search_tool,
)


def _extract_quoted(text: str) -> str:
    return text.strip().strip("'\"").strip("\u2018\u2019\u201c\u201d")


def _parse_compose(message: str) -> Optional[Dict[str, str]]:
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", message)
    if not email_match:
        return None
    to_addr = email_match.group(0)

    subject = ""
    subj_match = re.search(
        r"(?:with\s+)?subject\s*[:=]?\s*(?:'([^']*)'|\"([^\"]*)\"|\u2018([^\u2019]*)\u2019|\u201c([^\u201d]*)\u201d|([^\n]+?)(?=\s+(?:and\s+)?body|\s+saying|$))",
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
    if "today" in lower:
        return 1
    if "this week" in lower or "last week" in lower or "past week" in lower:
        return 7
    if "this month" in lower or "last month" in lower:
        return 30
    return None


def _parse_sender(message: str) -> Optional[str]:
    m = re.search(
        r"\bfrom\s+([A-Za-z0-9_.+-]+(?:@[A-Za-z0-9.-]+)?)(?=\s+(?:about|regarding|with|from|in|this|last|$))",
        message,
        re.IGNORECASE,
    )
    if m:
        candidate = m.group(1).strip()
        if candidate.lower() not in ("the", "last", "this", "past", "today"):
            return candidate
    m_end = re.search(r"\bfrom\s+([A-Za-z0-9_.+-]+(?:@[A-Za-z0-9.-]+)?)\s*$", message, re.IGNORECASE)
    if m_end:
        candidate = m_end.group(1).strip()
        if candidate.lower() not in ("the", "last", "this", "past", "today"):
            return candidate
    return None


def _parse_about_keyword(message: str) -> Optional[str]:
    m = re.search(r"\b(?:about|regarding|containing)\s+(?:the\s+)?(.+?)(?=\s+(?:from|in\s+the\s+last|$))", message, re.IGNORECASE)
    if m:
        return _extract_quoted(m.group(1))
    return None


def run_fallback_nlu(
    account: MailAccount, message: str, ui_context: Dict[str, Any]
) -> Dict[str, Any]:
    text = message.strip()
    lower = text.lower()
    open_email_id = ui_context.get("open_email_id")

    # 1. Reply to currently open email
    if re.search(r"\breply\b", lower):
        custom_body = None
        m_say = re.search(r"(?:saying|with|body)\s+['\"\u2018\u201c]?(.+?)['\"\u2019\u201d]?$", text, re.IGNORECASE | re.DOTALL)
        if m_say:
            custom_body = m_say.group(1).strip()
        return execute_reply_open_email(account, open_email_id, custom_body=custom_body)

    # 2. Forward currently open email
    if re.search(r"\bforward\b", lower):
        email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
        to_addr = email_match.group(0) if email_match else ""
        return execute_forward_open_email(account, open_email_id, to=to_addr)

    # 3. Compose / Send email
    if any(k in lower for k in ("send ", "compose ", "write ", "draft ", "email to ")):
        parsed = _parse_compose(text)
        if parsed:
            return execute_compose_tool(
                to=parsed["to"],
                subject=parsed["subject"] or "Hello",
                body=parsed["body"] or "",
                mode="new",
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

    # 5. Open specific email (e.g., "Open the latest email from David")
    if re.search(r"\bopen\b", lower) and not any(v in lower for v in ("inbox", "sent", "compose")):
        sender = _parse_sender(text)
        q = _parse_about_keyword(text)
        if sender or q:
            return execute_open_email_tool(account, sender=sender, q=q)

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
    sender = _parse_sender(text)
    q = _parse_about_keyword(text)

    if any([is_read is not None, days is not None, sender, q, "show" in lower, "find" in lower, "search" in lower, "filter" in lower]):
        return execute_search_tool(
            account,
            folder=folder,
            q=q,
            sender=sender,
            is_read=is_read,
            days=days,
        )

    return {
        "reply": (
            "I can control the mail UI for you! Try saying:\n"
            "- *\"Send an email to john@example.com with subject 'Meeting Tomorrow' and body 'Let's meet at 3pm'\"*\n"
            "- *\"Show only unread emails from this week\"*\n"
            "- *\"Find the email from Sarah about the project update\"*\n"
            "- *\"Open the latest email from David\"*\n"
            "- *\"Reply to this\"* (while reading an email)"
        ),
        "ui_actions": [],
        "rich_cards": [],
    }
