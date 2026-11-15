from typing import Any, Dict, List, Optional

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from accounts.models import MailAccount
from assistant.services.drafter import generate_subject_and_body, revise_email_draft
from mail.models import CalendarEvent, Contact, EmailMessage
from mail.services.contacts import resolve_recipient, resolve_recipient_list, upsert_contact
from mail.services.queries import query_emails


def execute_close_email_tool() -> Dict[str, Any]:
    return {
        "reply": "Closed the open email.",
        "ui_actions": [{"type": "close_email"}],
        "rich_cards": [],
    }


def execute_compose_tool(
    to: str,
    subject: str,
    body: str,
    mode: str = "new",
    thread_id: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    account: Optional[MailAccount] = None,
    intent: Optional[str] = None,
    cc: str = "",
    bcc: str = "",
) -> Dict[str, Any]:
    resolved_to = (to or "").strip()
    resolved_cc = (cc or "").strip()
    resolved_bcc = (bcc or "").strip()
    contact_name = resolved_to
    contact_note = ""
    if account is not None:
        unresolved_all: List[str] = []
        contacts_to: List[Contact] = []
        if resolved_to:
            resolved_to, unresolved_to, contacts_to = resolve_recipient_list(account, resolved_to)
            unresolved_all.extend(unresolved_to)
        if resolved_cc:
            resolved_cc, unresolved_cc, _ = resolve_recipient_list(account, resolved_cc)
            unresolved_all.extend(unresolved_cc)
        if resolved_bcc:
            resolved_bcc, unresolved_bcc, _ = resolve_recipient_list(account, resolved_bcc)
            unresolved_all.extend(unresolved_bcc)
        if unresolved_all:
            missing_str = ", ".join(unresolved_all)
            first_missing = unresolved_all[0]
            return {
                "reply": (
                    f"I couldn't find **{missing_str}** in your Contact Book. "
                    f"Please provide their email address (or say *\"Save contact {first_missing} name@example.com\"*)."
                ),
                "ui_actions": [],
                "rich_cards": [],
            }
        if contacts_to:
            contact_name = ", ".join(c.name for c in contacts_to)
            contact_note = f" ({contact_name})"
        else:
            contact_name = resolved_to

    final_subject = (subject or "").strip()
    final_body = (body or "").strip()
    if intent and (not final_subject or not final_body):
        ai_subj, ai_body = generate_subject_and_body(contact_name, intent)
        if not final_subject:
            final_subject = ai_subj
        if not final_body:
            final_body = ai_body

    draft = {
        "to": resolved_to,
        "cc": resolved_cc,
        "bcc": resolved_bcc,
        "subject": final_subject or "Hello",
        "body": final_body,
        "thread_id": thread_id,
        "in_reply_to": in_reply_to,
        "mode": mode,
    }
    cc_note = f", CC **{resolved_cc}**" if resolved_cc else ""
    bcc_note = f", BCC **{resolved_bcc}**" if resolved_bcc else ""
    return {
        "reply": (
            f"I've opened the compose view and filled in your {mode} email to **{draft['to']}**{contact_note}{cc_note}{bcc_note}. "
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


def execute_rewrite_compose_tool(
    *,
    to: str,
    subject: str,
    body: str,
    instruction: str,
    scheduled_at: str = "",
    cc: str = "",
    bcc: str = "",
) -> Dict[str, Any]:
    if not (to or cc or bcc or subject or body):
        return {
            "reply": "There isn't an open email draft to edit. Open Compose or ask me to draft an email first.",
            "ui_actions": [],
            "rich_cards": [],
        }
    try:
        revised_subject, revised_body = revise_email_draft(subject, body, instruction)
    except Exception as exc:
        provider_name = "OpenAI" if settings.AI_PROVIDER == "openai" else "Gemini"
        return {
            "reply": f"{provider_name} couldn't revise the draft, so your current draft is unchanged. {exc}",
            "ui_actions": [],
            "rich_cards": [],
            "agent_steps": [f"Selected provider: {provider_name}", "Draft revision failed"],
        }
    if scheduled_at:
        cards = [
            {
                "type": "schedule_confirmation",
                "draft": {
                    "to": to,
                    "cc": cc,
                    "bcc": bcc,
                    "subject": revised_subject,
                    "body": revised_body,
                    "scheduled_at": scheduled_at,
                },
            }
        ]
    else:
        cards = [
            {
                "type": "send_confirmation",
                "draft": {
                    "to": to,
                    "cc": cc,
                    "bcc": bcc,
                    "subject": revised_subject,
                    "body": revised_body,
                },
            }
        ]
    return {
        "reply": "I revised the draft with AI. Please review the updated fields and confirm when you're ready to send or schedule.",
        "ui_actions": [
            {
                "type": "update_compose_draft",
                "to": to,
                "cc": cc,
                "bcc": bcc,
                "subject": revised_subject,
                "body": revised_body,
                "scheduled_at": scheduled_at,
            }
        ],
        "rich_cards": cards,
        "agent_steps": [f"Revised draft with {settings.AI_PROVIDER.title()}"],
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
    account: MailAccount,
    open_email_id: Optional[int],
    target_folder: str,
    *,
    subject: Optional[str] = None,
    sender: Optional[str] = None,
    email_address: Optional[str] = None,
    name: Optional[str] = None,
    q: Optional[str] = None,
    move_all: bool = False,
) -> Dict[str, Any]:
    folder_key = (target_folder or "").strip().lower()
    has_query = any([subject, sender, email_address, name, q, move_all])
    if folder_key == "bin" and (not open_email_id or has_query):
        return execute_delete_email_tool(
            account,
            email_id=None if has_query else open_email_id,
            subject=subject,
            sender=sender,
            email_address=email_address,
            name=name,
            q=q,
            delete_all=move_all,
            move_to_bin_only=True,
        )
    if folder_key == "restore" or (
        folder_key == "inbox"
        and (
            not open_email_id
            or has_query
            or EmailMessage.objects.filter(
                account=account, id=open_email_id, folder=EmailMessage.FOLDER_BIN
            ).exists()
        )
    ):
        return execute_restore_email_tool(
            account,
            email_id=None if has_query else open_email_id,
            subject=subject,
            sender=sender,
            email_address=email_address,
            name=name,
            q=q,
            restore_all=move_all,
        )
    if not open_email_id:
        return {"reply": "Open an email first to move it.", "ui_actions": [], "rich_cards": []}
    target = EmailMessage.objects.filter(account=account, id=open_email_id).first()
    if not target:
        return {"reply": "Could not find the open email.", "ui_actions": [], "rich_cards": []}
    target.folder = folder_key
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
    intent: Optional[str] = None,
    client_tz=None,
    cc: str = "",
    bcc: str = "",
) -> Dict[str, Any]:
    from datetime import datetime
    from django.utils import timezone

    resolved_to = (to or "").strip()
    resolved_cc = (cc or "").strip()
    resolved_bcc = (bcc or "").strip()
    contact_name = resolved_to
    unresolved_all: List[str] = []
    contacts_to: List[Contact] = []
    if resolved_to:
        resolved_to, unresolved_to, contacts_to = resolve_recipient_list(account, resolved_to)
        unresolved_all.extend(unresolved_to)
    if resolved_cc:
        resolved_cc, unresolved_cc, _ = resolve_recipient_list(account, resolved_cc)
        unresolved_all.extend(unresolved_cc)
    if resolved_bcc:
        resolved_bcc, unresolved_bcc, _ = resolve_recipient_list(account, resolved_bcc)
        unresolved_all.extend(unresolved_bcc)
    if unresolved_all:
        return {
            "reply": f"I couldn't find **{', '.join(unresolved_all)}** in your Contact Book to schedule this email.",
            "ui_actions": [],
            "rich_cards": [],
        }
    if contacts_to:
        contact_name = ", ".join(c.name for c in contacts_to)
    else:
        contact_name = resolved_to

    final_subject = (subject or "").strip()
    final_body = (body or "").strip()
    if intent and (not final_subject or not final_body):
        try:
            ai_subj, ai_body = generate_subject_and_body(contact_name, intent)
        except Exception as exc:
            provider_name = "OpenAI" if settings.AI_PROVIDER == "openai" else "Gemini"
            return {
                "reply": f"{provider_name} couldn't draft the scheduled email. {exc}",
                "ui_actions": [], "rich_cards": [],
                "agent_steps": [f"Selected provider: {provider_name}", "Email drafting failed"],
            }
        if not final_subject:
            final_subject = ai_subj
        if not final_body:
            final_body = ai_body

    try:
        dt = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, client_tz or timezone.get_current_timezone())
    except ValueError:
        return {
            "reply": f"Could not parse scheduled time `{scheduled_at}`. Use ISO format like `2026-11-15T09:00:00`.",
            "ui_actions": [],
            "rich_cards": [],
        }

    return {
        "reply": "Please review the prepared email below. Edit any field in the compose view, then confirm to schedule it.",
        "ui_actions": [
            {"type": "navigate_view", "view": "compose"},
            {
                "type": "fill_compose",
                "to": resolved_to,
                "cc": resolved_cc,
                "bcc": resolved_bcc,
                "subject": final_subject or "(No subject)",
                "body": final_body,
                "scheduled_at": dt.isoformat(),
            },
        ],
        "rich_cards": [{"type": "schedule_confirmation", "draft": {
            "to": resolved_to,
            "cc": resolved_cc,
            "bcc": resolved_bcc,
            "subject": final_subject or "(No subject)",
            "body": final_body,
            "scheduled_at": dt.isoformat(),
        }}],
        "agent_steps": ["Prepared email draft", "Waiting for your scheduling confirmation"],
    }


