const state = {
  currentView: "inbox", // inbox | starred | sent | drafts | scheduled | spam | bin | contacts | detail | compose
  folder: "inbox",
  openEmailId: null,
  openEmail: null,
  composeDraftId: null,
  composeThreadId: null,
  composeInReplyTo: null,
  chatHistory: [],
  filters: {
    q: "",
    sender: "",
    is_read: "",
    days: "",
  },
};

function getCookie(name) {
  const match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
  return match ? decodeURIComponent(match[2]) : "";
}

async function apiFetch(url, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (options.method && options.method !== "GET") {
    headers["X-CSRFToken"] = getCookie("csrftoken");
  }
  const resp = await fetch(url, { ...options, headers });
  const text = await resp.text();
  try {
    return JSON.parse(text);
  } catch {
    return { error: `Server error (${resp.status})` };
  }
}

function showToast(text) {
  const container = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = text;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function formatDate(iso) {
  const d = new Date(iso);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str || "";
  return div.innerHTML;
}

function updateContextPill() {
  const pill = document.getElementById("assistant-context-pill");
  if (state.currentView === "detail" && state.openEmail) {
    pill.textContent = `Context: Reading "${state.openEmail.subject.slice(0, 28)}"`;
  } else if (state.currentView === "compose") {
    pill.textContent = "Context: Composing email";
  } else {
    pill.textContent = `Context: ${state.folder === "sent" ? "Sent" : "Inbox"}`;
  }
}

function switchView(viewName) {
  state.currentView = viewName;
  document.querySelectorAll(".workspace-view").forEach((el) => el.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));

  if (viewName === "detail") {
    document.getElementById("view-detail").classList.add("active");
  } else if (viewName === "compose") {
    document.getElementById("view-compose").classList.add("active");
  } else if (viewName === "contacts") {
    document.getElementById("view-contacts").classList.add("active");
    document.getElementById("nav-contacts").classList.add("active");
  } else {
    const validFolders = ["inbox", "starred", "sent", "drafts", "scheduled", "spam", "bin"];
    state.folder = validFolders.includes(viewName) ? viewName : "inbox";
    document.getElementById("view-list").classList.add("active");
    const titles = {
      inbox: "Inbox",
      starred: "Starred",
      sent: "Sent",
      drafts: "Drafts",
      scheduled: "Scheduled",
      spam: "Spam",
      bin: "Bin",
    };
    document.getElementById("list-title").textContent = titles[state.folder] || "Inbox";
    document.querySelectorAll(".nav-item[data-folder]").forEach((b) => {
      b.classList.toggle("active", b.dataset.folder === state.folder);
    });
  }
  updateContextPill();
}

function renderEmailList(emails) {
  const listEl = document.getElementById("email-list");
  document.getElementById("list-count").textContent = `${emails.length} email${emails.length === 1 ? "" : "s"}`;

  if (!emails.length) {
    listEl.innerHTML = `<div class="rich-card">No emails match the current filters.</div>`;
    return;
  }

  listEl.innerHTML = emails
    .map((m) => {
      const displayPerson =
        ["sent", "drafts", "scheduled"].includes(state.folder)
          ? `To: ${m.recipient_email || "(No recipient)"}`
          : m.sender_name;
      const dateText =
        state.folder === "scheduled" && m.scheduled_at
          ? `⏰ ${formatDate(m.scheduled_at)}`
          : formatDate(m.received_at);
      return `
        <div class="email-row ${m.is_read ? "" : "unread"}" data-id="${m.id}">
          <span class="unread-dot"></span>
          <button class="star-btn ${m.is_starred ? "starred" : ""}" data-star-id="${m.id}" title="Star">
            ${m.is_starred ? "★" : "☆"}
          </button>
          <span class="email-sender">${escapeHtml(displayPerson)}</span>
          <span class="email-content">
            <span class="email-subject">${escapeHtml(m.subject)}</span>
            <span class="email-snippet">— ${escapeHtml(m.snippet)}</span>
          </span>
          <span class="email-date">${dateText}</span>
        </div>
      `;
    })
    .join("");

  listEl.querySelectorAll(".star-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const res = await apiFetch(`/api/emails/${btn.dataset.starId}/star/`, { method: "POST" });
      btn.classList.toggle("starred", res.is_starred);
      btn.textContent = res.is_starred ? "★" : "☆";
      if (state.folder === "starred" && !res.is_starred) fetchEmails();
    });
  });

  listEl.querySelectorAll(".email-row").forEach((row) => {
    row.addEventListener("click", () => openEmailDetail(Number(row.dataset.id)));
  });
}

