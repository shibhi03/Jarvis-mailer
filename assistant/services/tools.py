from typing import Any, Dict, List, Optional

from accounts.models import MailAccount
from mail.models import EmailMessage
from mail.services.contacts import resolve_recipient, upsert_contact
from mail.services.queries import query_emails


def execute_compose_tool(
    to: str,
    subject: str,
    body: str,
    mode: str = "new",
    thread_id: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    account: Optional[MailAccount] = None,
) -> Dict[str, Any]:
    resolved_to = (to or "").strip()
    contact_note = ""
    if account is not None and resolved_to and "@" not in resolved_to:
        email_addr, contact, _ = resolve_recipient(account, resolved_to)
        if not email_addr:
            return {
                "reply": (
                    f"I couldn't find **{resolved_to}** in your Contact Book. "
                    f"Please provide their email address (or say *\"Save contact {resolved_to} name@example.com\"*)."
                ),
                "ui_actions": [],
                "rich_cards": [],
            }
        contact_note = f" ({contact.name})" if contact else ""
        resolved_to = email_addr

    draft = {
        "to": resolved_to,
        "subject": subject.strip(),
        "body": body.strip(),
        "thread_id": thread_id,
        "in_reply_to": in_reply_to,
        "mode": mode,
    }
    return {
        "reply": (
            f"I've opened the compose view and filled in your {mode} email to **{draft['to']}**{contact_note}. "
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
    folder_labels = {
        "sent": "Sent",
        "drafts": "Drafts",
        "starred": "Starred",
        "spam": "Spam",
        "bin": "Bin",
        "scheduled": "Scheduled",
    }
    filter_parts.append(folder_labels.get(folder, "Inbox"))
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
    days: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    target: Optional[EmailMessage] = None
    if email_id:
        target = EmailMessage.objects.filter(account=account, id=email_id).first()
    else:
        qs = query_emails(
            account,
            folder=folder or "inbox",
            sender=sender,
            q=q,
            days=days,
            date_from=date_from,
            date_to=date_to,
        )
        target = qs.first()
        if not target and not folder:
            target = query_emails(
                account,
                folder="all",
                sender=sender,
                q=q,
                days=days,
                date_from=date_from,
                date_to=date_to,
            ).first()

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
        account=account,
    )


def execute_save_contact_tool(
    account: MailAccount, name: str, email: str
) -> Dict[str, Any]:
    contact = upsert_contact(account, name=name, email=email)
    if not contact:
        return {
            "reply": "Please provide a valid email address to save to the Contact Book.",
            "ui_actions": [],
            "rich_cards": [],
        }
    return {
        "reply": f"Saved **{contact.name}** (`{contact.email}`) to your Contact Book.",
        "ui_actions": [{"type": "refresh_contacts"}],
        "rich_cards": [],
    }


def execute_star_open_email(
    account: MailAccount, open_email_id: Optional[int], starred: bool = True
) -> Dict[str, Any]:
    if not open_email_id:
        return {"reply": "Open an email first to star or unstar it.", "ui_actions": [], "rich_cards": []}
    target = EmailMessage.objects.filter(account=account, id=open_email_id).first()
    if not target:
        return {"reply": "Could not find the open email.", "ui_actions": [], "rich_cards": []}
    target.is_starred = starred
    target.save(update_fields=["is_starred"])
    return {
        "reply": f"{'Starred' if starred else 'Unstarred'} **{target.subject}**.",
        "ui_actions": [{"type": "update_star", "id": target.id, "is_starred": starred}],
        "rich_cards": [],
    }


def execute_move_open_email(
    account: MailAccount, open_email_id: Optional[int], target_folder: str
) -> Dict[str, Any]:
    if not open_email_id:
        return {"reply": "Open an email first to move it.", "ui_actions": [], "rich_cards": []}
    target = EmailMessage.objects.filter(account=account, id=open_email_id).first()
    if not target:
        return {"reply": "Could not find the open email.", "ui_actions": [], "rich_cards": []}
    target.folder = target_folder
    target.save(update_fields=["folder"])
    return execute_search_tool(account, folder="inbox")


def execute_read_email_detail(
    account: MailAccount,
    email_id: Optional[int] = None,
    sender: Optional[str] = None,
    q: Optional[str] = None,
) -> Dict[str, Any]:
    """Read full email & thread data for agent reasoning (without forcing UI navigation)."""
    target: Optional[EmailMessage] = None
    if email_id:
        target = EmailMessage.objects.filter(account=account, id=email_id).first()
    else:
        target = query_emails(account, folder="all", sender=sender, q=q).first()
    if not target:
        return {"found": False, "error": "No matching email found."}
    thread = [
        m.to_dict(include_body=True)
        for m in EmailMessage.objects.filter(
            account=account, thread_id=target.thread_id
        ).order_by("received_at", "id")
    ]
    return {"found": True, "email": target.to_dict(include_body=True), "thread": thread}


def execute_schedule_tool(
    account: MailAccount,
    to: str,
    subject: str,
    body: str,
    scheduled_at: str,
) -> Dict[str, Any]:
    import uuid
    from datetime import datetime
    from django.utils import timezone

    resolved_to = (to or "").strip()
    if resolved_to and "@" not in resolved_to:
        email_addr, _, _ = resolve_recipient(account, resolved_to)
        if not email_addr:
            return {
                "reply": f"I couldn't find **{resolved_to}** in your Contact Book to schedule this email.",
                "ui_actions": [],
                "rich_cards": [],
            }
        resolved_to = email_addr

    try:
        dt = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
    except ValueError:
        return {
            "reply": f"Could not parse scheduled time `{scheduled_at}`. Use ISO format like `2026-11-15T09:00:00`.",
            "ui_actions": [],
            "rich_cards": [],
        }

    msg = EmailMessage.objects.create(
        account=account,
        provider_message_id=f"sched-{uuid.uuid4().hex[:10]}",
        thread_id=f"thread-{uuid.uuid4().hex[:10]}",
        folder=EmailMessage.FOLDER_SCHEDULED,
        sender_name=account.display_name or "Me",
        sender_email=account.email,
        recipient_email=resolved_to,
        subject=subject.strip() or "(No subject)",
        snippet=" ".join(body.split())[:140],
        body_text=body.strip(),
        is_read=True,
        scheduled_at=dt,
        received_at=timezone.now(),
    )
    return {
        "reply": f"Scheduled email **{msg.subject}** to **{resolved_to}** for `{dt.strftime('%Y-%m-%d %H:%M')}`.",
        "ui_actions": [
            {
                "type": "apply_filters",
                "folder": "scheduled",
                "emails": [
                    m.to_dict(include_body=False)
                    for m in query_emails(account, folder="scheduled")[:50]
                ],
            }
        ],
        "rich_cards": [{"type": "email_preview", "email": msg.to_dict(include_body=False)}],
    }