def execute_save_draft_tool(
    account: MailAccount,
    to: str = "",
    subject: str = "",
    body: str = "",
    intent: Optional[str] = None,
    cc: str = "",
    bcc: str = "",
) -> Dict[str, Any]:
    import uuid
    from django.utils import timezone

    resolved_to, unresolved_to, contacts_to = resolve_recipient_list(account, to)
    if unresolved_to:
        parts = [p.strip() for p in resolved_to.split(",") if p.strip()] + unresolved_to
        resolved_to = ", ".join(parts)
    resolved_cc, unresolved_cc, _ = resolve_recipient_list(account, cc)
    if unresolved_cc:
        parts = [p.strip() for p in resolved_cc.split(",") if p.strip()] + unresolved_cc
        resolved_cc = ", ".join(parts)
    resolved_bcc, unresolved_bcc, _ = resolve_recipient_list(account, bcc)
    if unresolved_bcc:
        parts = [p.strip() for p in resolved_bcc.split(",") if p.strip()] + unresolved_bcc
        resolved_bcc = ", ".join(parts)

    contact_name = ", ".join(c.name for c in contacts_to) if contacts_to else resolved_to

    final_subject = (subject or "").strip()
    final_body = (body or "").strip()
    if intent and (not final_subject or not final_body):
        ai_subj, ai_body = generate_subject_and_body(contact_name, intent)
        if not final_subject:
            final_subject = ai_subj
        if not final_body:
            final_body = ai_body

    draft = EmailMessage.objects.create(
        account=account,
        provider_message_id=f"draft-{uuid.uuid4().hex[:10]}",
        thread_id=f"thread-{uuid.uuid4().hex[:10]}",
        folder=EmailMessage.FOLDER_DRAFTS,
        sender_name=account.display_name or "Me",
        sender_email=account.email,
        recipient_email=resolved_to,
        cc_email=resolved_cc,
        bcc_email=resolved_bcc,
        subject=final_subject or "(No subject)",
        snippet=" ".join(final_body.split())[:140],
        body_text=final_body,
        is_read=True,
        received_at=timezone.now(),
    )
    cc_note = f" (CC: **{resolved_cc}**)" if resolved_cc else ""
    bcc_note = f" (BCC: **{resolved_bcc}**)" if resolved_bcc else ""
    return {
        "reply": f"Saved draft **{draft.subject}**" + (f" to **{resolved_to}**." if resolved_to else ".") + cc_note + bcc_note,
        "ui_actions": [
            {
                "type": "apply_filters",
                "folder": "drafts",
                "emails": [
                    m.to_dict(include_body=False)
                    for m in query_emails(account, folder="drafts")[:50]
                ],
            }
        ],
        "rich_cards": [{"type": "email_preview", "email": draft.to_dict(include_body=False)}],
    }