function updateUnreadBadge(count) {
  const badge = document.getElementById("unread-badge");
  badge.textContent = count;
  badge.classList.toggle("hidden", !count);
}

async function fetchEmails() {
  const params = new URLSearchParams({ folder: state.folder });
  if (state.filters.q) params.set("q", state.filters.q);
  if (state.filters.sender) params.set("sender", state.filters.sender);
  if (state.filters.is_read !== "") params.set("is_read", state.filters.is_read);
  if (state.filters.days) params.set("days", state.filters.days);

  const data = await apiFetch(`/api/emails/?${params.toString()}`);
  renderEmailList(data.emails || []);
  updateUnreadBadge(data.unread_count || 0);
}

function renderDetailView(email, thread) {
  state.openEmailId = email.id;
  state.openEmail = email;
  switchView("detail");

  document.getElementById("detail-subject").textContent = email.subject;
  document.getElementById("btn-toggle-read").textContent = email.is_read ? "Mark Unread" : "Mark Read";
  document.getElementById("btn-star-detail").textContent = email.is_starred ? "★ Starred" : "☆ Star";
  document.getElementById("btn-spam").textContent = email.folder === "spam" ? "Not Spam" : "Spam";
  document.getElementById("btn-bin").textContent = email.folder === "bin" ? "Delete Forever" : "Bin";

  const container = document.getElementById("thread-container");
  const messages = thread && thread.length ? thread : [email];
  container.innerHTML = messages
    .map(
      (m) => `
      <div class="thread-card">
        <div class="thread-card-header">
          <div><strong>${escapeHtml(m.sender_name)}</strong> &lt;${escapeHtml(m.sender_email)}&gt; → ${escapeHtml(m.recipient_email)}</div>
          <div class="muted">${new Date(m.received_at).toLocaleString()}</div>
        </div>
        <div class="thread-body">${escapeHtml(m.body_text)}</div>
      </div>
    `
    )
    .join("");
}

async function openEmailDetail(emailId) {
  const data = await apiFetch(`/api/emails/${emailId}/`);
  if (data.email && data.email.folder === "drafts") {
    openCompose({
      draftId: data.email.id,
      to: data.email.recipient_email,
      subject: data.email.subject === "(No subject)" ? "" : data.email.subject,
      body: data.email.body_text,
      threadId: data.email.thread_id,
      inReplyTo: data.email.in_reply_to,
      title: "Edit Draft",
    });
    return;
  }
  renderDetailView(data.email, data.thread);
  updateUnreadBadge(data.unread_count || 0);
}

function openCompose({ draftId = null, to = "", subject = "", body = "", threadId = null, inReplyTo = null, title = "New Message" } = {}) {
  state.composeDraftId = draftId;
  state.composeThreadId = threadId;
  state.composeInReplyTo = inReplyTo;
  document.getElementById("compose-title").textContent = title;
  document.getElementById("compose-to").value = to;
  document.getElementById("compose-subject").value = subject;
  document.getElementById("compose-body").value = body;
  document.getElementById("compose-schedule-at").value = "";
  switchView("compose");
}

async function animateFieldFill(inputEl, value) {
  inputEl.classList.add("ai-filling");
  inputEl.value = "";
  const text = value || "";
  const step = Math.max(1, Math.ceil(text.length / 28));
  for (let i = 0; i <= text.length; i += step) {
    inputEl.value = text.slice(0, i);
    await new Promise((r) => setTimeout(r, 12));
  }
  inputEl.value = text;
  setTimeout(() => inputEl.classList.remove("ai-filling"), 500);
}

async function sendComposeDraft(draft) {
  const res = await apiFetch("/api/emails/send/", {
    method: "POST",
    body: JSON.stringify(draft),
  });
  if (res.status === "sent") {
    showToast(`Email sent to ${draft.to}`);
    state.composeThreadId = null;
    state.composeInReplyTo = null;
    switchView("sent");
    fetchEmails();
    return true;
  }
  showToast(res.error || "Failed to send email");
  return false;
}

