from typing import Any, Dict, List, Optional

from accounts.models import MailAccount
from mail.models import EmailMessage
from mail.services.queries import query_emails


def execute_compose_tool(
    to: str,
    subject: str,
    body: str,
    mode: str = "new",
    thread_id: Optional[str] = None,
    in_reply_to: Optional[str] = None,
) -> Dict[str, Any]:
    draft = {
        "to": to.strip(),
        "subject": subject.strip(),
        "body": body.strip(),
        "thread_id": thread_id,
        "in_reply_to": in_reply_to,
        "mode": mode,
    }
    return {
        "reply": (
            f"I've opened the compose view and filled in your {mode} email to **{draft['to']}**. "
            "Please review it and confirm when you're ready to send."
        ),
        "ui_actions": [
            {"type": "navigate_view", "view": "compose"},
            {"type": "fill_compose", **draft},
        ],
        "rich_cards": [
            {"type": "send_confirmation", "draft": draft},
        ],
    }


def execute_search_tool(
    account: MailAccount,
    *,
    folder: str = "inbox",
    q: Optional[str] = None,
    sender: Optional[str] = None,
    is_read: Optional[bool] = None,
    days: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    qs = query_emails(
        account,
        folder=folder,
        q=q,
        sender=sender,
        is_read=is_read,
        days=days,
        date_from=date_from,
        date_to=date_to,
    )
    results = [m.to_dict(include_body=False) for m in qs[:50]]

    filter_parts: List[str] = []
    if folder == "sent":
        filter_parts.append("Sent")
    else:
        filter_parts.append("Inbox")
    if is_read is False:
        filter_parts.append("unread only")
    elif is_read is True:
        filter_parts.append("read only")
    if sender:
        filter_parts.append(f"from '{sender}'")
    if q:
        filter_parts.append(f"matching '{q}'")
    if days:
        filter_parts.append(f"last {days} days")

    summary = ", ".join(filter_parts)
    reply = (
        f"Updated the main view with **{len(results)}** email(s) ({summary})."
        if results
        else f"No emails matched ({summary}). I've updated the main view to show the empty result."
    )

    return {
        "reply": reply,
        "ui_actions": [
            {
                "type": "apply_filters",
                "folder": folder,
                "q": q or "",
                "sender": sender or "",
                "is_read": is_read,
                "days": days,
                "date_from": date_from or "",
                "date_to": date_to or "",
                "emails": results,
            }
        ],
        "rich_cards": [
            {"type": "email_preview", "email": item} for item in results[:3]
        ],
    }


def execute_open_email_tool(
    account: MailAccount,
    *,
    email_id: Optional[int] = None,
    sender: Optional[str] = None,
    q: Optional[str] = None,
    folder: Optional[str] = None,
) -> Dict[str, Any]:
    target: Optional[EmailMessage] = None
    if email_id:
        target = EmailMessage.objects.filter(account=account, id=email_id).first()
    else:
        qs = query_emails(account, folder=folder or "all", sender=sender, q=q)
        target = qs.first()

    if not target:
        return {
            "reply": "I couldn't find a matching email to open.",
            "ui_actions": [],
            "rich_cards": [],
        }

    if not target.is_read and target.folder == EmailMessage.FOLDER_INBOX:
        target.is_read = True
        target.save(update_fields=["is_read"])

    thread_msgs = [
        m.to_dict(include_body=True)
        for m in EmailMessage.objects.filter(
            account=account, thread_id=target.thread_id
        ).order_by("received_at", "id")
    ]
    email_dict = target.to_dict(include_body=True)

    return {
        "reply": f"Opened **{email_dict['subject']}** from {email_dict['sender_name']}.",
        "ui_actions": [
            {"type": "open_email", "email": email_dict, "thread": thread_msgs}
        ],
        "rich_cards": [{"type": "email_preview", "email": email_dict}],
    }


def execute_reply_open_email(
    account: MailAccount,
    open_email_id: Optional[int],
    custom_body: Optional[str] = None,
) -> Dict[str, Any]:
    if not open_email_id:
        return {
            "reply": "No email is currently open. Open an email first or tell me who you want to reply to.",
            "ui_actions": [],
            "rich_cards": [],
        }

    target = EmailMessage.objects.filter(account=account, id=open_email_id).first()
    if not target:
        return {
            "reply": "I couldn't find the currently open email.",
            "ui_actions": [],
            "rich_cards": [],
        }

    reply_to = (
        target.recipient_email
        if target.folder == EmailMessage.FOLDER_SENT
        else target.sender_email
    )
    subject = (
        target.subject
        if target.subject.lower().startswith("re:")
        else f"Re: {target.subject}"
    )
    body = custom_body or (
        f"Hi {target.sender_name or reply_to.split('@')[0]},\n\n"
        f"Thanks for your email regarding \"{target.subject}\".\n\n"
        "Best regards,"
    )
    return execute_compose_tool(
        to=reply_to,
        subject=subject,
        body=body,
        mode="reply",
        thread_id=target.thread_id,
        in_reply_to=target.provider_message_id,
    )


def execute_forward_open_email(
    account: MailAccount,
    open_email_id: Optional[int],
    to: str = "",
) -> Dict[str, Any]:
    if not open_email_id:
        return {
            "reply": "No email is currently open to forward. Please open an email first.",
            "ui_actions": [],
            "rich_cards": [],
        }

    target = EmailMessage.objects.filter(account=account, id=open_email_id).first()
    if not target:
        return {
            "reply": "I couldn't find the currently open email.",
            "ui_actions": [],
            "rich_cards": [],
        }

    subject = (
        target.subject
        if target.subject.lower().startswith("fwd:")
        else f"Fwd: {target.subject}"
    )
    body = (
        f"\n\n---------- Forwarded message ---------\n"
        f"From: {target.sender_name} <{target.sender_email}>\n"
        f"Subject: {target.subject}\n\n"
        f"{target.body_text}"
    )
    return execute_compose_tool(
        to=to,
        subject=subject,
        body=body,
        mode="forward",
    )