def execute_mark_read_open_email(
    account: MailAccount, open_email_id: Optional[int], is_read: bool = False
) -> Dict[str, Any]:
    if not open_email_id:
        return {"reply": "Open an email first to change its read status.", "ui_actions": [], "rich_cards": []}
    target = EmailMessage.objects.filter(account=account, id=open_email_id).first()
    if not target:
        return {"reply": "Could not find the open email.", "ui_actions": [], "rich_cards": []}
    target.is_read = is_read
    target.save(update_fields=["is_read"])
    return {
        "reply": f"Marked **{target.subject}** as {'read' if is_read else 'unread'}.",
        "ui_actions": [{"type": "update_read", "id": target.id, "is_read": is_read}],
        "rich_cards": [],
    }


def execute_sync_now_tool(account: MailAccount) -> Dict[str, Any]:
    from mail.services.contacts import sync_contacts_from_messages
    from mail.services.provider import get_provider_for_account

    provider = get_provider_for_account(account)
    try:
        added = provider.sync_messages(max_results=25)
    except Exception as exc:
        return {"reply": f"Sync failed: {exc}", "ui_actions": [], "rich_cards": []}
    sync_contacts_from_messages(account)
    res = execute_search_tool(account, folder="inbox")
    res["reply"] = f"Synced your mailbox ({added} new email(s))."
    return res


def _filter_emails_by_target(
    account: MailAccount,
    qs,
    *,
    subject: Optional[str] = None,
    sender: Optional[str] = None,
    recipient: Optional[str] = None,
    email_address: Optional[str] = None,
    name: Optional[str] = None,
    q: Optional[str] = None,
):
    if subject and subject.strip():
        qs = qs.filter(subject__icontains=subject.strip())

    if email_address and email_address.strip():
        addr = email_address.strip()
        qs = qs.filter(
            Q(sender_email__icontains=addr)
            | Q(recipient_email__icontains=addr)
            | Q(cc_email__icontains=addr)
            | Q(bcc_email__icontains=addr)
        )

    for person in (sender, name):
        if person and person.strip():
            tok = person.strip()
            resolved_addrs = set(
                Contact.objects.filter(account=account, name__icontains=tok).values_list("email", flat=True)
            )
            p_addr = tok if "@" in tok else resolve_recipient(account, tok)[0]
            if p_addr:
                resolved_addrs.add(p_addr)
            person_q = (
                Q(sender_name__icontains=tok)
                | Q(sender_email__icontains=tok)
                | Q(recipient_email__icontains=tok)
                | Q(cc_email__icontains=tok)
                | Q(bcc_email__icontains=tok)
            )
            for addr in resolved_addrs:
                person_q |= (
                    Q(sender_email__icontains=addr)
                    | Q(recipient_email__icontains=addr)
                    | Q(cc_email__icontains=addr)
                    | Q(bcc_email__icontains=addr)
                )
            qs = qs.filter(person_q)

    if recipient and recipient.strip():
        r = recipient.strip()
        r_addr = r if "@" in r else resolve_recipient(account, r)[0]
        rec_q = Q(recipient_email__icontains=r) | Q(cc_email__icontains=r) | Q(bcc_email__icontains=r)
        if r_addr:
            rec_q |= (
                Q(recipient_email__icontains=r_addr)
                | Q(cc_email__icontains=r_addr)
                | Q(bcc_email__icontains=r_addr)
            )
        qs = qs.filter(rec_q)

    if q and q.strip():
        term = q.strip()
        term_addr = term if "@" in term else resolve_recipient(account, term)[0]
        q_filter = (
            Q(subject__icontains=term)
            | Q(body_text__icontains=term)
            | Q(sender_name__icontains=term)
            | Q(sender_email__icontains=term)
            | Q(recipient_email__icontains=term)
            | Q(cc_email__icontains=term)
            | Q(bcc_email__icontains=term)
        )
        if term_addr:
            q_filter |= (
                Q(sender_email__icontains=term_addr)
                | Q(recipient_email__icontains=term_addr)
                | Q(cc_email__icontains=term_addr)
                | Q(bcc_email__icontains=term_addr)
            )
        qs = qs.filter(q_filter)

    return qs


def execute_delete_email_tool(
    account: MailAccount,
    *,
    email_id: Optional[int] = None,
    folder: Optional[str] = None,
    sender: Optional[str] = None,
    recipient: Optional[str] = None,
    subject: Optional[str] = None,
    email_address: Optional[str] = None,
    name: Optional[str] = None,
    q: Optional[str] = None,
    permanent: bool = False,
    delete_all: bool = False,
    move_to_bin_only: bool = False,
) -> Dict[str, Any]:
    if email_id:
        targets = list(EmailMessage.objects.filter(account=account, id=email_id))
    else:
        qs = EmailMessage.objects.filter(account=account)
        if folder and folder != "all":
            if folder == "starred":
                qs = qs.filter(is_starred=True).exclude(
                    folder__in=[EmailMessage.FOLDER_SPAM, EmailMessage.FOLDER_BIN]
                )
            else:
                qs = qs.filter(folder=folder)
        elif not permanent or move_to_bin_only:
            qs = qs.exclude(folder=EmailMessage.FOLDER_BIN)

        qs = _filter_emails_by_target(
            account,
            qs,
            subject=subject,
            sender=sender,
            recipient=recipient,
            email_address=email_address,
            name=name,
            q=q,
        )
        qs = qs.order_by("-received_at", "-id")
        has_filter = bool(
            (folder and folder in ("scheduled", "drafts", "bin", "spam"))
            or sender
            or recipient
            or subject
            or email_address
            or name
            or q
        )
        if delete_all and has_filter:
            targets = list(qs[:50])
        else:
            first = qs.first()
            targets = [first] if first else []

    if not targets:
        reply_msg = (
            "I couldn't find any matching email to move to Bin."
            if move_to_bin_only
            else "I couldn't find any matching email, draft, or scheduled mail to delete."
        )
        return {
            "reply": reply_msg,
            "ui_actions": [],
            "rich_cards": [],
        }

    target_folder = (
        folder
        if folder in ("inbox", "starred", "sent", "drafts", "scheduled", "spam", "bin")
        else targets[0].folder
    )
    deleted_count = 0
    trashed_count = 0
    last_subject = ""
    for target in targets:
        last_subject = target.subject
        if permanent or (
            not move_to_bin_only
            and target.folder
            in (
                EmailMessage.FOLDER_SCHEDULED,
                EmailMessage.FOLDER_DRAFTS,
                EmailMessage.FOLDER_BIN,
            )
        ):
            target.delete()
            deleted_count += 1
        elif target.folder != EmailMessage.FOLDER_BIN:
            target.folder = EmailMessage.FOLDER_BIN
            target.save(update_fields=["folder"])
            trashed_count += 1

    refreshed = [
        m.to_dict(include_body=False)
        for m in query_emails(account, folder=target_folder)[:50]
    ]
    if deleted_count and not trashed_count:
        if deleted_count == 1:
            reply = f"Deleted **{last_subject}** permanently."
        else:
            reply = f"Deleted **{deleted_count}** {target_folder} email(s) permanently."
    elif trashed_count and not deleted_count:
        if trashed_count == 1:
            reply = f"Moved **{last_subject}** to Bin."
        else:
            reply = f"Moved **{trashed_count}** email(s) to Bin."
    elif not trashed_count and not deleted_count:
        reply = f"**{last_subject}** is already in Bin."
    else:
        reply = f"Deleted {deleted_count} and moved {trashed_count} email(s) to Bin."

    return {
        "reply": reply,
        "ui_actions": [
            {
                "type": "apply_filters",
                "folder": target_folder,
                "q": "",
                "sender": "",
                "is_read": None,
                "days": None,
                "date_from": "",
                "date_to": "",
                "emails": refreshed,
            }
        ],
        "rich_cards": [],
    }