async function executeUiActions(actions = []) {
  for (const action of actions) {
    if (action.type === "navigate_view") {
      switchView(action.view);
      if (action.view === "contacts") fetchContacts();
    } else if (action.type === "fill_compose") {
      switchView("compose");
      state.composeThreadId = action.thread_id || null;
      state.composeInReplyTo = action.in_reply_to || null;
      const modeTitle = action.mode === "reply" ? "Reply" : action.mode === "forward" ? "Forward" : "New Message";
      document.getElementById("compose-title").textContent = modeTitle;
      await animateFieldFill(document.getElementById("compose-to"), action.to || "");
      await animateFieldFill(document.getElementById("compose-subject"), action.subject || "");
      await animateFieldFill(document.getElementById("compose-body"), action.body || "");
    } else if (action.type === "apply_filters") {
      state.folder = action.folder || "inbox";
      state.filters.q = action.q || "";
      state.filters.sender = action.sender || "";
      state.filters.is_read = action.is_read === true ? "true" : action.is_read === false ? "false" : "";
      state.filters.days = action.days ? String(action.days) : "";

      document.getElementById("filter-q").value = state.filters.q;
      document.getElementById("filter-sender").value = state.filters.sender;
      document.getElementById("filter-read").value = state.filters.is_read;
      document.getElementById("filter-days").value = state.filters.days;

      switchView(state.folder);
      renderEmailList(action.emails || []);
    } else if (action.type === "open_email" && action.email) {
      renderDetailView(action.email, action.thread || [action.email]);
    } else if (action.type === "close_email") {
      state.openEmailId = null;
      state.openEmail = null;
      switchView(state.folder);
      fetchEmails();
    } else if (action.type === "refresh_contacts") {
      if (state.currentView === "contacts") fetchContacts();
    } else if (action.type === "update_star") {
      if (state.openEmail && state.openEmail.id === action.id) {
        state.openEmail.is_starred = action.is_starred;
        document.getElementById("btn-star-detail").textContent = action.is_starred ? "★ Starred" : "☆ Star";
      }
    } else if (action.type === "update_read") {
      if (state.openEmail && state.openEmail.id === action.id) {
        state.openEmail.is_read = action.is_read;
        document.getElementById("btn-toggle-read").textContent = action.is_read ? "Mark Unread" : "Mark Read";
      }
    } else if (action.type === "set_theme") {
      const theme = action.theme === "dark" ? "dark" : "light";
      document.documentElement.setAttribute("data-theme", theme);
      localStorage.setItem("jarvis_theme", theme);
    } else if (action.type === "submit_compose") {
      await sendComposeDraft({
        draft_id: state.composeDraftId,
        to: document.getElementById("compose-to").value,
        subject: document.getElementById("compose-subject").value,
        body: document.getElementById("compose-body").value,
        thread_id: state.composeThreadId,
        in_reply_to: state.composeInReplyTo,
      });
      state.composeDraftId = null;
    } else if (action.type === "discard_compose") {
      state.composeDraftId = null;
      switchView(state.folder);
      fetchEmails();
    }
  }
}

async function fetchContacts() {
  const data = await apiFetch("/api/contacts/");
  const listEl = document.getElementById("contacts-list");
  const contacts = data.contacts || [];
  if (!contacts.length) {
    listEl.innerHTML = `<div class="rich-card">No contacts saved yet. Add one above or tell Jarvis "Save contact Name email@example.com".</div>`;
    return;
  }
  listEl.innerHTML = contacts
    .map(
      (c) => `
      <div class="email-row" style="grid-template-columns: 180px 1fr auto;">
        <span class="email-sender"><strong>${escapeHtml(c.name)}</strong></span>
        <span class="muted">${escapeHtml(c.email)}</span>
        <span style="display:flex;gap:6px;">
          <button class="btn btn-sm btn-primary btn-email-contact" data-email="${escapeHtml(c.email)}">Email</button>
          <button class="btn btn-sm btn-ghost btn-del-contact" data-id="${c.id}">Delete</button>
        </span>
      </div>
    `
    )
    .join("");

  listEl.querySelectorAll(".btn-email-contact").forEach((btn) => {
    btn.addEventListener("click", () => openCompose({ to: btn.dataset.email }));
  });
  listEl.querySelectorAll(".btn-del-contact").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await apiFetch(`/api/contacts/${btn.dataset.id}/`, { method: "DELETE" });
      fetchContacts();
    });
  });
}

