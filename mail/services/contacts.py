import re
from email.utils import parseaddr
from typing import Any, List, Optional, Tuple

from django.db.models import Q

from accounts.models import MailAccount
from mail.models import Contact, EmailMessage

AUTOMATED_EMAIL_RE = re.compile(
    r"(no[-_.\s]?reply|do[-_.\s]?not[-_.\s]?reply|mailer[-_.]?daemon|"
    r"postmaster|auto[-_.]?reply|bounces?|notifications?|newsletter|automated)",
    re.IGNORECASE,
)


def is_automated_email(email: str, name: str = "") -> bool:
    local_part = (email or "").split("@")[0]
    return bool(AUTOMATED_EMAIL_RE.search(local_part) or AUTOMATED_EMAIL_RE.search(name or ""))


def upsert_contact(
    account: MailAccount, name: str, email: str, notes: str = ""
) -> Optional[Contact]:
    clean_email = (email or "").strip().lower()
    if not clean_email or "@" not in clean_email:
        return None
    if clean_email == account.email.lower():
        return None
    if is_automated_email(clean_email, name):
        return None

    clean_name = (name or "").strip() or clean_email.split("@")[0].replace(".", " ").title()
    contact, created = Contact.objects.get_or_create(
        account=account,
        email=clean_email,
        defaults={"name": clean_name, "notes": notes},
    )
    if not created and clean_name and contact.name == clean_email.split("@")[0]:
        contact.name = clean_name
        contact.save(update_fields=["name", "updated_at"])
    return contact


def sync_contacts_from_messages(account: MailAccount) -> int:
    """Populate Contact book from existing inbox/sent messages if not yet saved."""
    count = 0
    for msg in EmailMessage.objects.filter(account=account).only(
        "sender_name", "sender_email", "recipient_email"
    )[:100]:
        if msg.sender_email and msg.sender_email.lower() != account.email.lower():
            if upsert_contact(account, msg.sender_name, msg.sender_email):
                count += 1
    return count


def resolve_recipient(
    account: MailAccount, query: str
) -> Tuple[Optional[str], Optional[Contact], List[Contact]]:
    """Resolve a person's name or email to an email address via Contact book."""
    raw = (query or "").strip()
    if not raw:
        return None, None, []

    if "@" in raw and " " not in raw:
        return raw, None, []

    # Ensure contacts are synced from existing messages
    if not Contact.objects.filter(account=account).exists():
        sync_contacts_from_messages(account)

    exact = Contact.objects.filter(account=account, name__iexact=raw).first()
    if exact:
        return exact.email, exact, [exact]

    matches = list(
        Contact.objects.filter(
            Q(account=account) & (Q(name__icontains=raw) | Q(email__icontains=raw))
        )[:5]
    )
    if len(matches) == 1:
        return matches[0].email, matches[0], matches
    if len(matches) > 1:
        return matches[0].email, matches[0], matches

    # Fallback: check EmailMessage history directly
    msg = (
        EmailMessage.objects.filter(account=account)
        .filter(Q(sender_name__icontains=raw) | Q(sender_email__icontains=raw))
        .first()
    )
    if msg:
        c = upsert_contact(account, msg.sender_name, msg.sender_email)
        return msg.sender_email, c, ([c] if c else [])

    return None, None, []


def resolve_recipient_list(
    account: MailAccount, raw_recipients: Any
) -> Tuple[str, List[str], List[Contact]]:
    """Parse and resolve one or more recipient names/emails (comma, semicolon, or 'and' separated)."""
    if not raw_recipients:
        return "", [], []

    if isinstance(raw_recipients, (list, tuple)):
        items = [str(item).strip() for item in raw_recipients if str(item).strip()]
    else:
        items = [str(raw_recipients).strip()] if str(raw_recipients).strip() else []

    tokens: List[str] = []
    for item in items:
        for chunk in re.split(r"\s*[,;]\s*", item):
            part = chunk.strip()
            if not part:
                continue
            if "<" not in part and re.search(r"\s+\band\b\s+", part, re.IGNORECASE):
                exact = Contact.objects.filter(account=account, name__iexact=part).first()
                if exact:
                    tokens.append(part)
                else:
                    for sub in re.split(r"\s+\band\b\s+", part, flags=re.IGNORECASE):
                        if sub.strip():
                            tokens.append(sub.strip())
            else:
                tokens.append(part)

    resolved_emails: List[str] = []
    seen: set = set()
    unresolved: List[str] = []
    resolved_contacts: List[Contact] = []

    for token in tokens:
        if "<" in token and ">" in token:
            _, parsed_email = parseaddr(token)
            if parsed_email and "@" in parsed_email:
                key = parsed_email.strip().lower()
                if key not in seen:
                    seen.add(key)
                    resolved_emails.append(parsed_email.strip())
                contact = Contact.objects.filter(account=account, email__iexact=key).first()
                if contact and contact not in resolved_contacts:
                    resolved_contacts.append(contact)
                continue

        if "@" in token and " " not in token:
            clean = token.strip()
            key = clean.lower()
            if key not in seen:
                seen.add(key)
                resolved_emails.append(clean)
            contact = Contact.objects.filter(account=account, email__iexact=key).first()
            if contact and contact not in resolved_contacts:
                resolved_contacts.append(contact)
            continue

        email_addr, contact, _ = resolve_recipient(account, token)
        if email_addr:
            key = email_addr.strip().lower()
            if key not in seen:
                seen.add(key)
                resolved_emails.append(email_addr.strip())
            if contact and contact not in resolved_contacts:
                resolved_contacts.append(contact)
        else:
            unresolved.append(token)

    return ", ".join(resolved_emails), unresolved, resolved_contacts