def execute_restore_email_tool(
    account: MailAccount,
    *,
    email_id: Optional[int] = None,
    subject: Optional[str] = None,
    sender: Optional[str] = None,
    email_address: Optional[str] = None,
    name: Optional[str] = None,
    q: Optional[str] = None,
    restore_all: bool = False,
) -> Dict[str, Any]:
    has_query = any([subject, sender, email_address, name, q])
    qs = EmailMessage.objects.filter(account=account, folder=EmailMessage.FOLDER_BIN)

    if email_id and not has_query and not restore_all:
        targets = list(qs.filter(id=email_id))
    else:
        qs = _filter_emails_by_target(
            account,
            qs,
            subject=subject,
            sender=sender,
            email_address=email_address,
            name=name,
            q=q,
        ).order_by("-received_at", "-id")
        if restore_all:
            targets = list(qs[:50])
        else:
            first = qs.first()
            targets = [first] if first else []

    if not targets:
        refreshed_bin = [
            m.to_dict(include_body=False)
            for m in query_emails(account, folder="bin")[:50]
        ]
        return {
            "reply": "I couldn't find any matching email in your Bin to restore.",
            "ui_actions": [
                {
                    "type": "apply_filters",
                    "folder": "bin",
                    "q": "",
                    "sender": "",
                    "is_read": None,
                    "days": None,
                    "date_from": "",
                    "date_to": "",
                    "emails": refreshed_bin,
                }
            ],
            "rich_cards": [],
        }

    restored_count = 0
    last_subject = ""
    for target in targets:
        last_subject = target.subject
        target.folder = EmailMessage.FOLDER_INBOX
        target.save(update_fields=["folder"])
        restored_count += 1

    refreshed_bin = [
        m.to_dict(include_body=False)
        for m in query_emails(account, folder="bin")[:50]
    ]
    reply = (
        f"Restored **{last_subject}** from Bin to Inbox."
        if restored_count == 1
        else f"Restored **{restored_count}** email(s) from Bin to Inbox."
    )
    return {
        "reply": reply,
        "ui_actions": [
            {
                "type": "apply_filters",
                "folder": "bin",
                "q": "",
                "sender": "",
                "is_read": None,
                "days": None,
                "date_from": "",
                "date_to": "",
                "emails": refreshed_bin,
            }
        ],
        "rich_cards": [],
    }


def execute_clear_bin_tool(account: MailAccount) -> Dict[str, Any]:
    deleted_count, _ = EmailMessage.objects.filter(
        account=account, folder=EmailMessage.FOLDER_BIN
    ).delete()
    reply = (
        f"Cleared your Bin (**{deleted_count}** email(s) permanently deleted)."
        if deleted_count
        else "Your Bin is already empty."
    )
    return {
        "reply": reply,
        "ui_actions": [
            {
                "type": "apply_filters",
                "folder": "bin",
                "q": "",
                "sender": "",
                "is_read": None,
                "days": None,
                "date_from": "",
                "date_to": "",
                "emails": [],
            }
        ],
        "rich_cards": [],
    }


def execute_edit_contact_tool(
    account: MailAccount,
    *,
    contact_id: Optional[int] = None,
    target_name: str = "",
    target_email: str = "",
    new_name: str = "",
    new_email: str = "",
    new_notes: Optional[str] = None,
) -> Dict[str, Any]:
    contact: Optional[Contact] = None
    if contact_id:
        contact = Contact.objects.filter(account=account, id=contact_id).first()
    elif target_email:
        contact = Contact.objects.filter(
            account=account, email__iexact=target_email.strip()
        ).first()
    elif target_name:
        needle = target_name.strip()
        contact = Contact.objects.filter(account=account, name__iexact=needle).first()
        if not contact:
            contact = Contact.objects.filter(
                Q(account=account) & (Q(name__icontains=needle) | Q(email__icontains=needle))
            ).first()

    if not contact:
        label = target_name or target_email or "that contact"
        return {
            "reply": f"I couldn't find **{label}** in your Contact Book.",
            "ui_actions": [{"type": "navigate_view", "view": "contacts"}, {"type": "refresh_contacts"}],
            "rich_cards": [],
        }

    updated_fields = []
    if new_email and new_email.strip():
        clean_email = new_email.strip().lower()
        if "@" not in clean_email:
            return {
                "reply": f"`{clean_email}` doesn't look like a valid email address.",
                "ui_actions": [],
                "rich_cards": [],
            }
        if Contact.objects.filter(account=account, email=clean_email).exclude(id=contact.id).exists():
            return {
                "reply": f"Another contact in your Contact Book already uses `{clean_email}`.",
                "ui_actions": [{"type": "navigate_view", "view": "contacts"}],
                "rich_cards": [],
            }
        contact.email = clean_email
        updated_fields.append("email")

    if new_name and new_name.strip():
        contact.name = new_name.strip()
        updated_fields.append("name")

    if new_notes is not None:
        contact.notes = new_notes.strip()
        updated_fields.append("notes")

    if not updated_fields:
        return {
            "reply": f"Tell me the new name, email, or notes for **{contact.name}** (`{contact.email}`).",
            "ui_actions": [{"type": "navigate_view", "view": "contacts"}, {"type": "refresh_contacts"}],
            "rich_cards": [],
        }

    contact.save(update_fields=updated_fields + ["updated_at"])
    return {
        "reply": f"Updated contact **{contact.name}** (`{contact.email}`).",
        "ui_actions": [
            {"type": "navigate_view", "view": "contacts"},
            {"type": "refresh_contacts"},
        ],
        "rich_cards": [],
    }