function appendAssistantMessage(text, richCards = [], agentSteps = []) {
  const container = document.getElementById("assistant-messages");
  const wrapper = document.createElement("div");
  wrapper.className = "msg msg-assistant";

  if (agentSteps && agentSteps.length) {
    const stepsEl = document.createElement("div");
    stepsEl.className = "agent-steps";
    stepsEl.innerHTML = agentSteps
      .map((s) => `<span class="agent-step-pill">✓ ${escapeHtml(s)}</span>`)
      .join("");
    wrapper.appendChild(stepsEl);
  }

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  bubble.innerHTML = escapeHtml(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\n/g, "<br/>");
  wrapper.appendChild(bubble);

  for (const card of richCards) {
    if (card.type === "email_preview" && card.email) {
      const c = document.createElement("div");
      c.className = "rich-card clickable";
      c.innerHTML = `
        <div class="rich-card-title">${escapeHtml(card.email.subject)}</div>
        <div class="rich-card-sub">${escapeHtml(card.email.sender_name)} · ${formatDate(card.email.received_at)}</div>
        <div>${escapeHtml(card.email.snippet)}</div>
      `;
      c.addEventListener("click", () => openEmailDetail(card.email.id));
      wrapper.appendChild(c);
    } else if (card.type === "send_confirmation" && card.draft) {
      const c = document.createElement("div");
      c.className = "rich-card";
      c.innerHTML = `
        <div class="rich-card-title">Confirm Send</div>
        <div class="rich-card-sub">To: ${escapeHtml(card.draft.to)}</div>
        <div><strong>${escapeHtml(card.draft.subject)}</strong></div>
        <div class="confirm-actions">
          <button class="btn btn-sm btn-primary btn-confirm-send">Confirm & Send</button>
          <button class="btn btn-sm btn-ghost btn-cancel-send">Cancel</button>
        </div>
      `;
      c.querySelector(".btn-confirm-send").addEventListener("click", async (e) => {
        e.target.disabled = true;
        const ok = await sendComposeDraft({
          to: document.getElementById("compose-to").value || card.draft.to,
          subject: document.getElementById("compose-subject").value || card.draft.subject,
          body: document.getElementById("compose-body").value || card.draft.body,
          thread_id: card.draft.thread_id,
          in_reply_to: card.draft.in_reply_to,
        });
        if (ok) c.querySelector(".confirm-actions").innerHTML = `<span class="muted">✓ Sent</span>`;
      });
      c.querySelector(".btn-cancel-send").addEventListener("click", () => {
        c.querySelector(".confirm-actions").innerHTML = `<span class="muted">Cancelled</span>`;
      });
      wrapper.appendChild(c);
    }
  }

  container.appendChild(wrapper);
  container.scrollTop = container.scrollHeight;
}

function appendUserMessage(text) {
  const container = document.getElementById("assistant-messages");
  const wrapper = document.createElement("div");
  wrapper.className = "msg msg-user";
  wrapper.innerHTML = `<div class="msg-bubble">${escapeHtml(text)}</div>`;
  container.appendChild(wrapper);
  container.scrollTop = container.scrollHeight;
}

async function sendAssistantCommand(message) {
  appendUserMessage(message);
  const res = await apiFetch("/api/assistant/command/", {
    method: "POST",
    body: JSON.stringify({
      message,
      history: state.chatHistory.slice(-6),
      ui_context: {
        current_view: state.currentView,
        open_email_id: state.openEmailId,
        active_filters: state.filters,
        tz_offset_minutes: new Date().getTimezoneOffset(),
      },
    }),
  });
  await executeUiActions(res.ui_actions || []);
  const replyText = res.reply || "Done.";
  appendAssistantMessage(replyText, res.rich_cards || [], res.agent_steps || []);
  state.chatHistory.push({ role: "user", content: message }, { role: "assistant", content: replyText });
}

async function loadAuthStatus() {
  const status = await apiFetch("/auth/status/");
  document.getElementById("account-email").textContent = status.email;
  document.getElementById("account-provider").textContent =
    status.provider === "gmail" ? "Gmail Connected" : "Demo Mode (Local)";

  const connectBtn = document.getElementById("btn-connect-gmail");
  const syncBtn = document.getElementById("btn-sync-gmail");
  const disconnectBtn = document.getElementById("btn-disconnect-gmail");
  if (status.provider === "gmail") {
    connectBtn.classList.add("hidden");
    syncBtn.classList.remove("hidden");
    disconnectBtn.classList.remove("hidden");
  } else if (status.oauth_configured) {
    connectBtn.classList.remove("hidden");
    syncBtn.classList.add("hidden");
    disconnectBtn.classList.add("hidden");
  } else {
    connectBtn.classList.add("hidden");
    syncBtn.classList.add("hidden");
    disconnectBtn.classList.add("hidden");
  }
}

