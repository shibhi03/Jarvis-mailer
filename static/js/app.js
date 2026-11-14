const state = {
  currentView: "inbox", // inbox | starred | sent | drafts | scheduled | spam | bin | contacts | detail | compose
  folder: "inbox",
  openEmailId: null,
  openEmail: null,
  composeDraftId: null,
  composeThreadId: null,
  composeInReplyTo: null,
  chatHistory: [],
  activeChatId: null,
  assistantChats: [],
  page: 1,
  pageSize: 25,
  totalPages: 1,
  meetingPage: 1,
  meetingTotalPages: 1,
  calendarMode: "list",
  calendarPage: 1,
  calendarTotalPages: 1,
  pendingMeeting: null,
  calendarMonth: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
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
    const data = JSON.parse(text);
    if (!resp.ok) {
      return { ...data, error: data.error || `Request failed (${resp.status})`, status_code: resp.status };
    }
    return data;
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
  } else if (state.currentView === "calendar") {
    pill.textContent = "Context: Calendar";
  } else if (state.currentView === "meetings") {
    pill.textContent = "Context: Meeting emails";
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
  } else if (viewName === "meetings" || viewName === "calendar") {
    document.getElementById(`view-${viewName}`).classList.add("active");
    document.getElementById(`nav-${viewName}`).classList.add("active");
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
  const params = new URLSearchParams({ folder: state.folder, page: String(state.page), per_page: String(state.pageSize) });
  if (state.filters.q) params.set("q", state.filters.q);
  if (state.filters.sender) params.set("sender", state.filters.sender);
  if (state.filters.is_read !== "") params.set("is_read", state.filters.is_read);
  if (state.filters.days) params.set("days", state.filters.days);

  const data = await apiFetch(`/api/emails/?${params.toString()}`);
  if (data.error) { showToast(`Couldn't load emails: ${data.error}`); return; }
  renderEmailList(data.emails || []);
  const pagination = data.pagination || { page: 1, total_pages: 1, total_count: (data.emails || []).length, has_next: false, has_previous: false };
  state.page = pagination.page;
  state.totalPages = pagination.total_pages;
  document.getElementById("list-count").textContent = `${pagination.total_count} email${pagination.total_count === 1 ? "" : "s"}`;
  document.getElementById("page-status").textContent = `Page ${pagination.page} of ${pagination.total_pages}`;
  document.getElementById("btn-page-prev").disabled = !pagination.has_previous;
  document.getElementById("btn-page-next").disabled = !pagination.has_next;
  updateUnreadBadge(data.unread_count || 0);
}