def execute_list_calendar_events_tool(
    account: MailAccount, *, upcoming_only: bool = True, client_tz=None
) -> Dict[str, Any]:
    now = timezone.now()
    qs = CalendarEvent.objects.filter(account=account).select_related("source_email")
    if upcoming_only:
        qs = qs.filter(start_at__gte=now)
    events = list(qs.order_by("start_at", "id")[:25])
    tz = client_tz or timezone.get_current_timezone()

    if events:
        lines = []
        for ev in events:
            local_dt = ev.start_at.astimezone(tz)
            when_str = local_dt.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")
            lines.append(f"- **{ev.title}** — {when_str}")
        label = "upcoming event(s)" if upcoming_only else "calendar event(s)"
        reply = f"You have **{len(events)}** {label}:\n" + "\n".join(lines)
    else:
        reply = (
            "You have no upcoming events scheduled on your Calendar."
            if upcoming_only
            else "Your Calendar has no saved events yet."
        )

    return {
        "reply": reply,
        "ui_actions": [
            {"type": "navigate_view", "view": "calendar", "calendar_mode": "list"},
            {"type": "refresh_calendar"},
        ],
        "rich_cards": [
            {"type": "calendar_event", "event": ev.to_dict()} for ev in events[:5]
        ],
    }


def execute_create_calendar_event_tool(
    account: MailAccount,
    *,
    title: str,
    start_at: str,
    description: str = "",
    reminder_minutes: int = 15,
    attendees: str = "",
    inform_via_email: bool = False,
    client_tz=None,
) -> Dict[str, Any]:
    from datetime import datetime

    clean_title = (title or "").strip() or "New Meeting"
    raw_start = (start_at or "").strip()
    dt = None
    tz = client_tz or timezone.get_current_timezone()
    if raw_start:
        try:
            dt = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, tz)
        except ValueError:
            from assistant.services.fallback_nlu import _parse_schedule_datetime

            parsed_iso = _parse_schedule_datetime(raw_start, client_tz=tz)
            if parsed_iso:
                dt = datetime.fromisoformat(parsed_iso)

    if dt is None or dt <= timezone.now():
        return {
            "reply": "Please provide a valid future date and time for the event (for example, 'tomorrow at 4pm' or '2026-11-20T15:00:00').",
            "ui_actions": [{"type": "navigate_view", "view": "calendar", "calendar_mode": "list"}],
            "rich_cards": [],
        }

    try:
        rem = int(reminder_minutes)
    except (TypeError, ValueError):
        rem = 15
    if rem not in (0, 5, 10, 15, 30, 60):
        rem = 15

    tokens = []
    if isinstance(attendees, list):
        tokens = [str(item).strip() for item in attendees if str(item).strip()]
    elif attendees:
        import re as _re

        tokens = [
            part.strip()
            for part in _re.split(r"\s*,\s*|\s+\band\b\s+", str(attendees))
            if part.strip()
        ]
    resolved_emails: List[str] = []
    for token in tokens:
        addr, _, _ = resolve_recipient(account, token)
        if addr:
            resolved_emails.append(addr)
        elif "@" in token:
            resolved_emails.append(token)
    attendees_csv = ", ".join(CalendarEvent._split_addresses(", ".join(resolved_emails)))

    event = CalendarEvent.objects.create(
        account=account,
        title=clean_title[:500],
        description=(description or "").strip(),
        attendees=attendees_csv,
        start_at=dt,
        reminder_minutes=rem,
    )

    display_dt = dt.astimezone(tz)
    when_str = display_dt.strftime("%b %d, %Y at %I:%M %p").replace(" 0", " ")
    sender_sig = account.display_name or account.email
    desc_block = f"\nDetails: {event.description}\n" if event.description else ""
    draft = {
        "to": attendees_csv,
        "subject": f"Invitation: {event.title}",
        "body": (
            f"Hi,\n\nI've scheduled \"{event.title}\" for {when_str}.\n"
            f"{desc_block}\nPlease let me know if this works for you.\n\nBest regards,\n{sender_sig}"
        ),
        "mode": "new",
        "calendar_event_id": event.id,
    }

    if inform_via_email:
        to_note = f" to **{draft['to']}**" if draft["to"] else ""
        return {
            "reply": (
                f"Created calendar event **{event.title}** for {when_str} and drafted an invitation email{to_note}. "
                "Please review it in Compose and confirm before sending."
            ),
            "ui_actions": [
                {"type": "refresh_calendar"},
                {"type": "navigate_view", "view": "compose"},
                {"type": "fill_compose", **draft},
            ],
            "rich_cards": [
                {"type": "calendar_event", "event": event.to_dict(), "draft": draft},
                {"type": "send_confirmation", "draft": draft},
            ],
        }

    return {
        "reply": f"Added **{event.title}** for {when_str} to your Calendar. Click **Inform Users (Draft Email)** below if you'd like to notify anyone.",
        "ui_actions": [
            {"type": "navigate_view", "view": "calendar", "calendar_mode": "list"},
            {"type": "refresh_calendar"},
        ],
        "rich_cards": [
            {"type": "calendar_event", "event": event.to_dict(), "draft": draft},
        ],
    }


