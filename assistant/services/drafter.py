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

    # Derive a concise subject
    subject = "Quick Note"
    m_for = re.search(r"\b(?:for|about|regarding)\s+(.+?)(?:\s+(?:tonight|today|tomorrow|this\s+\w+))?$", clean, re.IGNORECASE)
    if re.search(r"\bdinner\b", clean, re.IGNORECASE):
        subject = "Dinner Tonight" if "tonight" in clean.lower() else "Dinner Invitation"
    elif re.search(r"\blunch\b", clean, re.IGNORECASE):
        subject = "Lunch Invitation"
    elif re.search(r"\bcoffee\b", clean, re.IGNORECASE):
        subject = "Coffee Catch-Up"
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
    m_thank = re.match(r"^thanking\s+you\s+(?:for\s+)?(.+)$", body_core, re.IGNORECASE)
    m_rem = re.match(r"^reminding\s+you\s+(?:about|to\s+)?(.+)$", body_core, re.IGNORECASE)

    if m_ask:
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

    body = f"Hi {first_name},\n\n{sentence}\n\nBest regards,"
    return subject, body


def generate_subject_and_body(recipient_name: str, intent: str) -> Tuple[str, str]:
    """Use configured LLM (OpenAI/Gemini) to draft subject & body, with smart fallback."""
    if settings.OPENAI_API_KEY:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Draft a concise, natural email from the user's intent. "
                            "Return ONLY valid JSON with keys 'subject' and 'body'."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Recipient: {recipient_name}\nIntent: {intent}",
                    },
                ],
                temperature=0.4,
            )
            data = json.loads(resp.choices[0].message.content or "{}")
            if data.get("subject") and data.get("body"):
                return data["subject"].strip(), data["body"].strip()
        except Exception:
            pass

    if settings.GEMINI_API_KEY:
        try:
            from google import genai

            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            resp = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=(
                    "Draft a concise, natural email from the user's intent. "
                    "Return ONLY valid JSON with keys 'subject' and 'body'.\n"
                    f"Recipient: {recipient_name}\nIntent: {intent}"
                ),
            )
            raw = (resp.text or "").strip().strip("`")
            if raw.startswith("json"):
                raw = raw[4:].strip()
            data = json.loads(raw)
            if data.get("subject") and data.get("body"):
                return data["subject"].strip(), data["body"].strip()
        except Exception:
            pass

    return _fallback_draft(recipient_name, intent)