function initRealtimeSSE() {
  const es = new EventSource("/api/mail/stream/");
  es.addEventListener("new_email", (evt) => {
    const email = JSON.parse(evt.data);
    showToast(`New email from ${email.sender_name}: ${email.subject}`);
    if (state.currentView === "inbox") {
      fetchEmails();
    }
  });
}

function initTheme() {
  const saved = localStorage.getItem("jarvis_theme") || "light";
  document.documentElement.setAttribute("data-theme", saved);
}

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  loadAuthStatus();
  fetchEmails();
  initRealtimeSSE();

  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.openEmailId = null;
      state.openEmail = null;
      if (btn.dataset.view === "contacts") {
        switchView("contacts");
        fetchContacts();
      } else {
        switchView(btn.dataset.folder);
        fetchEmails();
      }
    });
  });

  document.getElementById("contact-add-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("contact-name").value.trim();
    const email = document.getElementById("contact-email").value.trim();
    const res = await apiFetch("/api/contacts/", {
      method: "POST",
      body: JSON.stringify({ name, email }),
    });
    if (res.contact) {
      showToast(`Saved ${res.contact.name}`);
      document.getElementById("contact-name").value = "";
      document.getElementById("contact-email").value = "";
      fetchContacts();
    } else {
      showToast(res.error || "Failed to save contact");
    }
  });

  document.getElementById("btn-compose").addEventListener("click", () => openCompose());
  document.getElementById("btn-discard-compose").addEventListener("click", () => {
    switchView(state.folder);
    fetchEmails();
  });

  document.getElementById("btn-back-list").addEventListener("click", () => {
    state.openEmailId = null;
    state.openEmail = null;
    switchView(state.folder);
    fetchEmails();
  });

  document.getElementById("btn-reply").addEventListener("click", () => {
    if (!state.openEmail) return;
    const e = state.openEmail;
    openCompose({
      to: e.folder === "sent" ? e.recipient_email : e.sender_email,
      subject: e.subject.toLowerCase().startsWith("re:") ? e.subject : `Re: ${e.subject}`,
      body: `\n\n--- On ${new Date(e.received_at).toLocaleString()}, ${e.sender_name} wrote ---\n${e.body_text}`,
      threadId: e.thread_id,
      inReplyTo: e.provider_message_id,
      title: "Reply",
    });
  });

  document.getElementById("btn-forward").addEventListener("click", () => {
    if (!state.openEmail) return;
    const e = state.openEmail;
    openCompose({
      to: "",
      subject: e.subject.toLowerCase().startsWith("fwd:") ? e.subject : `Fwd: ${e.subject}`,
      body: `\n\n---------- Forwarded message ---------\nFrom: ${e.sender_name} <${e.sender_email}>\nSubject: ${e.subject}\n\n${e.body_text}`,
      title: "Forward",
    });
  });

  document.getElementById("btn-toggle-read").addEventListener("click", async () => {
    if (!state.openEmailId) return;
    const res = await apiFetch(`/api/emails/${state.openEmailId}/toggle-read/`, { method: "POST" });
    if (state.openEmail) state.openEmail.is_read = res.is_read;
    document.getElementById("btn-toggle-read").textContent = res.is_read ? "Mark Unread" : "Mark Read";
    updateUnreadBadge(res.unread_count || 0);
  });

  document.getElementById("btn-star-detail").addEventListener("click", async () => {
    if (!state.openEmailId) return;
    const res = await apiFetch(`/api/emails/${state.openEmailId}/star/`, { method: "POST" });
    if (state.openEmail) state.openEmail.is_starred = res.is_starred;
    document.getElementById("btn-star-detail").textContent = res.is_starred ? "★ Starred" : "☆ Star";
  });

  document.getElementById("btn-spam").addEventListener("click", async () => {
    if (!state.openEmailId || !state.openEmail) return;
    const target = state.openEmail.folder === "spam" ? "inbox" : "spam";
    await apiFetch(`/api/emails/${state.openEmailId}/move/`, {
      method: "POST",
      body: JSON.stringify({ folder: target }),
    });
    showToast(target === "spam" ? "Moved to Spam" : "Moved to Inbox");
    switchView(state.folder);
    fetchEmails();
  });

  document.getElementById("btn-bin").addEventListener("click", async () => {
    if (!state.openEmailId || !state.openEmail) return;
    const target = state.openEmail.folder === "bin" ? "delete" : "bin";
    await apiFetch(`/api/emails/${state.openEmailId}/move/`, {
      method: "POST",
      body: JSON.stringify({ folder: target }),
    });
    showToast(target === "delete" ? "Deleted permanently" : "Moved to Bin");
    switchView(state.folder);
    fetchEmails();
  });

  document.getElementById("compose-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    await sendComposeDraft({
      draft_id: state.composeDraftId,
      to: document.getElementById("compose-to").value,
      subject: document.getElementById("compose-subject").value,
      body: document.getElementById("compose-body").value,
      thread_id: state.composeThreadId,
      in_reply_to: state.composeInReplyTo,
    });
    state.composeDraftId = null;
  });

  document.getElementById("btn-save-draft").addEventListener("click", async () => {
    const res = await apiFetch("/api/emails/draft/", {
      method: "POST",
      body: JSON.stringify({
        draft_id: state.composeDraftId,
        to: document.getElementById("compose-to").value,
        subject: document.getElementById("compose-subject").value,
        body: document.getElementById("compose-body").value,
        thread_id: state.composeThreadId,
        in_reply_to: state.composeInReplyTo,
      }),
    });
    if (res.status === "saved") {
      state.composeDraftId = null;
      showToast("Draft saved");
      switchView("drafts");
      fetchEmails();
    } else {
      showToast(res.error || "Failed to save draft");
    }
  });

  document.getElementById("btn-schedule-send").addEventListener("click", async () => {
    const scheduledAt = document.getElementById("compose-schedule-at").value;
    if (!scheduledAt) {
      showToast("Please pick a date and time to schedule send");
      return;
    }
    const res = await apiFetch("/api/emails/schedule/", {
      method: "POST",
      body: JSON.stringify({
        draft_id: state.composeDraftId,
        to: document.getElementById("compose-to").value,
        subject: document.getElementById("compose-subject").value,
        body: document.getElementById("compose-body").value,
        scheduled_at: scheduledAt,
        thread_id: state.composeThreadId,
        in_reply_to: state.composeInReplyTo,
      }),
    });
    if (res.status === "scheduled") {
      state.composeDraftId = null;
      showToast("Email scheduled");
      switchView("scheduled");
      fetchEmails();
    } else {
      showToast(res.error || "Failed to schedule email");
    }
  });

  const syncFilters = () => {
    state.filters.q = document.getElementById("filter-q").value;
    state.filters.sender = document.getElementById("filter-sender").value;
    state.filters.is_read = document.getElementById("filter-read").value;
    state.filters.days = document.getElementById("filter-days").value;
    if (state.currentView !== "inbox" && state.currentView !== "sent") {
      switchView(state.folder);
    }
    fetchEmails();
  };

  ["filter-q", "filter-sender"].forEach((id) =>
    document.getElementById(id).addEventListener("input", syncFilters)
  );
  ["filter-read", "filter-days"].forEach((id) =>
    document.getElementById(id).addEventListener("change", syncFilters)
  );

  document.getElementById("btn-clear-filters").addEventListener("click", () => {
    state.filters = { q: "", sender: "", is_read: "", days: "" };
    document.getElementById("filter-q").value = "";
    document.getElementById("filter-sender").value = "";
    document.getElementById("filter-read").value = "";
    document.getElementById("filter-days").value = "";
    fetchEmails();
  });

  document.getElementById("assistant-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("assistant-input");
    const msg = input.value.trim();
    if (!msg) return;
    input.value = "";
    await sendAssistantCommand(msg);
  });

  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => sendAssistantCommand(chip.dataset.prompt));
  });

  document.getElementById("btn-simulate-push").addEventListener("click", async () => {
    await apiFetch("/api/mail/simulate-incoming/", { method: "POST", body: "{}" });
  });

  document.getElementById("btn-sync-gmail").addEventListener("click", async () => {
    const res = await apiFetch("/api/emails/sync/", { method: "POST" });
    showToast(`Synced ${res.added || 0} new email(s)`);
    fetchEmails();
  });

  document.getElementById("btn-disconnect-gmail").addEventListener("click", async () => {
    await apiFetch("/auth/logout/", { method: "POST" });
    loadAuthStatus();
    fetchEmails();
  });

  document.getElementById("btn-theme-toggle").addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("jarvis_theme", next);
  });
});