def execute_user_profile_tool(account: MailAccount) -> Dict[str, Any]:
    from mail.services.gmail_provider import GmailMailProvider

    profile_details: Dict[str, Any] = {}
    if account.provider == MailAccount.PROVIDER_GMAIL:
        try:
            profile_details = GmailMailProvider(account).fetch_user_profile()
            account.refresh_from_db()
        except Exception:
            profile_details = {}

    unread_count = EmailMessage.objects.filter(
        account=account, folder=EmailMessage.FOLDER_INBOX, is_read=False
    ).count()
    contacts_count = account.contacts.count()
    events_count = CalendarEvent.objects.filter(
        account=account, start_at__gte=timezone.now()
    ).count()
    display_name = profile_details.get("display_name") or account.display_name or account.email
    provider_label = "Google Gmail" if account.provider == MailAccount.PROVIDER_GMAIL else "Demo / Local"

    lines = [
        f"- **Name**: {display_name}",
        f"- **Email**: {account.email}",
        f"- **Provider**: {provider_label}",
        f"- **Inbox Unread**: {unread_count}",
        f"- **Contacts**: {contacts_count}",
        f"- **Upcoming Events**: {events_count}",
    ]
    if profile_details.get("messages_total") is not None:
        lines.append(f"- **Total Gmail Messages**: {profile_details['messages_total']}")

    return {
        "reply": "Here are your connected account details:\n" + "\n".join(lines),
        "ui_actions": [{"type": "refresh_auth_status"}],
        "rich_cards": [],
        "observation": {
            "email": account.email,
            "display_name": display_name,
            "provider": account.provider,
            "unread_count": unread_count,
            "contacts_count": contacts_count,
            "upcoming_events": events_count,
            **profile_details,
        },
    }


def _resolve_attendee_emails_csv(account: MailAccount, attendees_raw: Any) -> str:
    if not attendees_raw:
        return ""
    import re as _re

    tokens = (
        [str(item).strip() for item in attendees_raw if str(item).strip()]
        if isinstance(attendees_raw, list)
        else [
            part.strip()
            for part in _re.split(r"\s*,\s*|\s*;\s*|\s+\band\b\s+", str(attendees_raw))
            if part.strip()
        ]
    )
    resolved: List[str] = []
    for token in tokens:
        addr, _, _ = resolve_recipient(account, token)
        if addr:
            resolved.append(addr)
        elif "@" in token:
            resolved.append(token)
    return ", ".join(CalendarEvent._split_addresses(", ".join(resolved)))


def execute_edit_calendar_event_tool(
    account: MailAccount,
    *,
    event_id: Optional[int] = None,
    target_title: str = "",
    new_title: str = "",
    start_at: str = "",
    description: Optional[str] = None,
    reminder_minutes: Optional[int] = None,
    attendees: Optional[str] = None,
    inform_via_email: bool = False,
    client_tz=None,
) -> Dict[str, Any]:
    from datetime import datetime

    qs = CalendarEvent.objects.filter(account=account).select_related("source_email")
    event: Optional[CalendarEvent] = None
    if event_id:
        event = qs.filter(id=event_id).first()
    elif target_title and target_title.strip():
        needle = target_title.strip()
        event = qs.filter(title__iexact=needle).first() or qs.filter(title__icontains=needle).first()
    else:
        user_created_qs = qs.filter(
            Q(source_email__isnull=True) | Q(source_email__folder=EmailMessage.FOLDER_SENT)
        ).order_by("start_at", "id")
        event = user_created_qs.filter(start_at__gte=timezone.now()).first() or user_created_qs.first()

    if not event:
        label = target_title or "that event"
        return {
            "reply": f"I couldn't find **{label}** on your Calendar.",
            "ui_actions": [{"type": "navigate_view", "view": "calendar", "calendar_mode": "list"}],
            "rich_cards": [],
        }

    if event.source_email is not None and event.source_email.folder != EmailMessage.FOLDER_SENT:
        return {
            "reply": f"**{event.title}** came from a received email, so only events created by you can be edited.",
            "ui_actions": [
                {"type": "navigate_view", "view": "calendar", "calendar_mode": "list"},
                {"type": "select_calendar_event", "id": event.id},
            ],
            "rich_cards": [],
        }

    tz = client_tz or timezone.get_current_timezone()
    changed = False
    if new_title and new_title.strip():
        event.title = new_title.strip()[:500]
        changed = True
    if description is not None:
        event.description = description.strip()
        changed = True
    if attendees is not None:
        resolved_att = _resolve_attendee_emails_csv(account, attendees)
        if resolved_att:
            event.attendees = ", ".join(CalendarEvent._split_addresses(event.attendees, resolved_att))
            changed = True

    if start_at and start_at.strip():
        raw_start = start_at.strip()
        dt = None
        try:
            dt = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, tz)
        except ValueError:
            from assistant.services.fallback_nlu import _parse_schedule_datetime

            parsed_iso = _parse_schedule_datetime(raw_start, client_tz=tz)
            if parsed_iso:
                dt = datetime.fromisoformat(parsed_iso)
        if dt is None or dt <= timezone.now():
            return {
                "reply": "Please provide a valid future date and time when updating the event.",
                "ui_actions": [{"type": "navigate_view", "view": "calendar", "calendar_mode": "list"}],
                "rich_cards": [],
            }
        event.start_at = dt
        event.reminder_acknowledged = False
        changed = True

    if reminder_minutes is not None:
        try:
            rem = int(reminder_minutes)
        except (TypeError, ValueError):
            rem = event.reminder_minutes
        if rem in (0, 5, 10, 15, 30, 60) and rem != event.reminder_minutes:
            event.reminder_minutes = rem
            event.reminder_acknowledged = False
            changed = True

    if changed:
        event.save()

    ev_dict = event.to_dict()
    to_emails = ev_dict.get("sent_to") or event.attendees or ""
    display_dt = event.start_at.astimezone(tz)
    when_str = display_dt.strftime("%b %d, %Y at %I:%M %p").replace(" 0", " ")
    sender_sig = account.display_name or account.email
    desc_block = f"\nDetails: {event.description}\n" if event.description else ""
    draft = {
        "to": to_emails,
        "subject": f"Updated Event: {event.title}",
        "body": (
            f"Hi,\n\nI've updated \"{event.title}\" to {when_str}.\n"
            f"{desc_block}\nPlease let me know if this works for you.\n\nBest regards,\n{sender_sig}"
        ),
        "mode": "new",
        "calendar_event_id": event.id,
    }

    if inform_via_email:
        to_note = f" to **{draft['to']}**" if draft["to"] else ""
        return {
            "reply": (
                f"Updated calendar event **{event.title}** ({when_str}) and prepared an update email{to_note}. "
                "Please review it in Compose and confirm before sending."
            ),
            "ui_actions": [
                {"type": "refresh_calendar"},
                {"type": "select_calendar_event", "id": event.id},
                {"type": "navigate_view", "view": "compose"},
                {"type": "fill_compose", **draft},
            ],
            "rich_cards": [
                {"type": "calendar_event", "event": ev_dict, "draft": draft},
                {"type": "send_confirmation", "draft": draft},
            ],
        }

    if not changed:
        return {
            "reply": f"Opened **{event.title}** for editing on your Calendar.",
            "ui_actions": [
                {"type": "navigate_view", "view": "calendar", "calendar_mode": "list"},
                {"type": "refresh_calendar"},
                {"type": "edit_calendar_event_form", "id": event.id},
            ],
            "rich_cards": [{"type": "calendar_event", "event": ev_dict, "draft": draft}],
        }

    return {
        "reply": f"Updated calendar event **{event.title}** to {when_str}. Use **Inform Users (Draft Email)** if you want to notify people about the update.",
        "ui_actions": [
            {"type": "navigate_view", "view": "calendar", "calendar_mode": "list"},
            {"type": "refresh_calendar"},
            {"type": "select_calendar_event", "id": event.id},
        ],
        "rich_cards": [{"type": "calendar_event", "event": ev_dict, "draft": draft}],
    }