function localDateKey(value) {
  const date = value instanceof Date ? value : new Date(value);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

async function fetchMeetingEmails() {
  const data = await apiFetch(`/api/meetings/?page=${state.meetingPage}&tz_offset_minutes=${new Date().getTimezoneOffset()}`);
  if (data.error) { showToast(`Couldn't find meeting emails: ${data.error}`); return; }
  const meetings = data.meetings || [];
  const pagination = data.pagination || { page: 1, total_pages: 1, total_count: meetings.length, has_next: false, has_previous: false };
  state.meetingPage = pagination.page;
  state.meetingTotalPages = pagination.total_pages;
  document.getElementById("meeting-count").textContent = `${pagination.total_count} found`;
  document.getElementById("meeting-page-status").textContent = `Page ${pagination.page} of ${pagination.total_pages}`;
  document.getElementById("meeting-page-prev").disabled = !pagination.has_previous;
  document.getElementById("meeting-page-next").disabled = !pagination.has_next;
  const container = document.getElementById("meeting-email-list");
  if (!meetings.length) {
    container.innerHTML = `<div class="calendar-empty">No meeting emails with a recognizable date or time were found.</div>`;
    return;
  }
  container.innerHTML = meetings.map((meeting) => `
    <article class="meeting-email-card" data-email-id="${meeting.email_id}">
      <h3>${escapeHtml(meeting.title)}</h3>
      <div class="meeting-email-meta">${escapeHtml(meeting.sender_name || meeting.sender_email)} · ${meeting.has_date ? "Date found" : "Date inferred from email"}${meeting.has_time ? " · Time found" : " · No time found"}</div>
      <div><strong>${new Date(meeting.start_at).toLocaleString([], { dateStyle: "medium", timeStyle: meeting.all_day ? undefined : "short" })}${meeting.all_day ? " · all day" : ""}</strong></div>
      <div class="meeting-email-snippet">${escapeHtml(meeting.snippet)}</div>
      <div class="meeting-email-actions">
        ${meeting.already_added ? `<span class="muted">Already on calendar</span>` : new Date(meeting.start_at) <= new Date() ? `<span class="muted">Past event</span>` : `<label class="muted">Remind me <select class="select reminder-choice"><option value="0">At event time</option><option value="5">5 min before</option><option value="15" selected>15 min before</option><option value="30">30 min before</option><option value="60">1 hour before</option></select></label><button class="btn btn-sm btn-primary btn-add-calendar" type="button">Review &amp; add</button>`}
        <button class="btn btn-sm btn-outline btn-open-meeting-email" type="button">Open email</button>
      </div>
    </article>`).join("");
  container.querySelectorAll(".btn-open-meeting-email").forEach((button) => button.addEventListener("click", () => {
    const id = Number(button.closest("[data-email-id]").dataset.emailId);
    openEmailDetail(id);
  }));
  container.querySelectorAll(".btn-add-calendar").forEach((button) => button.addEventListener("click", async () => {
    const card = button.closest("[data-email-id]");
    const meeting = meetings.find((item) => item.email_id === Number(card.dataset.emailId));
    const reminderMinutes = Number(card.querySelector(".reminder-choice").value);
    button.disabled = true;
    const added = await addDetectedMeeting(meeting, reminderMinutes);
    if (!added) button.disabled = false;
  }));
}

async function addDetectedMeeting(meeting, reminderMinutes = 15) {
  const when = new Date(meeting.start_at).toLocaleString();
  const reminderText = reminderMinutes ? `${reminderMinutes} minutes before` : "at the event time";
  if (!window.confirm(`Please approve adding this meeting to your Jarvis calendar:\n\n${meeting.title}\n${when}\nReminder: ${reminderText}`)) return false;
  const result = await apiFetch("/api/calendar/events/", { method: "POST", body: JSON.stringify({
    confirmed: true, email_id: meeting.email_id, start_at: meeting.start_at,
    all_day: meeting.all_day, reminder_minutes: reminderMinutes,
  }) });
  if (!result.event) { showToast(result.error || "Couldn't add the meeting"); return false; }
  document.getElementById("meeting-approval-banner").classList.add("hidden");
  state.pendingMeeting = null;
  showToast("Meeting added to your calendar");
  if (state.currentView === "meetings") fetchMeetingEmails();
  if (state.currentView === "calendar") fetchCalendar();
  checkMeetingSuggestions();
  return true;
}

async function checkMeetingSuggestions() {
  const data = await apiFetch(`/api/meetings/?page=1&pending=1&tz_offset_minutes=${new Date().getTimezoneOffset()}`);
  if (data.error) return;
  let dismissed = [];
  try { dismissed = JSON.parse(localStorage.getItem("jarvis_dismissed_meetings") || "[]"); } catch { dismissed = []; }
  const meeting = (data.meetings || []).find((item) => !item.already_added && !dismissed.includes(item.email_id));
  const banner = document.getElementById("meeting-approval-banner");
  if (!meeting) { banner.classList.add("hidden"); state.pendingMeeting = null; return; }
  state.pendingMeeting = meeting;
  document.getElementById("meeting-approval-title").textContent = `Meeting mentioned in “${meeting.title}”`;
  document.getElementById("meeting-approval-time").textContent = `${new Date(meeting.start_at).toLocaleString()} · Review before adding to Calendar`;
  banner.classList.remove("hidden");
}

async function fetchCalendar() {
  const month = `${state.calendarMonth.getFullYear()}-${String(state.calendarMonth.getMonth() + 1).padStart(2, "0")}`;
  document.getElementById("calendar-month-title").textContent = state.calendarMonth.toLocaleDateString([], { month: "long", year: "numeric" });
  const isList = state.calendarMode === "list";
  document.getElementById("calendar-events-list").classList.toggle("hidden", !isList);
  document.getElementById("calendar-month-view").classList.toggle("hidden", isList);
  document.getElementById("calendar-month-navigation").classList.toggle("hidden", isList);
  document.getElementById("calendar-list-pagination").classList.toggle("hidden", !isList);
  document.getElementById("calendar-list-mode").className = `btn btn-sm ${isList ? "btn-primary" : "btn-outline"}`;
  document.getElementById("calendar-month-mode").className = `btn btn-sm ${isList ? "btn-outline" : "btn-primary"}`;
  const url = isList
    ? `/api/calendar/events/?view=list&page=${state.calendarPage}`
    : `/api/calendar/events/?month=${month}&tz_offset_minutes=${new Date().getTimezoneOffset()}`;
  const data = await apiFetch(url);
  if (data.error) { showToast(`Couldn't load calendar: ${data.error}`); return; }
  if (isList) {
    const page = data.pagination || { page: 1, total_pages: 1, total_count: (data.events || []).length, has_next: false, has_previous: false };
    state.calendarPage = page.page;
    state.calendarTotalPages = page.total_pages;
    document.getElementById("calendar-page-status").textContent = `Page ${page.page} of ${page.total_pages} · ${page.total_count} events`;
    document.getElementById("calendar-page-prev").disabled = !page.has_previous;
    document.getElementById("calendar-page-next").disabled = !page.has_next;
    renderCalendarList(data.events || []);
  } else renderCalendar(data.events || []);
}

function renderCalendarList(events) {
  const list = document.getElementById("calendar-events-list");
  if (!events.length) {
    list.innerHTML = `<div class="calendar-empty">No events yet. Add one here or review a meeting email.</div>`;
    return;
  }
  list.innerHTML = events.map((event) => `<button class="calendar-event-row" data-event-id="${event.id}" type="button"><span class="calendar-event-time">${new Date(event.start_at).toLocaleString([], { dateStyle: "medium", timeStyle: event.all_day ? undefined : "short" })}${event.all_day ? " · all day" : ""}</span><span><span class="calendar-event-title">${escapeHtml(event.title)}</span><span class="calendar-event-description">${event.source_email_id ? "From an email · Click to open" : "Personal event"}</span></span></button>`).join("");
  list.querySelectorAll(".calendar-event-row").forEach((button) => button.addEventListener("click", () => {
    const event = events.find((item) => item.id === Number(button.dataset.eventId));
    list.querySelectorAll(".calendar-event-row").forEach((row) => row.classList.toggle("selected", row === button));
    showCalendarEmail(event);
  }));
}

async function showCalendarEmail(event) {
  const panel = document.getElementById("calendar-email-panel");
  if (!event.source_email_id) {
    panel.innerHTML = `<h3>${escapeHtml(event.title)}</h3><div class="meeting-email-meta">${new Date(event.start_at).toLocaleString()}</div><div class="thread-body">${escapeHtml(event.description || "No notes for this event.")}</div><div class="meeting-email-meta">Reminder: ${event.reminder_minutes ? `${event.reminder_minutes} minutes before` : "at event time"}</div>`;
    return;
  }
  panel.innerHTML = `<div class="muted">Loading related email…</div>`;
  const data = await apiFetch(`/api/emails/${event.source_email_id}/`);
  if (!data.email) { panel.innerHTML = `<div class="calendar-empty">Couldn't load the related email.</div>`; return; }
  const email = data.email;
  const thread = data.thread?.length ? data.thread : [email];
  panel.innerHTML = `<h3>${escapeHtml(email.subject)}</h3>${thread.map((message) => `<div class="meeting-email-meta">${escapeHtml(message.sender_name)} &lt;${escapeHtml(message.sender_email)}&gt; · ${new Date(message.received_at).toLocaleString()}</div><div class="thread-body">${escapeHtml(message.body_text)}</div>`).join("")}<button id="calendar-open-full-email" class="btn btn-sm btn-outline" type="button">Open full email</button>`;
  document.getElementById("calendar-open-full-email").addEventListener("click", () => openEmailDetail(email.id));
}

function renderCalendar(events) {
  const grid = document.getElementById("calendar-grid");
  const first = new Date(state.calendarMonth.getFullYear(), state.calendarMonth.getMonth(), 1);
  const startOffset = (first.getDay() + 6) % 7;
  const gridStart = new Date(first.getFullYear(), first.getMonth(), 1 - startOffset);
  const eventsByDate = new Map();
  events.forEach((event) => {
    const key = localDateKey(event.start_at);
    if (!eventsByDate.has(key)) eventsByDate.set(key, []);
    eventsByDate.get(key).push(event);
  });
  grid.innerHTML = Array.from({ length: 42 }, (_, index) => {
    const day = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + index);
    const dayEvents = eventsByDate.get(localDateKey(day)) || [];
    return `<div class="calendar-day${day.getMonth() === state.calendarMonth.getMonth() ? "" : " outside-month"}${localDateKey(day) === localDateKey(new Date()) ? " today" : ""}"><div class="calendar-day-number">${day.getDate()}</div>${dayEvents.map((event) => `<button class="calendar-event-chip" data-event-id="${event.id}" type="button" title="${escapeHtml(event.title)} · ${new Date(event.start_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}">${event.all_day ? "All day" : new Date(event.start_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} ${escapeHtml(event.title)}</button>`).join("")}</div>`;
  }).join("");
  grid.querySelectorAll(".calendar-event-chip").forEach((button) => button.addEventListener("click", () => {
    const event = events.find((item) => item.id === Number(button.dataset.eventId));
    if (event) showCalendarEmail(event);
  }));
}

async function checkCalendarReminders() {
  const data = await apiFetch("/api/calendar/reminders/");
  for (const reminder of data.reminders || []) {
    showToast(`Reminder: ${reminder.title} · ${new Date(reminder.start_at).toLocaleString()}`);
    await apiFetch(`/api/calendar/reminders/${reminder.id}/ack/`, { method: "POST", body: "{}" });
  }
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

function syncComposeConfirmationCards() {
  const toValue = document.getElementById("compose-to").value;
  const subjectValue = document.getElementById("compose-subject").value;
  document.querySelectorAll(".send-confirmation-card").forEach((card) => {
    const to = card.querySelector(".confirm-to");
    const subject = card.querySelector(".confirm-subject");
    if (to) to.textContent = toValue;
    if (subject) subject.textContent = subjectValue;
  });
}

async function executeUiActions(actions = []) {
  for (const action of actions) {
    if (action.type === "navigate_view") {
      switchView(action.view);
      if (action.view === "contacts") fetchContacts();
      else if (action.view === "meetings") fetchMeetingEmails();
      else if (action.view === "calendar") fetchCalendar();
    } else if (action.type === "fill_compose") {
      switchView("compose");
      state.composeThreadId = action.thread_id || null;
      state.composeInReplyTo = action.in_reply_to || null;
      const modeTitle = action.mode === "reply" ? "Reply" : action.mode === "forward" ? "Forward" : "New Message";
      document.getElementById("compose-title").textContent = modeTitle;
      await animateFieldFill(document.getElementById("compose-to"), action.to || "");
      await animateFieldFill(document.getElementById("compose-subject"), action.subject || "");
      await animateFieldFill(document.getElementById("compose-body"), action.body || "");
      if (action.scheduled_at) {
        const when = new Date(action.scheduled_at);
        const local = new Date(when.getTime() - when.getTimezoneOffset() * 60000);
        document.getElementById("compose-schedule-at").value = local.toISOString().slice(0, 16);
      }
    } else if (action.type === "update_compose_draft") {
      switchView("compose");
      if (action.to !== undefined) document.getElementById("compose-to").value = action.to;
      await animateFieldFill(document.getElementById("compose-subject"), action.subject || "");
      await animateFieldFill(document.getElementById("compose-body"), action.body || "");
      syncComposeConfirmationCards();
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
      state.page = 1;
      fetchEmails();
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

function appendAssistantMessage(text, richCards = [], agentSteps = [], historical = false) {
  const container = document.getElementById("assistant-messages");
  const wrapper = document.createElement("div");
  wrapper.className = "msg msg-assistant";

  if (agentSteps && agentSteps.length) {
    const stepsEl = document.createElement("div");
    stepsEl.className = "agent-steps";
    stepsEl.innerHTML = agentSteps
      .map((s) => `<span class="agent-step-pill">${escapeHtml(s)}</span>`)
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
      if (historical) {
        c.className = "rich-card";
        c.innerHTML = `
          <div class="rich-card-title">Drafted email</div>
          <div class="rich-card-sub">To: ${escapeHtml(card.draft.to)}</div>
          <div><strong>${escapeHtml(card.draft.subject)}</strong></div>
          <div class="muted">Previous draft preview</div>
        `;
        wrapper.appendChild(c);
        continue;
      }
      c.className = "rich-card send-confirmation-card";
      c.innerHTML = `
        <div class="rich-card-title">Confirm Send</div>
        <div class="rich-card-sub">To: <span class="confirm-to">${escapeHtml(card.draft.to)}</span></div>
        <div><strong class="confirm-subject">${escapeHtml(card.draft.subject)}</strong></div>
        <div class="confirm-actions">
          <button class="btn btn-sm btn-primary btn-confirm-send">Confirm & Send</button>
          <button class="btn btn-sm btn-ghost btn-cancel-send">Cancel</button>
        </div>
      `;
      c.querySelector(".btn-confirm-send").addEventListener("click", async (e) => {
        e.target.disabled = true;
        const ok = await sendComposeDraft({
          to: document.getElementById("compose-to").value,
          subject: document.getElementById("compose-subject").value,
          body: document.getElementById("compose-body").value,
          thread_id: card.draft.thread_id,
          in_reply_to: card.draft.in_reply_to,
        });
        if (ok) c.querySelector(".confirm-actions").innerHTML = `<span class="muted">✓ Sent</span>`;
      });
      c.querySelector(".btn-cancel-send").addEventListener("click", () => {
        c.querySelector(".confirm-actions").innerHTML = `<span class="muted">Cancelled</span>`;
      });
      wrapper.appendChild(c);
    } else if (card.type === "schedule_confirmation" && card.draft) {
      const c = document.createElement("div");
      c.className = "rich-card schedule-confirmation-card";
      c.innerHTML = `<div class="rich-card-title">Confirm Schedule</div><div class="rich-card-sub">To: ${escapeHtml(card.draft.to)}</div><div><strong>${escapeHtml(card.draft.subject)}</strong></div><div class="muted">${escapeHtml(new Date(card.draft.scheduled_at).toLocaleString())}</div><div class="confirm-actions"><button class="btn btn-sm btn-primary">Confirm &amp; Schedule</button><button class="btn btn-sm btn-ghost">Cancel</button></div>`;
      const [confirmButton, cancelButton] = c.querySelectorAll("button");
      if (historical) {
        c.querySelector(".confirm-actions").textContent = "Previous schedule preview";
      } else {
        confirmButton.addEventListener("click", async () => {
          confirmButton.disabled = true;
          const dateValue = document.getElementById("compose-schedule-at").value;
          const res = await apiFetch("/api/emails/schedule/", { method: "POST", body: JSON.stringify({
            confirmed: true, draft_id: state.composeDraftId,
            to: document.getElementById("compose-to").value,
            subject: document.getElementById("compose-subject").value,
            body: document.getElementById("compose-body").value,
            scheduled_at: dateValue ? new Date(dateValue).toISOString() : "",
            thread_id: state.composeThreadId, in_reply_to: state.composeInReplyTo,
          }) });
          if (res.status === "scheduled") {
            c.querySelector(".confirm-actions").textContent = "✓ Scheduled";
            state.composeDraftId = null;
            showToast("Email scheduled");
            switchView("scheduled"); state.page = 1; fetchEmails();
          } else { confirmButton.disabled = false; showToast(res.error || "Failed to schedule email"); }
        });
        cancelButton.addEventListener("click", () => { c.querySelector(".confirm-actions").textContent = "Cancelled"; });
      }
      wrapper.appendChild(c);
    }
  }

  container.appendChild(wrapper);
  container.scrollTop = container.scrollHeight;
}

function showAssistantWelcome() {
  const container = document.getElementById("assistant-messages");
  container.replaceChildren();
  const welcome = document.createElement("div");
  welcome.className = "msg msg-assistant";
  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  bubble.innerHTML = "Hi! I'm <strong>Jarvis</strong>. Tell me what to do and I'll drive the mail UI for you — compose emails, filter your inbox, open threads, or reply to the email you're reading.";
  welcome.appendChild(bubble);
  container.appendChild(welcome);
}

function renderAssistantChatList() {
  const container = document.getElementById("assistant-chat-history");
  container.replaceChildren();
  state.assistantChats.forEach((chat) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `assistant-chat-item${String(chat.id) === String(state.activeChatId) ? " active" : ""}`;
    button.textContent = chat.title || "New chat";
    button.title = chat.last_message || chat.title || "New chat";
    button.addEventListener("click", () => openAssistantChat(chat.id));
    container.appendChild(button);
  });
}

async function refreshAssistantChatList() {
  const data = await apiFetch("/api/assistant/chats/");
  if (data.error) return data;
  state.assistantChats = data.chats || [];
  renderAssistantChatList();
  return data;
}

async function openAssistantChat(chatId) {
  const data = await apiFetch(`/api/assistant/chats/${chatId}/`);
  if (!data.chat) return;
  state.activeChatId = data.chat.id;
  localStorage.setItem("jarvis_active_chat", String(state.activeChatId));
  state.chatHistory = data.messages || [];
  const container = document.getElementById("assistant-messages");
  container.replaceChildren();
  if (!state.chatHistory.length) showAssistantWelcome();
  state.chatHistory.forEach((message) => {
    if (message.role === "user") appendUserMessage(message.content);
    else appendAssistantMessage(message.content, message.rich_cards || [], message.agent_steps || [], true);
  });
  renderAssistantChatList();
}

async function createAssistantChat() {
  const data = await apiFetch("/api/assistant/chats/new/", { method: "POST", body: "{}" });
  if (!data.chat) {
    showToast(data.error || "Couldn't create a new chat");
    return;
  }
  state.activeChatId = data.chat.id;
  state.chatHistory = [];
  localStorage.setItem("jarvis_active_chat", String(state.activeChatId));
  state.assistantChats = [data.chat, ...state.assistantChats.filter((chat) => String(chat.id) !== String(data.chat.id))];
  renderAssistantChatList();
  showAssistantWelcome();
}

async function loadAssistantChats() {
  const data = await refreshAssistantChatList();
  if (data?.error) {
    showToast(`Chat history couldn't load: ${data.error}`);
    return;
  }
  if (!state.assistantChats.length) {
    await createAssistantChat();
    return;
  }
  const savedId = localStorage.getItem("jarvis_active_chat");
  const selected = state.assistantChats.find((chat) => String(chat.id) === savedId) || state.assistantChats[0];
  await openAssistantChat(selected.id);
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
  if (!state.activeChatId) await createAssistantChat();
  appendUserMessage(message);
  const uiContext = {
    current_view: state.currentView,
    open_email_id: state.openEmailId,
    active_filters: state.filters,
    tz_offset_minutes: new Date().getTimezoneOffset(),
  };
  if (state.currentView === "compose") {
    uiContext.compose_draft = {
      to: document.getElementById("compose-to").value,
      subject: document.getElementById("compose-subject").value,
      body: document.getElementById("compose-body").value,
    };
  }
  const res = await apiFetch("/api/assistant/command/", {
    method: "POST",
    body: JSON.stringify({
      message,
      conversation_id: state.activeChatId,
      ui_context: uiContext,
    }),
  });
  if (res.error) {
    appendAssistantMessage(`I couldn't process that request: ${res.error}`);
    showToast(`Jarvis request failed: ${res.error}`);
    return;
  }
  await executeUiActions(res.ui_actions || []);
  const replyText = res.reply || "I couldn't determine an action for that request. Please rephrase it.";
  if (res.conversation_id) state.activeChatId = res.conversation_id;
  appendAssistantMessage(replyText, res.rich_cards || [], res.agent_steps || []);
  state.chatHistory.push(
    { role: "user", content: message, context: uiContext },
    { role: "assistant", content: replyText, rich_cards: res.rich_cards || [], agent_steps: res.agent_steps || [] },
  );
  await refreshAssistantChatList();
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
    checkMeetingSuggestions();
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
  checkMeetingSuggestions();
  initRealtimeSSE();
  loadAssistantChats();

  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.openEmailId = null;
      state.openEmail = null;
      if (btn.dataset.view === "contacts") {
        switchView("contacts");
        fetchContacts();
      } else if (btn.dataset.view === "meetings") {
        switchView("meetings");
        fetchMeetingEmails();
      } else if (btn.dataset.view === "calendar") {
        switchView("calendar");
        fetchCalendar();
      } else {
        state.page = 1;
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

  ["compose-to", "compose-subject"].forEach((id) =>
    document.getElementById(id).addEventListener("input", syncComposeConfirmationCards)
  );

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
    const recipient = document.getElementById("compose-to").value.trim();
    const subject = document.getElementById("compose-subject").value.trim();
    const body = document.getElementById("compose-body").value.trim();
    if (!recipient || !subject || !body) { showToast("Complete the recipient, subject, and message before scheduling"); return; }
    const when = new Date(scheduledAt);
    if (when <= new Date()) { showToast("Choose a future date and time"); return; }
    const confirmed = window.confirm(`Review your draft before scheduling:\n\nTo: ${recipient}\nSubject: ${subject}\nSend at: ${when.toLocaleString()}\n\nMessage:\n${body}\n\nSchedule this email?`);
    if (!confirmed) return;
    const res = await apiFetch("/api/emails/schedule/", {
      method: "POST",
      body: JSON.stringify({
        draft_id: state.composeDraftId,
        confirmed: true,
        to: document.getElementById("compose-to").value,
        subject: document.getElementById("compose-subject").value,
        body: document.getElementById("compose-body").value,
        scheduled_at: when.toISOString(),
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
    state.page = 1;
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
    state.page = 1;
    fetchEmails();
  });

  document.getElementById("btn-page-prev").addEventListener("click", () => { if (state.page > 1) { state.page -= 1; fetchEmails(); } });
  document.getElementById("btn-page-next").addEventListener("click", () => { if (state.page < state.totalPages) { state.page += 1; fetchEmails(); } });

  document.getElementById("assistant-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("assistant-input");
    const msg = input.value.trim();
    if (!msg) return;
    input.value = "";
    await sendAssistantCommand(msg);
  });

  document.getElementById("btn-new-chat").addEventListener("click", createAssistantChat);

  document.getElementById("meeting-approval-add").addEventListener("click", async () => {
    if (state.pendingMeeting) await addDetectedMeeting(state.pendingMeeting, 15);
  });
  document.getElementById("meeting-approval-dismiss").addEventListener("click", () => {
    if (state.pendingMeeting) {
      let dismissed = [];
      try { dismissed = JSON.parse(localStorage.getItem("jarvis_dismissed_meetings") || "[]"); } catch { dismissed = []; }
      dismissed.push(state.pendingMeeting.email_id);
      localStorage.setItem("jarvis_dismissed_meetings", JSON.stringify(dismissed.slice(-100)));
    }
    state.pendingMeeting = null;
    document.getElementById("meeting-approval-banner").classList.add("hidden");
    checkMeetingSuggestions();
  });
  document.getElementById("calendar-list-mode").addEventListener("click", () => { state.calendarMode = "list"; state.calendarPage = 1; fetchCalendar(); });
  document.getElementById("calendar-month-mode").addEventListener("click", () => { state.calendarMode = "month"; fetchCalendar(); });
  document.getElementById("calendar-add-event").addEventListener("click", () => {
    document.getElementById("calendar-add-form").classList.toggle("hidden");
  });
  document.getElementById("calendar-cancel-add").addEventListener("click", () => {
    document.getElementById("calendar-add-form").reset();
    document.getElementById("calendar-add-form").classList.add("hidden");
  });
  document.getElementById("calendar-add-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const title = document.getElementById("calendar-event-title").value.trim();
    const rawStart = document.getElementById("calendar-event-start").value;
    const startAt = new Date(rawStart);
    const reminderMinutes = Number(document.getElementById("calendar-event-reminder").value);
    if (!title || !rawStart || Number.isNaN(startAt.getTime())) { showToast("Add an event title and valid date/time"); return; }
    if (startAt <= new Date()) { showToast("Choose a future date and time"); return; }
    if (!window.confirm(`Add this event to your Jarvis calendar?\n\n${title}\n${startAt.toLocaleString()}\nReminder: ${reminderMinutes ? `${reminderMinutes} minutes before` : "at event time"}`)) return;
    const result = await apiFetch("/api/calendar/events/", { method: "POST", body: JSON.stringify({
      confirmed: true, title, start_at: startAt.toISOString(), reminder_minutes: reminderMinutes,
    }) });
    if (result.event) {
      showToast("Event added to your calendar");
      document.getElementById("calendar-add-form").reset();
      document.getElementById("calendar-add-form").classList.add("hidden");
      fetchCalendar();
    } else showToast(result.error || "Couldn't add event");
  });

  document.getElementById("calendar-prev").addEventListener("click", () => {
    state.calendarMonth = new Date(state.calendarMonth.getFullYear(), state.calendarMonth.getMonth() - 1, 1);
    fetchCalendar();
  });
  document.getElementById("calendar-next").addEventListener("click", () => {
    state.calendarMonth = new Date(state.calendarMonth.getFullYear(), state.calendarMonth.getMonth() + 1, 1);
    fetchCalendar();
  });
  document.getElementById("calendar-page-prev").addEventListener("click", () => {
    if (state.calendarPage > 1) { state.calendarPage -= 1; fetchCalendar(); }
  });
  document.getElementById("calendar-page-next").addEventListener("click", () => {
    if (state.calendarPage < state.calendarTotalPages) { state.calendarPage += 1; fetchCalendar(); }
  });
  document.getElementById("meeting-page-prev").addEventListener("click", () => {
    if (state.meetingPage > 1) { state.meetingPage -= 1; fetchMeetingEmails(); }
  });
  document.getElementById("meeting-page-next").addEventListener("click", () => {
    if (state.meetingPage < state.meetingTotalPages) { state.meetingPage += 1; fetchMeetingEmails(); }
  });
  checkCalendarReminders();
  setInterval(checkCalendarReminders, 60_000);

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
    checkMeetingSuggestions();
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
