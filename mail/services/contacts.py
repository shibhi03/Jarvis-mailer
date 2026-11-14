from typing import List, Optional, Tuple

from django.db.models import Q

from accounts.models import MailAccount
from mail.models import Contact, EmailMessage


def upsert_contact(
    account: MailAccount, name: str, email: str, notes: str = ""
) -> Optional[Contact]:
    clean_email = (email or "").strip().lower()
    if not clean_email or "@" not in clean_email:
        return None
    if clean_email == account.email.lower():
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