def execute_delete_calendar_event_tool(
    account: MailAccount,
    *,
    event_id: Optional[int] = None,
    title: str = "",
) -> Dict[str, Any]:
    qs = CalendarEvent.objects.filter(account=account)
    event: Optional[CalendarEvent] = None
    if event_id:
        event = qs.filter(id=event_id).first()
    elif title and title.strip():
        needle = title.strip()
        event = qs.filter(title__iexact=needle).first() or qs.filter(title__icontains=needle).first()
    else:
        return {
            "reply": "Select a calendar event first or tell me the title of the event to delete.",
            "ui_actions": [{"type": "navigate_view", "view": "calendar", "calendar_mode": "list"}],
            "rich_cards": [],
        }

    if not event:
        return {
            "reply": f"I couldn't find **{title or event_id}** on your Calendar.",
            "ui_actions": [{"type": "navigate_view", "view": "calendar", "calendar_mode": "list"}],
            "rich_cards": [],
        }
    deleted_title = event.title
    event.delete()
    return {
        "reply": f"Deleted calendar event **{deleted_title}**.",
        "ui_actions": [
            {"type": "navigate_view", "view": "calendar", "calendar_mode": "list"},
            {"type": "refresh_calendar"},
        ],
        "rich_cards": [],
    }


def execute_delete_contact_tool(
    account: MailAccount,
    *,
    contact_id: Optional[int] = None,
    name: str = "",
    email: str = "",
) -> Dict[str, Any]:
    qs = Contact.objects.filter(account=account)
    contact: Optional[Contact] = None
    if contact_id:
        contact = qs.filter(id=contact_id).first()
    elif email and email.strip():
        contact = qs.filter(email__iexact=email.strip()).first()
    elif name and name.strip():
        needle = name.strip()
        contact = qs.filter(name__iexact=needle).first() or qs.filter(
            Q(name__icontains=needle) | Q(email__icontains=needle)
        ).first()

    if not contact:
        label = name or email or "that contact"
        return {
            "reply": f"I couldn't find **{label}** in your Contact Book.",
            "ui_actions": [{"type": "navigate_view", "view": "contacts"}, {"type": "refresh_contacts"}],
            "rich_cards": [],
        }
    c_name, c_email = contact.name, contact.email
    contact.delete()
    return {
        "reply": f"Deleted contact **{c_name}** (`{c_email}`).",
        "ui_actions": [
            {"type": "navigate_view", "view": "contacts"},
            {"type": "refresh_contacts"},
        ],
        "rich_cards": [],
    }


def execute_new_chat_tool(account: Optional[MailAccount] = None) -> Dict[str, Any]:
    return {
        "reply": "Started a new Jarvis chat.",
        "ui_actions": [{"type": "new_chat"}],
        "rich_cards": [],
    }


def execute_simulate_incoming_tool(account: MailAccount) -> Dict[str, Any]:
    import uuid
    from mail.services.realtime import realtime_broker

    msg = EmailMessage.objects.create(
        account=account,
        provider_message_id=f"push-{uuid.uuid4().hex[:10]}",
        thread_id=f"thread-{uuid.uuid4().hex[:8]}",
        folder=EmailMessage.FOLDER_INBOX,
        sender_name="Sarah Chen",
        sender_email="sarah.chen@nebulaknowlab.com",
        recipient_email=account.email,
        subject="Live Push Notification: Urgent Sync",
        snippet="Hey Alex, just testing real-time push delivery—this arrived without a manual refresh!",
        body_text="Hey Alex, just testing real-time push delivery—this arrived without a manual refresh!",
        is_read=False,
        received_at=timezone.now(),
    )
    realtime_broker.publish("new_email", msg.to_dict())
    return {
        "reply": f"Simulated incoming push email **{msg.subject}** from **{msg.sender_name}**.",
        "ui_actions": [
            {
                "type": "apply_filters",
                "folder": "inbox",
                "q": "",
                "sender": "",
                "is_read": None,
                "days": None,
                "emails": [m.to_dict(include_body=False) for m in query_emails(account, folder="inbox")[:50]],
            }
        ],
        "rich_cards": [{"type": "email_preview", "email": msg.to_dict(include_body=False)}],
    }


def execute_disconnect_gmail_tool(account: MailAccount) -> Dict[str, Any]:
    MailAccount.objects.filter(provider=MailAccount.PROVIDER_GMAIL).update(is_active=False)
    return {
        "reply": "Disconnected Gmail and switched to Demo Mode.",
        "ui_actions": [{"type": "disconnect_gmail"}, {"type": "refresh_auth_status"}],
        "rich_cards": [],
    }


