const timeout = AbortSignal.timeout(20_000);

function safeMessage(message, apiKey) {
  return String(message || "Unknown error")
    .replaceAll(apiKey || "\0", "[redacted]")
    .replaceAll(/\s+/g, " ")
    .slice(0, 320);
}

async function checkOpenAI() {
  const apiKey = process.env.OPENAI_API_KEY?.trim();
  const model = process.env.OPENAI_MODEL?.trim() || "gpt-4o-mini";
  if (!apiKey) {
    console.log("OpenAI: NOT CONFIGURED (OPENAI_API_KEY is empty)");
    return false;
  }

  try {
    const response = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      signal: timeout,
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model,
        messages: [{ role: "user", content: "Reply with exactly: OK" }],
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data.error?.message || data.message || response.statusText;
      console.log(`OpenAI: FAILED (${response.status}, ${model}) — ${safeMessage(detail, apiKey)}`);
      return false;
    }
    const generated = data.choices?.[0]?.message?.content;
    if (!generated) {
      console.log(`OpenAI: FAILED (${model}) — request succeeded but returned no text`);
      return false;
    }
    console.log(`OpenAI: OK (${model}) — authenticated and generated text`);
    return true;
  } catch (error) {
    const detail = [error.message, error.cause?.code, error.cause?.message].filter(Boolean).join(": ");
    console.log(`OpenAI: FAILED (${model}) — ${safeMessage(detail, apiKey)}`);
    return false;
  }
}

async function checkGemini() {
  const apiKey = process.env.GEMINI_API_KEY?.trim();
  const model = process.env.GEMINI_MODEL?.trim() || "gemini-3.8-flash";
  if (!apiKey) {
    console.log("Gemini: NOT CONFIGURED (GEMINI_API_KEY is empty)");
    return false;
  }

  try {
    const endpoint = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent`;
    const response = await fetch(endpoint, {
      method: "POST",
      signal: timeout,
      headers: {
        "x-goog-api-key": apiKey,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        contents: [{ parts: [{ text: "Reply with exactly: OK" }] }],
        generationConfig: { maxOutputTokens: 8 },
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data.error?.message || data.message || response.statusText;
      console.log(`Gemini: FAILED (${response.status}, ${model}) — ${safeMessage(detail, apiKey)}`);
      return false;
    }
    const generated = data.candidates?.[0]?.content?.parts?.map((part) => part.text || "").join("").trim();
    if (!generated) {
      console.log(`Gemini: FAILED (${model}) — request succeeded but returned no text`);
      return false;
    }
    console.log(`Gemini: OK (${model}) — authenticated and generated text`);
    return true;
  } catch (error) {
    const detail = [error.message, error.cause?.code, error.cause?.message].filter(Boolean).join(": ");
    console.log(`Gemini: FAILED (${model}) — ${safeMessage(detail, apiKey)}`);
    return false;
  }
}

const results = await Promise.all([checkOpenAI(), checkGemini()]);
if (!results.some(Boolean)) {
  console.log("No configured provider passed. Check the reported error, key, model, and account API access.");
  process.exitCode = 1;
} else {
  console.log("At least one provider is ready. Jarvis will prefer OpenAI and use Gemini as fallback.");
}
