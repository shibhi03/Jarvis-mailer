import json
import re
from typing import Tuple

from django.conf import settings


def _clean_pronouns(text: str) -> str:
    text = re.sub(r"\b(?:him|her|them)\b", "you", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:his|her|their)\b", "your", text, flags=re.IGNORECASE)
    return text.strip()


def _fallback_draft(recipient_name: str, intent: str) -> Tuple[str, str]:
    clean = intent.strip().rstrip(".")
    first_name = (recipient_name or "there").split("@")[0].split()[0].capitalize()
    informal = bool(re.search(r"\binformal\b|\bcasual\b|\bfriendly\b", clean, re.IGNORECASE))

    # Derive a concise subject
    subject = "Quick Note"
    m_for = re.search(r"\b(?:for|about|regarding)\s+(.+?)(?:\s+(?:tonight|today|tomorrow|this\s+\w+))?$", clean, re.IGNORECASE)
    if re.search(r"\bdinner\b", clean, re.IGNORECASE):
        subject = "Dinner Tonight" if "tonight" in clean.lower() else "Dinner Invitation"
    elif re.search(r"\blunch\b", clean, re.IGNORECASE):
        subject = "Lunch Invitation"
    elif re.search(r"\bcoffee\b", clean, re.IGNORECASE):
        subject = "Coffee Catch-Up"
    elif re.search(r"\b(?:how\s+(?:is|are)\s+(?:he|she|they|you)|how\s+(?:he|she|they)\s+is|how\s+you\s+are)\b", clean, re.IGNORECASE):
        subject = "Checking In"
    elif re.search(r"\bmeeting|sync|call\b", clean, re.IGNORECASE):
        subject = "Meeting Request"
    elif m_for:
        phrase = re.sub(r"^(?:the|a|an)\s+", "", m_for.group(1), flags=re.IGNORECASE).strip()
        subject = " ".join(phrase.split()[:5]).title()
    elif clean:
        words = [w for w in clean.split() if w.lower() not in ("asking", "telling", "saying", "to", "out", "for")]
        if words:
            subject = " ".join(words[:5]).title()

    # Derive a natural body
    body_core = _clean_pronouns(clean)
    m_ask = re.match(r"^asking\s+you\s+(?:out\s+)?(?:for\s+)?(.+)$", body_core, re.IGNORECASE)
    m_how = re.match(
        r"^asking\s+how\s+(?:(?:is|are)\s+)?(?:he|she|they|you)(?:\s+(?:is|are))?\s*$",
        body_core,
        re.IGNORECASE,
    ) or re.match(r"^asking\s+how\s+(?:he|she|they)\s+is\s*$", body_core, re.IGNORECASE)
    m_thank = re.match(r"^thanking\s+you\s+(?:for\s+)?(.+)$", body_core, re.IGNORECASE)
    m_rem = re.match(r"^reminding\s+you\s+(?:about|to\s+)?(.+)$", body_core, re.IGNORECASE)

    if m_how:
        sentence = "Just wanted to check in and see how you're doing."
    elif m_ask:
        topic = m_ask.group(1).strip()
        sentence = f"Would you like to go out for {topic}?" if "dinner" in topic.lower() or "lunch" in topic.lower() or "coffee" in topic.lower() else f"I wanted to ask you about {topic}."
    elif m_thank:
        sentence = f"Thank you so much for {m_thank.group(1).strip()}!"
    elif m_rem:
        sentence = f"Just a quick reminder regarding {m_rem.group(1).strip()}."
    elif body_core:
        sentence = body_core[0].upper() + body_core[1:] + "."
    else:
        sentence = "I hope you're doing well."

    signoff = "Talk soon," if informal else "Best regards,"
    body = f"Hi {first_name},\n\n{sentence}\n\n{signoff}"
    return subject, body


def _parse_draft_json(raw: str) -> dict:
    cleaned = (raw or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    return json.loads(cleaned)


def generate_subject_and_body(recipient_name: str, intent: str) -> Tuple[str, str]:
    """Draft using only the provider selected by AI_PROVIDER."""
    if settings.AI_PROVIDER == "openai":
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OpenAI is selected, but OPENAI_API_KEY is missing.")
        try:
            from openai import OpenAI

            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "Draft a concise, natural email from the user's intent. Return only JSON with keys subject and body."},
                    {"role": "user", "content": f"Recipient: {recipient_name}\nIntent: {intent}"},
                ],
                temperature=0.4,
            )
            data = _parse_draft_json(resp.choices[0].message.content or "{}")
            if data.get("subject") and data.get("body"):
                return data["subject"].strip(), data["body"].strip()
            raise ValueError("OpenAI returned an incomplete email draft.")
        except Exception as exc:
            raise RuntimeError(f"OpenAI email drafting failed: {exc}") from exc
    else:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("Gemini is selected, but GEMINI_API_KEY is missing.")
        try:
            from google import genai

            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            resp = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=(
                    "Write a concise, natural email based on the user's intent. "
                    "Return only JSON with string keys subject and body.\n"
                    f"Recipient: {recipient_name}\nIntent: {intent}"
                ),
            )
            data = _parse_draft_json(resp.text or "{}")
            if data.get("subject") and data.get("body"):
                return data["subject"].strip(), data["body"].strip()
            raise ValueError("Gemini returned an incomplete email draft.")
        except Exception as exc:
            raise RuntimeError(f"Gemini email drafting failed: {exc}") from exc


def revise_email_draft(subject: str, body: str, instruction: str) -> Tuple[str, str]:
    """Rewrite with only the provider selected by AI_PROVIDER."""
    prompt = (
        "Revise this email according to the user's editing instruction. Preserve the recipient, "
        "intent, and factual details. Do not send it. Return only JSON with string keys subject and body.\n"
        f"Current subject: {subject}\nCurrent body:\n{body}\n\n"
        f"Editing instruction: {instruction}"
    )
    if settings.AI_PROVIDER == "openai":
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OpenAI is selected, but OPENAI_API_KEY is missing.")
        try:
            from openai import OpenAI

            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "Revise the provided email and return only JSON with subject and body."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4,
            )
            revised = _parse_draft_json(response.choices[0].message.content or "{}")
            new_subject = str(revised.get("subject", "")).strip()
            new_body = str(revised.get("body", "")).strip()
            if new_subject and new_body:
                return new_subject, new_body
            raise ValueError("OpenAI returned an incomplete revision.")
        except Exception as exc:
            raise RuntimeError(f"OpenAI email revision failed: {exc}") from exc
    else:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("Gemini is selected, but GEMINI_API_KEY is missing.")
        try:
            from google import genai

            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            response = client.models.generate_content(model=settings.GEMINI_MODEL, contents=prompt)
            revised = _parse_draft_json(response.text or "{}")
            new_subject = str(revised.get("subject", "")).strip()
            new_body = str(revised.get("body", "")).strip()
            if new_subject and new_body:
                return new_subject, new_body
            raise ValueError("Gemini returned an incomplete revision.")
        except Exception as exc:
            raise RuntimeError(f"Gemini email revision failed: {exc}") from exc