def execute_trigger_ui_button_tool(
    account: MailAccount,
    action_name: str,
    *,
    open_email_id: Optional[int] = None,
    selected_event_id: Optional[int] = None,
    current_view: str = "inbox",
) -> Dict[str, Any]:
    key = (action_name or "").strip().lower().replace("-", "_").replace(" ", "_")

    folder_buttons = {"inbox", "starred", "sent", "drafts", "scheduled", "spam", "bin"}
    if key in folder_buttons or key == "clear_filters":
        target = current_view if key == "clear_filters" and current_view in folder_buttons else (key if key in folder_buttons else "inbox")
        return execute_search_tool(account, folder=target)

    if key == "compose":
        return {"reply": "Opened Compose.", "ui_actions": [{"type": "navigate_view", "view": "compose"}], "rich_cards": []}
    if key == "contacts":
        return {"reply": "Opened Contact Book.", "ui_actions": [{"type": "navigate_view", "view": "contacts"}], "rich_cards": []}
    if key == "meetings":
        return {"reply": "Opened Meeting Emails.", "ui_actions": [{"type": "navigate_view", "view": "meetings"}], "rich_cards": []}
    if key in ("calendar", "calendar_list_mode"):
        return execute_list_calendar_events_tool(account, upcoming_only=True)
    if key == "calendar_month_mode":
        return {
            "reply": "Switched Calendar to Month view.",
            "ui_actions": [{"type": "navigate_view", "view": "calendar", "calendar_mode": "month"}, {"type": "refresh_calendar"}],
            "rich_cards": [],
        }
    if key in ("calendar_next_month", "calendar_prev_month"):
        direction = "next" if key == "calendar_next_month" else "prev"
        return {
            "reply": f"Moved Calendar to the {'next' if direction == 'next' else 'previous'} month.",
            "ui_actions": [{"type": "navigate_view", "view": "calendar", "calendar_mode": "month"}, {"type": "calendar_nav", "direction": direction}],
            "rich_cards": [],
        }
    if key in ("next_page", "prev_page"):
        direction = "next" if key == "next_page" else "prev"
        return {
            "reply": f"Moved to the {'next' if direction == 'next' else 'previous'} page.",
            "ui_actions": [{"type": "paginate", "direction": direction}],
            "rich_cards": [],
        }
    if key == "back_to_list":
        return execute_close_email_tool()
    if key == "connect_gmail":
        return {"reply": "Opening Gmail connection flow.", "ui_actions": [{"type": "connect_gmail"}], "rich_cards": []}
    if key == "sync_gmail":
        return execute_sync_now_tool(account)
    if key == "disconnect_gmail":
        return execute_disconnect_gmail_tool(account)
    if key == "simulate_push":
        return execute_simulate_incoming_tool(account)
    if key == "toggle_theme":
        return {"reply": "Toggled color theme.", "ui_actions": [{"type": "toggle_theme"}], "rich_cards": []}
    if key == "clear_bin":
        return execute_clear_bin_tool(account)
    if key == "new_chat":
        return execute_new_chat_tool(account)
    if key == "star_email":
        return execute_star_open_email(account, open_email_id, starred=True)
    if key == "reply":
        return execute_reply_open_email(account, open_email_id)
    if key == "forward":
        return execute_forward_open_email(account, open_email_id)
    if key == "toggle_read":
        if not open_email_id:
            return {"reply": "Open an email first to toggle its read status.", "ui_actions": [], "rich_cards": []}
        em = EmailMessage.objects.filter(account=account, id=open_email_id).first()
        return execute_mark_read_open_email(account, open_email_id, is_read=not (em.is_read if em else False))
    if key == "mark_spam":
        return execute_move_open_email(account, open_email_id, "spam")
    if key == "move_to_bin":
        return execute_delete_email_tool(account, email_id=open_email_id, move_to_bin_only=True)
    if key in ("restore_from_bin", "restore_email"):
        return execute_restore_email_tool(account, email_id=open_email_id)
    if key == "discard_compose":
        return {"reply": "Discarded compose draft.", "ui_actions": [{"type": "discard_compose"}], "rich_cards": []}
    if key in ("toggle_cc", "toggle_bcc"):
        field = "cc" if key == "toggle_cc" else "bcc"
        return {
            "reply": f"Opened the {field.upper()} field in Compose.",
            "ui_actions": [{"type": "navigate_view", "view": "compose"}, {"type": "toggle_compose_field", "field": field}],
            "rich_cards": [],
        }
    if key == "save_draft":
        return {
            "reply": "Saved your current Compose draft to Drafts.",
            "ui_actions": [{"type": "save_current_draft"}],
            "rich_cards": [],
        }
    if key == "approve_detected_meeting":
        return {
            "reply": "Reviewing the detected meeting invitation.",
            "ui_actions": [{"type": "approve_detected_meeting"}],
            "rich_cards": [],
        }
    if key == "dismiss_detected_meeting":
        return {
            "reply": "Dismissed the detected meeting banner.",
            "ui_actions": [{"type": "dismiss_detected_meeting"}],
            "rich_cards": [],
        }
    if key == "open_add_event_form":
        return {
            "reply": "Opened the Add Event form on your Calendar.",
            "ui_actions": [{"type": "navigate_view", "view": "calendar"}, {"type": "open_calendar_event_form"}],
            "rich_cards": [],
        }
    if key == "cancel_add_event_form":
        return {
            "reply": "Closed the Calendar event form.",
            "ui_actions": [{"type": "close_calendar_event_form"}],
            "rich_cards": [],
        }
    if key == "open_edit_event_form":
        return execute_edit_calendar_event_tool(account, event_id=selected_event_id)
    if key == "inform_event_users":
        return execute_edit_calendar_event_tool(account, event_id=selected_event_id, inform_via_email=True)
    if key == "open_event_email":
        return {
            "reply": "Opening the related email for this event.",
            "ui_actions": [{"type": "open_event_email", "id": selected_event_id}],
            "rich_cards": [],
        }
    if key == "delete_event":
        return execute_delete_calendar_event_tool(account, event_id=selected_event_id)
    if key == "cancel_contact_edit":
        return {
            "reply": "Cancelled contact editing.",
            "ui_actions": [{"type": "cancel_contact_edit"}],
            "rich_cards": [],
        }
    return {"reply": f"Unknown UI button action '{action_name}'.", "ui_actions": [], "rich_cards": []}
