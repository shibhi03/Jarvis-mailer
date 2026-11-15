const state = {
  currentView: "inbox", // inbox | starred | sent | drafts | scheduled | spam | bin | contacts | detail | compose
  folder: "inbox",
  openEmailId: null,
  openEmail: null,
  composeDraftId: null,
  composeCalendarEventId: null,
  composeThreadId: null,
  composeInReplyTo: null,
  composeRecipients: {
    to: [],
    cc: [],
    bcc: [],
  },
  cachedContacts: [],
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
  selectedCalendarEventId: null,
  lastCalendarEvents: [],
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

function getCsrfToken() {
  return (
    getCookie("csrftoken") ||
    document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") ||
    document.querySelector('input[name="csrfmiddlewaretoken"]')?.value ||
    ""
  );
}

async function apiFetch(url, options = {}) {
  const fetchOptions = { ...options };
  const method = (fetchOptions.method || "GET").toUpperCase();
  const headers = { ...(fetchOptions.headers || {}) };
  if (!(fetchOptions.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  if (
    fetchOptions.body &&
    typeof fetchOptions.body === "object" &&
    !(fetchOptions.body instanceof FormData)
  ) {
    fetchOptions.body = JSON.stringify(fetchOptions.body);
  }
  if (
    method !== "GET" &&
    method !== "HEAD" &&
    (fetchOptions.body === undefined || fetchOptions.body === null || fetchOptions.body === "")
  ) {
    fetchOptions.body = "{}";
  }
  if (method !== "GET" && method !== "HEAD") {
    const csrfToken = getCsrfToken();
    if (csrfToken) {
      headers["X-CSRFToken"] = csrfToken;
    }
  }
  const resp = await fetch(url, { credentials: "same-origin", ...fetchOptions, headers });
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
  } else if (state.currentView === "contacts") {
    pill.textContent = "Context: Contacts";
  } else {
    const folderLabel = state.folder ? state.folder.charAt(0).toUpperCase() + state.folder.slice(1) : "Inbox";
    pill.textContent = `Context: ${folderLabel}`;
  }
  const spotlightPill = document.getElementById("jarvis-spotlight-context");
  if (spotlightPill) spotlightPill.textContent = pill.textContent;
}

function switchView(viewName) {
  state.currentView = viewName;
  document.querySelectorAll(".workspace-view").forEach((el) => el.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
  const clearBinBtn = document.getElementById("btn-clear-bin");
  if (clearBinBtn) clearBinBtn.classList.add("hidden");

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
    if (clearBinBtn) clearBinBtn.classList.toggle("hidden", state.folder !== "bin");
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
      const folder = m.folder || state.folder;
      const isBin = folder === "bin";
      const permDelete = ["bin", "drafts", "scheduled"].includes(folder);
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
          <span class="email-row-actions" style="display:flex;gap:4px;align-items:center;">
            ${isBin ? `<button class="btn btn-sm btn-outline btn-restore-email" data-restore-id="${m.id}" title="Restore to Inbox" type="button">↩ Restore</button>` : ""}
            <button class="btn btn-sm btn-ghost btn-delete-email" data-delete-id="${m.id}" data-folder="${escapeHtml(folder)}" title="${permDelete ? "Delete permanently" : "Move to Bin"}" type="button">🗑</button>
          </span>
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

  listEl.querySelectorAll(".btn-restore-email").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const res = await apiFetch(`/api/emails/${btn.dataset.restoreId}/move/`, {
        method: "POST",
        body: JSON.stringify({ folder: "restore" }),
      });
      if (res.error) {
        showToast(res.error);
        return;
      }
      showToast("Restored to Inbox");
      fetchEmails();
    });
  });

  listEl.querySelectorAll(".btn-delete-email").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = btn.dataset.deleteId;
      const folder = btn.dataset.folder || state.folder;
      const target = ["bin", "drafts", "scheduled"].includes(folder) ? "delete" : "bin";
      const res = await apiFetch(`/api/emails/${id}/move/`, {
        method: "POST",
        body: JSON.stringify({ folder: target }),
      });
      if (res.error) {
        showToast(res.error);
        return;
      }
      showToast(target === "delete" ? "Deleted permanently" : "Moved to Bin");
      fetchEmails();
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
  const events = data.events || [];
  state.lastCalendarEvents = events;
  if (isList) {
    const page = data.pagination || { page: 1, total_pages: 1, total_count: events.length, has_next: false, has_previous: false };
    state.calendarPage = page.page;
    state.calendarTotalPages = page.total_pages;
    document.getElementById("calendar-page-status").textContent = `Page ${page.page} of ${page.total_pages} · ${page.total_count} events`;
    document.getElementById("calendar-page-prev").disabled = !page.has_previous;
    document.getElementById("calendar-page-next").disabled = !page.has_next;
    renderCalendarList(events);
  } else renderCalendar(events);
}

function toAddressList(val) {
  if (Array.isArray(val)) return val.map((item) => String(item).trim()).filter(Boolean);
  if (!val) return [];
  return String(val).split(/[,;\n]+/).map((item) => item.trim()).filter(Boolean);
}

function resetCalendarForm() {
  const form = document.getElementById("calendar-add-form");
  if (form) form.reset();
  const editIdEl = document.getElementById("calendar-event-edit-id");
  if (editIdEl) editIdEl.value = "";
  const submitBtn = document.getElementById("calendar-submit-btn");
  if (submitBtn) submitBtn.textContent = "Save Event";
  const informLabel = document.getElementById("calendar-event-inform-label");
  if (informLabel) informLabel.textContent = "Inform people by drafting an email after adding this event";
}

function openCalendarEventEditor(event) {
  if (!event) return;
  if (event.is_user_created === false) {
    showToast("Events created from received emails cannot be edited.");
    return;
  }
  state.selectedCalendarEventId = event.id;
  const form = document.getElementById("calendar-add-form");
  if (!form) return;
  form.classList.remove("hidden");
  const editIdEl = document.getElementById("calendar-event-edit-id");
  if (editIdEl) editIdEl.value = String(event.id);
  document.getElementById("calendar-event-title").value = event.title || "";
  const startEl = document.getElementById("calendar-event-start");
  if (startEl && event.start_at) {
    const dt = new Date(event.start_at);
    if (!Number.isNaN(dt.getTime())) {
      const local = new Date(dt.getTime() - dt.getTimezoneOffset() * 60000);
      startEl.value = local.toISOString().slice(0, 16);
    }
  }
  document.getElementById("calendar-event-reminder").value = String(event.reminder_minutes ?? 15);
  const descEl = document.getElementById("calendar-event-description");
  if (descEl) descEl.value = event.description || "";
  const attendeesEl = document.getElementById("calendar-event-attendees");
  const existingRecipients = toAddressList(event.sent_to?.length ? event.sent_to : event.attendees);
  if (attendeesEl) attendeesEl.value = existingRecipients.join(", ");
  const informEl = document.getElementById("calendar-event-inform");
  if (informEl) informEl.checked = false;
  const informLabel = document.getElementById("calendar-event-inform-label");
  if (informLabel) informLabel.textContent = "Inform people about this update by drafting an email";
  const submitBtn = document.getElementById("calendar-submit-btn");
  if (submitBtn) submitBtn.textContent = "Update Event";
  document.getElementById("calendar-event-title")?.focus();
}

function buildEventInformDraft(event, isUpdate = false) {
  const recipients = toAddressList(event.sent_to?.length ? event.sent_to : event.attendees);
  const whenStr = new Date(event.start_at).toLocaleString();
  const detailsLine = event.description ? `\nDetails: ${event.description}\n` : "";
  const subject = isUpdate ? `Updated Event: ${event.title}` : `Invitation: ${event.title}`;
  const body = isUpdate
    ? `Hi,\n\nPlease note an update to the event "${event.title}".\nWhen: ${whenStr}\n${detailsLine}\nLet me know if you have any questions.\n\nBest regards,`
    : `Hi,\n\nI've scheduled "${event.title}" for ${whenStr}.\n${detailsLine}\nPlease let me know if this works for you.\n\nBest regards,`;
  const draft = {
    to: recipients.join(", "),
    cc: "",
    bcc: "",
    subject,
    body,
    calendar_event_id: event.id,
    title: isUpdate ? "Inform Users about Event Update" : "Inform Users about Event",
  };
  openCompose({
    calendarEventId: event.id,
    to: draft.to,
    subject: draft.subject,
    body: draft.body,
    title: draft.title,
  });
  appendAssistantMessage(
    isUpdate
      ? `Prepared an update email draft for **${event.title}**. Review recipients and confirm when ready to send.`
      : `Prepared an email draft for **${event.title}**. Add recipients if needed and confirm to send.`,
    [{ type: "send_confirmation", draft }],
  );
}

function renderCalendarList(events) {
  const list = document.getElementById("calendar-events-list");
  if (!events.length) {
    list.innerHTML = `<div class="calendar-empty">No events yet. Add one here or review a meeting email.</div>`;
    return;
  }
  list.innerHTML = events.map((event) => {
    const sentTo = toAddressList(event.sent_to);
    const attendees = toAddressList(event.attendees);
    let subtitle = "Personal event · Click to manage";
    if (event.email_direction === "received") {
      subtitle = "From received email · Click to view email";
    } else if (sentTo.length) {
      subtitle = `Email sent to ${sentTo.join(", ")} · Click to view or edit`;
    } else if (attendees.length) {
      subtitle = `Participants: ${attendees.join(", ")} · Click to manage`;
    }
    const isSelected = state.selectedCalendarEventId === event.id ? " selected" : "";
    return `<button class="calendar-event-row${isSelected}" data-event-id="${event.id}" type="button"><span class="calendar-event-time">${new Date(event.start_at).toLocaleString([], { dateStyle: "medium", timeStyle: event.all_day ? undefined : "short" })}${event.all_day ? " · all day" : ""}</span><span><span class="calendar-event-title">${escapeHtml(event.title)}</span><span class="calendar-event-description">${escapeHtml(subtitle)}</span></span></button>`;
  }).join("");
  list.querySelectorAll(".calendar-event-row").forEach((button) => button.addEventListener("click", () => {
    const event = events.find((item) => item.id === Number(button.dataset.eventId));
    list.querySelectorAll(".calendar-event-row").forEach((row) => row.classList.toggle("selected", row === button));
    if (event) showCalendarEmail(event);
  }));
}

function renderCalendarSentEmailsHtml(event) {
  const sentTo = toAddressList(event.sent_to);
  const sentEmails = Array.isArray(event.sent_emails) ? event.sent_emails : [];
  const attendees = toAddressList(event.attendees);
  const blocks = [];
  if (sentTo.length) {
    blocks.push(`<div class="meeting-email-meta"><strong>Emails sent to:</strong> ${escapeHtml(sentTo.join(", "))}</div>`);
  } else if (attendees.length) {
    blocks.push(`<div class="meeting-email-meta"><strong>Participants (not emailed yet):</strong> ${escapeHtml(attendees.join(", "))}</div>`);
  }
  if (sentEmails.length) {
    blocks.push(
      sentEmails.map((m) => `
        <div class="meeting-email-meta" style="margin-top:8px;">
          <strong>Sent Mail:</strong> ${escapeHtml(m.subject)} · To: ${escapeHtml(m.recipient_email || "(None)")}${m.cc_email ? ` · Cc: ${escapeHtml(m.cc_email)}` : ""}${m.bcc_email ? ` · Bcc: ${escapeHtml(m.bcc_email)}` : ""} · ${m.received_at ? new Date(m.received_at).toLocaleString() : ""}
        </div>
        <div class="thread-body">${escapeHtml(m.body_text || "")}</div>
      `).join(""),
    );
  }
  return blocks.join("");
}

async function showCalendarEmail(event) {
  if (!event) return;
  state.selectedCalendarEventId = event.id;
  const panel = document.getElementById("calendar-email-panel");
  const isUserCreated = event.is_user_created !== undefined
    ? Boolean(event.is_user_created)
    : (!event.source_email_id || event.email_direction === "sent");
  const hasSentEmails = Boolean((event.sent_emails && event.sent_emails.length) || (event.sent_to && event.sent_to.length));

  const buildActionsHtml = () => `
    <div class="event-card-actions">
      ${isUserCreated ? `<button id="calendar-edit-event" class="btn btn-sm btn-outline" type="button">Edit Event</button>` : ""}
      <button id="calendar-inform-users" class="btn btn-sm btn-primary" type="button">${hasSentEmails ? "Inform About Update (Draft Email)" : "Inform Users (Draft Email)"}</button>
      ${event.source_email_id ? `<button id="calendar-open-full-email" class="btn btn-sm btn-outline" type="button">Open full email</button>` : ""}
      <button id="calendar-delete-event" class="btn btn-sm btn-outline" type="button">Delete Event</button>
    </div>`;

  const bindActions = () => {
    const editBtn = document.getElementById("calendar-edit-event");
    if (editBtn) {
      editBtn.addEventListener("click", () => openCalendarEventEditor(event));
    }
    const informBtn = document.getElementById("calendar-inform-users");
    if (informBtn) {
      informBtn.addEventListener("click", () => buildEventInformDraft(event, hasSentEmails));
    }
    const openEmailBtn = document.getElementById("calendar-open-full-email");
    if (openEmailBtn && event.source_email_id) {
      openEmailBtn.addEventListener("click", () => openEmailDetail(event.source_email_id));
    }
    const delBtn = document.getElementById("calendar-delete-event");
    if (delBtn) {
      delBtn.addEventListener("click", async () => {
        const res = await apiFetch(`/api/calendar/events/${event.id}/`, { method: "DELETE" });
        if (res.error) {
          showToast(res.error);
          return;
        }
        state.selectedCalendarEventId = null;
        panel.innerHTML = `<div class="calendar-empty">Event deleted. Choose an event to view its details here.</div>`;
        showToast("Event deleted");
        fetchCalendar();
      });
    }
  };

  const eventHeaderHtml = `
    <h3>${escapeHtml(event.title)}</h3>
    <div class="meeting-email-meta">${new Date(event.start_at).toLocaleString()}${event.all_day ? " · all day" : ""} · Reminder: ${event.reminder_minutes ? `${event.reminder_minutes} minutes before` : "at event time"}</div>
    <div class="thread-body">${escapeHtml(event.description || "No notes for this event.")}</div>
    ${renderCalendarSentEmailsHtml(event)}
  `;

  if (isUserCreated) {
    panel.innerHTML = `${eventHeaderHtml}${buildActionsHtml()}`;
    bindActions();
    return;
  }

  const received = event.received_email;
  if (received) {
    panel.innerHTML = `
      ${eventHeaderHtml}
      <hr style="border:none;border-top:1px solid var(--border);margin:12px 0;" />
      <div class="meeting-email-meta"><strong>Received Email:</strong> ${escapeHtml(received.subject || "")}</div>
      <div class="meeting-email-meta">${escapeHtml(received.sender_name || "")} &lt;${escapeHtml(received.sender_email || "")}&gt; · To: ${escapeHtml(received.recipient_email || "")}${received.cc_email ? ` · Cc: ${escapeHtml(received.cc_email)}` : ""} · ${received.received_at ? new Date(received.received_at).toLocaleString() : ""}</div>
      <div class="thread-body">${escapeHtml(received.body_text || "")}</div>
      ${buildActionsHtml()}
    `;
    bindActions();
    return;
  }

  panel.innerHTML = `${eventHeaderHtml}<div class="muted">Loading related email…</div>`;
  const data = await apiFetch(`/api/emails/${event.source_email_id}/`);
  if (!data.email) {
    panel.innerHTML = `${eventHeaderHtml}<div class="calendar-empty">Couldn't load the related email.</div>${buildActionsHtml()}`;
    bindActions();
    return;
  }
  const email = data.email;
  const thread = data.thread?.length ? data.thread : [email];
  panel.innerHTML = `
    ${eventHeaderHtml}
    <hr style="border:none;border-top:1px solid var(--border);margin:12px 0;" />
    <div class="meeting-email-meta"><strong>Received Email:</strong> ${escapeHtml(email.subject)}</div>
    ${thread.map((message) => `<div class="meeting-email-meta">${escapeHtml(message.sender_name)} &lt;${escapeHtml(message.sender_email)}&gt; · ${new Date(message.received_at).toLocaleString()}</div><div class="thread-body">${escapeHtml(message.body_text)}</div>`).join("")}
    ${buildActionsHtml()}
  `;
  bindActions();
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
  document.getElementById("btn-restore-bin")?.classList.toggle("hidden", email.folder !== "bin");
  document.getElementById("btn-bin").textContent = email.folder === "bin" ? "Delete Forever" : "Bin";

  const container = document.getElementById("thread-container");
  const messages = thread && thread.length ? thread : [email];
  container.innerHTML = messages
    .map(
      (m) => `
      <div class="thread-card">
        <div class="thread-card-header">
          <div>
            <div><strong>${escapeHtml(m.sender_name)}</strong> &lt;${escapeHtml(m.sender_email)}&gt;</div>
            <div class="thread-recipients">To: ${escapeHtml(m.recipient_email)}${m.cc_email ? ` &middot; Cc: ${escapeHtml(m.cc_email)}` : ""}${m.bcc_email ? ` &middot; Bcc: ${escapeHtml(m.bcc_email)}` : ""}</div>
          </div>
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
      cc: data.email.cc_email || "",
      bcc: data.email.bcc_email || "",
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

async function ensureContactsCached() {
  if (state.cachedContacts.length) return state.cachedContacts;
  const data = await apiFetch("/api/contacts/");
  if (data && Array.isArray(data.contacts)) {
    state.cachedContacts = data.contacts;
  }
  return state.cachedContacts;
}

function resolveContactDisplay(token) {
  const raw = (token || "").trim();
  if (!raw) return null;
  const angle = raw.match(/^(.+?)\s*<([^<>\s]+@[^<>\s]+)>$/);
  if (angle) {
    const email = angle[2].trim();
    const label = angle[1].trim() || email;
    return { value: email, label, email };
  }
  const lower = raw.toLowerCase();
  const byEmail = state.cachedContacts.find((c) => (c.email || "").toLowerCase() === lower);
  if (byEmail) {
    return { value: byEmail.email, label: byEmail.name || byEmail.email, email: byEmail.email };
  }
  if (raw.includes("@")) {
    return { value: raw, label: raw, email: raw };
  }
  const byName = state.cachedContacts.find((c) => (c.name || "").toLowerCase() === lower);
  if (byName) {
    return { value: byName.email, label: byName.name || byName.email, email: byName.email };
  }
  return { value: raw, label: raw, email: raw };
}

function splitRecipientTokens(rawValue) {
  if (!rawValue) return [];
  if (Array.isArray(rawValue)) {
    return rawValue.flatMap((v) => splitRecipientTokens(String(v)));
  }
  return String(rawValue)
    .split(/[,;\n]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function syncRecipientHiddenInput(field) {
  const list = state.composeRecipients[field] || [];
  const entry = document.getElementById(`compose-${field}-entry`);
  const values = list.map((item) => item.value);
  const pending = entry ? entry.value.trim() : "";
  if (pending) {
    splitRecipientTokens(pending).forEach((tok) => {
      const resolved = resolveContactDisplay(tok);
      if (resolved && !values.some((v) => v.toLowerCase() === resolved.value.toLowerCase())) {
        values.push(resolved.value);
      }
    });
  }
  const hidden = document.getElementById(`compose-${field}`);
  if (hidden) hidden.value = values.join(", ");
  return hidden ? hidden.value : values.join(", ");
}

function getRecipientFieldValue(field) {
  return syncRecipientHiddenInput(field);
}

function renderRecipientChips(field) {
  const chipsEl = document.getElementById(`compose-${field}-chips`);
  if (!chipsEl) return;
  const list = state.composeRecipients[field] || [];
  chipsEl.innerHTML = list
    .map((item, idx) => {
      const initial = (item.label || item.email || "?").trim().charAt(0).toUpperCase() || "?";
      return `
        <span class="gmail-recipient-chip" data-field="${field}" data-index="${idx}" title="${escapeHtml(item.email)}">
          <span class="gmail-chip-avatar">${escapeHtml(initial)}</span>
          <span class="gmail-chip-text">${escapeHtml(item.label)}</span>
          <button type="button" class="gmail-chip-remove" aria-label="Remove recipient" data-field="${field}" data-index="${idx}">&times;</button>
        </span>
      `;
    })
    .join("");
  chipsEl.querySelectorAll(".gmail-chip-remove").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const idx = Number(btn.dataset.index);
      state.composeRecipients[field].splice(idx, 1);
      renderRecipientChips(field);
      syncComposeConfirmationCards();
      document.getElementById(`compose-${field}-entry`)?.focus();
    });
  });
  syncRecipientHiddenInput(field);
}

function addRecipientToken(field, rawToken) {
  const resolved = resolveContactDisplay(rawToken);
  if (!resolved) return false;
  const list = state.composeRecipients[field] || [];
  const exists = list.some((item) => item.value.toLowerCase() === resolved.value.toLowerCase());
  if (!exists) {
    list.push(resolved);
    state.composeRecipients[field] = list;
  }
  return true;
}

function setRecipientField(field, rawValue) {
  state.composeRecipients[field] = [];
  const entry = document.getElementById(`compose-${field}-entry`);
  if (entry) entry.value = "";
  const suggest = document.getElementById(`compose-${field}-suggest`);
  if (suggest) suggest.classList.add("hidden");
  splitRecipientTokens(rawValue).forEach((tok) => addRecipientToken(field, tok));
  const row = document.getElementById(`compose-${field}-row`);
  if (row && (field === "cc" || field === "bcc")) {
    const hasItems = state.composeRecipients[field].length > 0;
    row.classList.toggle("hidden", !hasItems);
    const toggleBtn = document.getElementById(`btn-toggle-${field}`);
    if (toggleBtn) toggleBtn.classList.toggle("active", hasItems);
  }
  renderRecipientChips(field);
}

function commitRecipientInput(field, explicitValue = null) {
  const entry = document.getElementById(`compose-${field}-entry`);
  const raw = explicitValue !== null ? explicitValue : (entry ? entry.value : "");
  const tokens = splitRecipientTokens(raw);
  let changed = false;
  tokens.forEach((tok) => {
    if (addRecipientToken(field, tok)) changed = true;
  });
  if (entry && explicitValue === null) entry.value = "";
  const suggest = document.getElementById(`compose-${field}-suggest`);
  if (suggest) suggest.classList.add("hidden");
  renderRecipientChips(field);
  if (changed) syncComposeConfirmationCards();
}

function renderRecipientSuggestions(field) {
  const entry = document.getElementById(`compose-${field}-entry`);
  const suggest = document.getElementById(`compose-${field}-suggest`);
  if (!entry || !suggest) return;
  const q = entry.value.trim().toLowerCase();
  if (!q) {
    suggest.classList.add("hidden");
    suggest.innerHTML = "";
    return;
  }
  const existing = new Set((state.composeRecipients[field] || []).map((r) => r.value.toLowerCase()));
  const matches = (state.cachedContacts || [])
    .filter((c) => {
      const email = (c.email || "").toLowerCase();
      const name = (c.name || "").toLowerCase();
      return !existing.has(email) && (name.includes(q) || email.includes(q));
    })
    .slice(0, 6);
  if (!matches.length) {
    suggest.classList.add("hidden");
    suggest.innerHTML = "";
    return;
  }
  suggest.innerHTML = matches
    .map((c) => {
      const initial = (c.name || c.email || "?").trim().charAt(0).toUpperCase() || "?";
      return `
        <button type="button" class="gmail-suggest-item" data-email="${escapeHtml(c.email)}" data-name="${escapeHtml(c.name || "")}">
          <span class="gmail-chip-avatar">${escapeHtml(initial)}</span>
          <span class="gmail-suggest-meta">
            <span class="gmail-suggest-name">${escapeHtml(c.name || c.email)}</span>
            <span class="gmail-suggest-email">${escapeHtml(c.email)}</span>
          </span>
        </button>
      `;
    })
    .join("");
  suggest.classList.remove("hidden");
  suggest.querySelectorAll(".gmail-suggest-item").forEach((btn) => {
    btn.addEventListener("mousedown", (e) => {
      e.preventDefault();
      const email = btn.dataset.email || "";
      const name = btn.dataset.name || "";
      addRecipientToken(field, name ? `${name} <${email}>` : email);
      entry.value = "";
      suggest.classList.add("hidden");
      renderRecipientChips(field);
      syncComposeConfirmationCards();
      entry.focus();
    });
  });
}

function initGmailRecipientInputs() {
  const toggleCc = document.getElementById("btn-toggle-cc");
  const toggleBcc = document.getElementById("btn-toggle-bcc");
  toggleCc?.addEventListener("click", () => {
    const row = document.getElementById("compose-cc-row");
    row?.classList.remove("hidden");
    toggleCc.classList.add("active");
    ensureContactsCached();
    document.getElementById("compose-cc-entry")?.focus();
  });
  toggleBcc?.addEventListener("click", () => {
    const row = document.getElementById("compose-bcc-row");
    row?.classList.remove("hidden");
    toggleBcc.classList.add("active");
    ensureContactsCached();
    document.getElementById("compose-bcc-entry")?.focus();
  });

  ["to", "cc", "bcc"].forEach((field) => {
    const box = document.getElementById(`compose-${field}-box`);
    const entry = document.getElementById(`compose-${field}-entry`);
    if (!entry) return;
    box?.addEventListener("click", (e) => {
      if (!e.target.closest(".gmail-chip-remove")) entry.focus();
    });
    entry.addEventListener("focus", () => ensureContactsCached());
    entry.addEventListener("input", () => {
      if (/[,;\n]/.test(entry.value)) {
        commitRecipientInput(field);
      } else {
        syncRecipientHiddenInput(field);
        renderRecipientSuggestions(field);
        syncComposeConfirmationCards();
      }
    });
    entry.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === "," || e.key === ";") {
        if (entry.value.trim()) {
          e.preventDefault();
          commitRecipientInput(field);
        } else if (e.key === "Enter") {
          e.preventDefault();
        }
      } else if (e.key === "Tab" && entry.value.trim()) {
        commitRecipientInput(field);
      } else if (e.key === "Backspace" && !entry.value && state.composeRecipients[field].length) {
        state.composeRecipients[field].pop();
        renderRecipientChips(field);
        syncComposeConfirmationCards();
      }
    });
    entry.addEventListener("blur", () => {
      setTimeout(() => {
        if (entry.value.trim()) commitRecipientInput(field);
        else document.getElementById(`compose-${field}-suggest`)?.classList.add("hidden");
      }, 140);
    });
  });
}

function openCompose({ draftId = null, calendarEventId = null, to = "", cc = "", bcc = "", subject = "", body = "", threadId = null, inReplyTo = null, title = "New Message" } = {}) {
  state.composeDraftId = draftId;
  state.composeCalendarEventId = calendarEventId;
  state.composeThreadId = threadId;
  state.composeInReplyTo = inReplyTo;
  ensureContactsCached();
  document.getElementById("compose-title").textContent = title;
  setRecipientField("to", to);
  setRecipientField("cc", cc);
  setRecipientField("bcc", bcc);
  document.getElementById("compose-cc-row")?.classList.toggle("hidden", !cc);
  document.getElementById("btn-toggle-cc")?.classList.toggle("active", Boolean(cc));
  document.getElementById("compose-bcc-row")?.classList.toggle("hidden", !bcc);
  document.getElementById("btn-toggle-bcc")?.classList.toggle("active", Boolean(bcc));
  document.getElementById("compose-subject").value = subject;
  document.getElementById("compose-body").value = body;
  document.getElementById("compose-schedule-at").value = "";
  switchView("compose");
}

async function animateFieldFill(inputEl, value) {
  const recipientMap = { "compose-to": "to", "compose-cc": "cc", "compose-bcc": "bcc" };
  if (inputEl && recipientMap[inputEl.id]) {
    const field = recipientMap[inputEl.id];
    const row = document.getElementById(`compose-${field}-row`);
    setRecipientField(field, value || "");
    if (row) {
      row.classList.add("ai-filling");
      await new Promise((r) => setTimeout(r, 90));
      setTimeout(() => row.classList.remove("ai-filling"), 500);
    }
    return;
  }
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
  const payload = {
    ...draft,
    calendar_event_id: draft.calendar_event_id ?? state.composeCalendarEventId ?? null,
  };
  const res = await apiFetch("/api/emails/send/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (res.status === "sent") {
    showToast(`Email sent to ${payload.to}`);
    state.composeDraftId = null;
    state.composeCalendarEventId = null;
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
  const toValue = getRecipientFieldValue("to");
  const ccValue = getRecipientFieldValue("cc");
  const bccValue = getRecipientFieldValue("bcc");
  const subjectValue = document.getElementById("compose-subject").value;
  const scheduleValue = document.getElementById("compose-schedule-at").value;
  const scheduleText = scheduleValue ? new Date(scheduleValue).toLocaleString() : "";
  document.querySelectorAll(".send-confirmation-card, .schedule-confirmation-card").forEach((card) => {
    const to = card.querySelector(".confirm-to");
    const cc = card.querySelector(".confirm-cc");
    const ccWrap = card.querySelector(".confirm-cc-wrap");
    const bcc = card.querySelector(".confirm-bcc");
    const bccWrap = card.querySelector(".confirm-bcc-wrap");
    const subject = card.querySelector(".confirm-subject");
    const scheduledEl = card.querySelector(".confirm-scheduled-at");
    if (to) to.textContent = toValue;
    if (cc) cc.textContent = ccValue;
    if (ccWrap) ccWrap.classList.toggle("hidden", !ccValue);
    if (bcc) bcc.textContent = bccValue;
    if (bccWrap) bccWrap.classList.toggle("hidden", !bccValue);
    if (subject) subject.textContent = subjectValue;
    if (scheduledEl && scheduleText) scheduledEl.textContent = scheduleText;
  });
}

async function resolveActionCalendarEvent(action) {
  if (action?.event) return action.event;
  const targetId = action?.event_id || action?.id || state.selectedCalendarEventId;
  if (!targetId) return null;
  const cached = state.lastCalendarEvents.find((item) => Number(item.id) === Number(targetId));
  if (cached) return cached;
  const resp = await apiFetch(`/api/calendar/events/${targetId}/`);
  return resp.event || null;
}

async function saveCurrentComposeDraft() {
  ["to", "cc", "bcc"].forEach((field) => commitRecipientInput(field));
  const res = await apiFetch("/api/emails/draft/", {
    method: "POST",
    body: JSON.stringify({
      draft_id: state.composeDraftId,
      to: getRecipientFieldValue("to"),
      cc: getRecipientFieldValue("cc"),
      bcc: getRecipientFieldValue("bcc"),
      subject: document.getElementById("compose-subject").value,
      body: document.getElementById("compose-body").value,
      thread_id: state.composeThreadId,
      in_reply_to: state.composeInReplyTo,
    }),
  });
  if (res.status === "saved") {
    state.composeDraftId = null;
    state.composeCalendarEventId = null;
    showToast("Draft saved");
    switchView("drafts");
    fetchEmails();
    return true;
  }
  showToast(res.error || "Failed to save draft");
  return false;
}

async function executeUiActions(actions = []) {
  const hasDraftAction = actions.some(
    (a) => a.type === "fill_compose" || a.type === "update_compose_draft"
  );
  for (const action of actions) {
    if (action.type === "navigate_view") {
      if (action.view === "calendar" && action.calendar_mode) {
        state.calendarMode = action.calendar_mode;
      }
      if (action.view === "compose" && action.fresh) {
        openCompose();
      } else {
        switchView(action.view);
      }
      if (action.view === "contacts") fetchContacts();
      else if (action.view === "meetings") fetchMeetingEmails();
      else if (action.view === "calendar") fetchCalendar();
    } else if (action.type === "fill_compose") {
      switchView("compose");
      await ensureContactsCached();
      state.composeDraftId = action.draft_id || null;
      state.composeCalendarEventId = action.calendar_event_id || null;
      state.composeThreadId = action.thread_id || null;
      state.composeInReplyTo = action.in_reply_to || null;
      const modeTitle = action.mode === "reply" ? "Reply" : action.mode === "forward" ? "Forward" : "New Message";
      document.getElementById("compose-title").textContent = modeTitle;
      setRecipientField("cc", "");
      setRecipientField("bcc", "");
      document.getElementById("compose-cc-row")?.classList.toggle("hidden", !action.cc);
      document.getElementById("btn-toggle-cc")?.classList.toggle("active", Boolean(action.cc));
      document.getElementById("compose-bcc-row")?.classList.toggle("hidden", !action.bcc);
      document.getElementById("btn-toggle-bcc")?.classList.toggle("active", Boolean(action.bcc));
      await animateFieldFill(document.getElementById("compose-to"), action.to || "");
      if (action.cc) {
        await animateFieldFill(document.getElementById("compose-cc"), action.cc || "");
      }
      if (action.bcc) {
        await animateFieldFill(document.getElementById("compose-bcc"), action.bcc || "");
      }
      await animateFieldFill(document.getElementById("compose-subject"), action.subject || "");
      await animateFieldFill(document.getElementById("compose-body"), action.body || "");
      if (action.scheduled_at) {
        const when = new Date(action.scheduled_at);
        const local = new Date(when.getTime() - when.getTimezoneOffset() * 60000);
        document.getElementById("compose-schedule-at").value = local.toISOString().slice(0, 16);
      } else {
        document.getElementById("compose-schedule-at").value = "";
      }
      syncComposeConfirmationCards();
    } else if (action.type === "update_compose_draft") {
      switchView("compose");
      await ensureContactsCached();
      if (action.calendar_event_id !== undefined) {
        state.composeCalendarEventId = action.calendar_event_id || null;
      }
      if (action.to !== undefined) setRecipientField("to", action.to);
      if (action.cc !== undefined) {
        setRecipientField("cc", action.cc);
        document.getElementById("compose-cc-row")?.classList.toggle("hidden", !action.cc);
        document.getElementById("btn-toggle-cc")?.classList.toggle("active", Boolean(action.cc));
      }
      if (action.bcc !== undefined) {
        setRecipientField("bcc", action.bcc);
        document.getElementById("compose-bcc-row")?.classList.toggle("hidden", !action.bcc);
        document.getElementById("btn-toggle-bcc")?.classList.toggle("active", Boolean(action.bcc));
      }
      await animateFieldFill(document.getElementById("compose-subject"), action.subject || "");
      await animateFieldFill(document.getElementById("compose-body"), action.body || "");
      if (action.scheduled_at) {
        const when = new Date(action.scheduled_at);
        if (!Number.isNaN(when.getTime())) {
          const local = new Date(when.getTime() - when.getTimezoneOffset() * 60000);
          document.getElementById("compose-schedule-at").value = local.toISOString().slice(0, 16);
        }
      }
      syncComposeConfirmationCards();
    } else if (action.type === "apply_filters") {
      state.openEmailId = null;
      state.openEmail = null;
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
      fetchContacts();
    } else if (action.type === "refresh_calendar") {
      if (action.calendar_mode) state.calendarMode = action.calendar_mode;
      if (action.deleted_event_id && Number(state.selectedCalendarEventId) === Number(action.deleted_event_id)) {
        state.selectedCalendarEventId = null;
        const panel = document.getElementById("calendar-email-panel");
        if (panel) panel.innerHTML = `<div class="calendar-empty">Event deleted. Choose an event to view its details here.</div>`;
      }
      await fetchCalendar();
      const targetId = action.selected_event_id || state.selectedCalendarEventId;
      if (targetId) {
        const refreshed = state.lastCalendarEvents.find((item) => Number(item.id) === Number(targetId));
        if (refreshed) {
          await showCalendarEmail(refreshed);
        } else {
          const check = await apiFetch(`/api/calendar/events/${targetId}/`);
          if (!check.event) {
            state.selectedCalendarEventId = null;
            const panel = document.getElementById("calendar-email-panel");
            if (panel) panel.innerHTML = `<div class="calendar-empty">Choose an event to view its details here.</div>`;
          }
        }
      }
    } else if (action.type === "refresh_auth_status") {
      loadAuthStatus();
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
    } else if (action.type === "toggle_theme") {
      const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem("jarvis_theme", next);
    } else if (action.type === "new_chat") {
      if (action.chat) {
        state.activeChatId = action.chat.id;
        state.chatHistory = [];
        localStorage.setItem("jarvis_active_chat", String(state.activeChatId));
        state.assistantChats = [action.chat, ...state.assistantChats.filter((chat) => String(chat.id) !== String(action.chat.id))];
        renderAssistantChatList();
        showAssistantWelcome();
      } else {
        await createAssistantChat();
      }
    } else if (action.type === "select_calendar_event") {
      if (state.currentView !== "calendar") {
        switchView("calendar");
        await fetchCalendar();
      }
      const ev = await resolveActionCalendarEvent(action);
      if (ev) {
        state.selectedCalendarEventId = ev.id;
        document.querySelectorAll(".calendar-event-row").forEach((row) => {
          row.classList.toggle("selected", Number(row.dataset.eventId) === Number(ev.id));
        });
        await showCalendarEmail(ev);
      }
    } else if (action.type === "open_calendar_event_form") {
      if (state.currentView !== "calendar") {
        switchView("calendar");
        await fetchCalendar();
      }
      resetCalendarForm();
      document.getElementById("calendar-add-form")?.classList.remove("hidden");
      document.getElementById("calendar-event-title")?.focus();
    } else if (action.type === "edit_calendar_event_form") {
      if (state.currentView !== "calendar") {
        switchView("calendar");
        await fetchCalendar();
      }
      const ev = await resolveActionCalendarEvent(action);
      if (ev) openCalendarEventEditor(ev);
      else showToast("Select a user-created event to edit");
    } else if (action.type === "close_calendar_event_form") {
      resetCalendarForm();
      document.getElementById("calendar-add-form")?.classList.add("hidden");
    } else if (action.type === "calendar_nav") {
      if (state.currentView !== "calendar") switchView("calendar");
      const dir = action.direction === "prev" || action.direction === "previous" || Number(action.delta) < 0 ? -1 : 1;
      state.calendarMode = "month";
      state.calendarMonth = new Date(state.calendarMonth.getFullYear(), state.calendarMonth.getMonth() + dir, 1);
      await fetchCalendar();
    } else if (action.type === "paginate") {
      const dir = action.direction === "prev" || action.direction === "previous" || Number(action.delta) < 0 ? -1 : 1;
      const target = action.target || (state.currentView === "calendar" ? "calendar" : state.currentView === "meetings" ? "meetings" : "emails");
      if (target === "calendar") {
        if (state.currentView !== "calendar") switchView("calendar");
        state.calendarMode = "list";
        state.calendarPage = Math.max(1, Math.min(state.calendarTotalPages || 1, state.calendarPage + dir));
        await fetchCalendar();
      } else if (target === "meetings") {
        if (state.currentView !== "meetings") switchView("meetings");
        state.meetingPage = Math.max(1, Math.min(state.meetingTotalPages || 1, state.meetingPage + dir));
        await fetchMeetingEmails();
      } else {
        state.page = Math.max(1, Math.min(state.totalPages || 1, state.page + dir));
        await fetchEmails();
      }
    } else if (action.type === "toggle_compose_field") {
      if (state.currentView !== "compose") openCompose();
      const fields = action.field === "both" ? ["cc", "bcc"] : [action.field === "bcc" ? "bcc" : "cc"];
      fields.forEach((f) => {
        const row = document.getElementById(`compose-${f}-row`);
        const btn = document.getElementById(`btn-toggle-${f}`);
        const shouldShow = typeof action.show === "boolean" ? action.show : (action.toggle && row ? row.classList.contains("hidden") : true);
        row?.classList.toggle("hidden", !shouldShow);
        btn?.classList.toggle("active", shouldShow);
        if (shouldShow) document.getElementById(`compose-${f}-entry`)?.focus();
      });
    } else if (action.type === "save_current_draft") {
      await saveCurrentComposeDraft();
    } else if (action.type === "approve_detected_meeting") {
      if (state.pendingMeeting) {
        await addDetectedMeeting(state.pendingMeeting, action.reminder_minutes ?? 15);
      } else {
        showToast("No pending detected meeting to approve");
      }
    } else if (action.type === "dismiss_detected_meeting") {
      document.getElementById("meeting-approval-dismiss")?.click();
    } else if (action.type === "simulate_push_email") {
      if (action.simulated || action.email) {
        fetchEmails();
        checkMeetingSuggestions();
      } else {
        await apiFetch("/api/mail/simulate-incoming/", { method: "POST", body: "{}" });
        fetchEmails();
        checkMeetingSuggestions();
      }
    } else if (action.type === "disconnect_gmail") {
      await apiFetch("/auth/logout/", { method: "POST", body: "{}" });
      loadAuthStatus();
      fetchEmails();
    } else if (action.type === "connect_gmail") {
      if (action.url) window.location.assign(action.url);
      else document.getElementById("btn-connect-gmail")?.click();
    } else if (action.type === "cancel_contact_edit") {
      resetContactForm();
    } else if (action.type === "open_event_email") {
      const targetEmailId = action.email_id || (await resolveActionCalendarEvent(action))?.source_email_id;
      if (targetEmailId) await openEmailDetail(targetEmailId);
    } else if (action.type === "inform_event_users") {
      const ev = await resolveActionCalendarEvent(action);
      if (ev) {
        const hasSent = Boolean((ev.sent_emails && ev.sent_emails.length) || (ev.sent_to && ev.sent_to.length));
        buildEventInformDraft(ev, hasSent);
      } else {
        showToast("Select an event to inform users");
      }
    } else if (action.type === "submit_compose") {
      if (hasDraftAction) continue;
      await sendComposeDraft({
        draft_id: state.composeDraftId,
        calendar_event_id: state.composeCalendarEventId,
        to: getRecipientFieldValue("to"),
        cc: getRecipientFieldValue("cc"),
        bcc: getRecipientFieldValue("bcc"),
        subject: document.getElementById("compose-subject").value,
        body: document.getElementById("compose-body").value,
        thread_id: state.composeThreadId,
        in_reply_to: state.composeInReplyTo,
      });
      state.composeDraftId = null;
      state.composeCalendarEventId = null;
    } else if (action.type === "confirm_schedule" && !hasDraftAction) {
      const dateValue = document.getElementById("compose-schedule-at").value;
      const res = await apiFetch("/api/emails/schedule/", {
        method: "POST",
        body: JSON.stringify({
          confirmed: true,
          draft_id: state.composeDraftId,
          to: getRecipientFieldValue("to"),
          cc: getRecipientFieldValue("cc"),
          bcc: getRecipientFieldValue("bcc"),
          subject: document.getElementById("compose-subject").value,
          body: document.getElementById("compose-body").value,
          scheduled_at: dateValue ? new Date(dateValue).toISOString() : "",
          thread_id: state.composeThreadId,
          in_reply_to: state.composeInReplyTo,
        }),
      });
      if (res.status === "scheduled") {
        document.querySelectorAll(".schedule-confirmation-card .confirm-actions").forEach((el) => {
          if (el.querySelector("button")) el.textContent = "✓ Scheduled";
        });
        state.composeDraftId = null;
        state.composeCalendarEventId = null;
        showToast("Email scheduled");
        switchView("scheduled");
        state.page = 1;
        fetchEmails();
      } else {
        showToast(res.error || "Failed to schedule email");
      }
    } else if (action.type === "discard_compose") {
      state.composeDraftId = null;
      state.composeCalendarEventId = null;
      switchView(state.folder);
      fetchEmails();
    }
  }
}

function resetContactForm() {
  const editIdEl = document.getElementById("contact-edit-id");
  const nameEl = document.getElementById("contact-name");
  const emailEl = document.getElementById("contact-email");
  const notesEl = document.getElementById("contact-notes");
  const submitBtn = document.getElementById("contact-submit-btn");
  const cancelBtn = document.getElementById("contact-cancel-edit");
  if (editIdEl) editIdEl.value = "";
  if (nameEl) nameEl.value = "";
  if (emailEl) emailEl.value = "";
  if (notesEl) notesEl.value = "";
  if (submitBtn) submitBtn.textContent = "Save Contact";
  if (cancelBtn) cancelBtn.classList.add("hidden");
}

async function fetchContacts() {
  const data = await apiFetch("/api/contacts/");
  const listEl = document.getElementById("contacts-list");
  const contacts = data.contacts || [];
  state.cachedContacts = contacts;
  if (!contacts.length) {
    listEl.innerHTML = `<div class="rich-card">No contacts saved yet. Add one above or tell Jarvis "Save contact Name email@example.com".</div>`;
    return;
  }
  listEl.innerHTML = contacts
    .map(
      (c) => `
      <div class="email-row" style="grid-template-columns: 180px 1fr auto;">
        <span class="email-sender"><strong>${escapeHtml(c.name)}</strong>${c.notes ? `<div class="muted">${escapeHtml(c.notes)}</div>` : ""}</span>
        <span class="muted">${escapeHtml(c.email)}</span>
        <span style="display:flex;gap:6px;">
          <button class="btn btn-sm btn-primary btn-email-contact" data-email="${escapeHtml(c.email)}">Email</button>
          <button class="btn btn-sm btn-outline btn-edit-contact" data-id="${c.id}">Edit</button>
          <button class="btn btn-sm btn-ghost btn-del-contact" data-id="${c.id}">Delete</button>
        </span>
      </div>
    `
    )
    .join("");

  listEl.querySelectorAll(".btn-email-contact").forEach((btn) => {
    btn.addEventListener("click", () => openCompose({ to: btn.dataset.email }));
  });
  listEl.querySelectorAll(".btn-edit-contact").forEach((btn) => {
    btn.addEventListener("click", () => {
      const contact = contacts.find((item) => item.id === Number(btn.dataset.id));
      if (!contact) return;
      document.getElementById("contact-edit-id").value = String(contact.id);
      document.getElementById("contact-name").value = contact.name || "";
      document.getElementById("contact-email").value = contact.email || "";
      document.getElementById("contact-notes").value = contact.notes || "";
      document.getElementById("contact-submit-btn").textContent = "Update Contact";
      document.getElementById("contact-cancel-edit").classList.remove("hidden");
      document.getElementById("contact-name").focus();
    });
  });
  listEl.querySelectorAll(".btn-del-contact").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await apiFetch(`/api/contacts/${btn.dataset.id}/`, { method: "DELETE" });
      if (document.getElementById("contact-edit-id")?.value === String(btn.dataset.id)) {
        resetContactForm();
      }
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
          <div class="rich-card-sub">To: ${escapeHtml(card.draft.to || "")}</div>
          ${card.draft.cc ? `<div class="rich-card-sub">Cc: ${escapeHtml(card.draft.cc)}</div>` : ""}
          ${card.draft.bcc ? `<div class="rich-card-sub">Bcc: ${escapeHtml(card.draft.bcc)}</div>` : ""}
          <div><strong>${escapeHtml(card.draft.subject)}</strong></div>
          <div class="muted">Previous draft preview</div>
        `;
        wrapper.appendChild(c);
        continue;
      }
      c.className = "rich-card send-confirmation-card";
      c.innerHTML = `
        <div class="rich-card-title">Confirm Send</div>
        <div class="rich-card-sub">To: <span class="confirm-to">${escapeHtml(card.draft.to || "")}</span></div>
        <div class="rich-card-sub confirm-cc-wrap${card.draft.cc ? "" : " hidden"}">Cc: <span class="confirm-cc">${escapeHtml(card.draft.cc || "")}</span></div>
        <div class="rich-card-sub confirm-bcc-wrap${card.draft.bcc ? "" : " hidden"}">Bcc: <span class="confirm-bcc">${escapeHtml(card.draft.bcc || "")}</span></div>
        <div><strong class="confirm-subject">${escapeHtml(card.draft.subject)}</strong></div>
        <div class="confirm-actions">
          <button class="btn btn-sm btn-primary btn-confirm-send">Confirm & Send</button>
          <button class="btn btn-sm btn-ghost btn-cancel-send">Cancel</button>
        </div>
      `;
      c.querySelector(".btn-confirm-send").addEventListener("click", async (e) => {
        e.target.disabled = true;
        const ok = await sendComposeDraft({
          draft_id: state.composeDraftId || card.draft.draft_id || null,
          calendar_event_id: card.draft.calendar_event_id ?? state.composeCalendarEventId ?? null,
          to: getRecipientFieldValue("to") || card.draft.to || "",
          cc: getRecipientFieldValue("cc") || card.draft.cc || "",
          bcc: getRecipientFieldValue("bcc") || card.draft.bcc || "",
          subject: document.getElementById("compose-subject").value || card.draft.subject,
          body: document.getElementById("compose-body").value || card.draft.body,
          thread_id: card.draft.thread_id,
          in_reply_to: card.draft.in_reply_to,
        });
        if (ok) c.querySelector(".confirm-actions").innerHTML = `<span class="muted">✓ Sent</span>`;
        else e.target.disabled = false;
      });
      c.querySelector(".btn-cancel-send").addEventListener("click", () => {
        c.querySelector(".confirm-actions").innerHTML = `<span class="muted">Cancelled</span>`;
      });
      wrapper.appendChild(c);
    } else if (card.type === "schedule_confirmation" && card.draft) {
      const c = document.createElement("div");
      c.className = "rich-card schedule-confirmation-card";
      c.innerHTML = `<div class="rich-card-title">Confirm Schedule</div><div class="rich-card-sub">To: <span class="confirm-to">${escapeHtml(card.draft.to || "")}</span></div><div class="rich-card-sub confirm-cc-wrap${card.draft.cc ? "" : " hidden"}">Cc: <span class="confirm-cc">${escapeHtml(card.draft.cc || "")}</span></div><div class="rich-card-sub confirm-bcc-wrap${card.draft.bcc ? "" : " hidden"}">Bcc: <span class="confirm-bcc">${escapeHtml(card.draft.bcc || "")}</span></div><div><strong class="confirm-subject">${escapeHtml(card.draft.subject)}</strong></div><div class="muted confirm-scheduled-at">${escapeHtml(new Date(card.draft.scheduled_at).toLocaleString())}</div><div class="confirm-actions"><button class="btn btn-sm btn-primary">Confirm &amp; Schedule</button><button class="btn btn-sm btn-ghost">Cancel</button></div>`;
      const [confirmButton, cancelButton] = c.querySelectorAll("button");
      if (historical) {
        c.querySelector(".confirm-actions").textContent = "Previous schedule preview";
      } else {
        confirmButton.addEventListener("click", async () => {
          confirmButton.disabled = true;
          const dateValue = document.getElementById("compose-schedule-at").value;
          const res = await apiFetch("/api/emails/schedule/", { method: "POST", body: JSON.stringify({
            confirmed: true, draft_id: state.composeDraftId,
            to: getRecipientFieldValue("to") || card.draft.to || "",
            cc: getRecipientFieldValue("cc") || card.draft.cc || "",
            bcc: getRecipientFieldValue("bcc") || card.draft.bcc || "",
            subject: document.getElementById("compose-subject").value || card.draft.subject,
            body: document.getElementById("compose-body").value || card.draft.body,
            scheduled_at: dateValue ? new Date(dateValue).toISOString() : card.draft.scheduled_at,
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
    } else if (card.type === "calendar_event" && card.event) {
      const c = document.createElement("div");
      c.className = "rich-card";
      const whenLabel = new Date(card.event.start_at).toLocaleString();
      c.innerHTML = `
        <div class="rich-card-title">${escapeHtml(card.event.title)}</div>
        <div class="rich-card-sub">${escapeHtml(whenLabel)}</div>
        ${card.event.description ? `<div>${escapeHtml(card.event.description)}</div>` : ""}
        <div class="event-card-actions">
          <button class="btn btn-sm btn-outline btn-open-cal" type="button">Open in Calendar</button>
          <button class="btn btn-sm btn-primary btn-inform-cal" type="button">Inform Users (Draft Email)</button>
        </div>
      `;
      c.querySelector(".btn-open-cal").addEventListener("click", () => {
        state.calendarMode = "list";
        switchView("calendar");
        fetchCalendar();
      });
      c.querySelector(".btn-inform-cal").addEventListener("click", () => {
        const draft = card.draft || {
          to: "",
          subject: `Invitation: ${card.event.title}`,
          body: `Hi,\n\nI've scheduled "${card.event.title}" for ${whenLabel}.\n\nPlease let me know if this works for you.\n\nBest regards,`,
        };
        openCompose({ ...draft, title: "Inform Users about Event" });
        showToast("Opened invitation draft in Compose");
      });
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
    selected_calendar_event_id: state.selectedCalendarEventId,
    active_filters: state.filters,
    tz_offset_minutes: new Date().getTimezoneOffset(),
  };
  if (state.currentView === "compose") {
    uiContext.compose_draft = {
      to: getRecipientFieldValue("to"),
      cc: getRecipientFieldValue("cc"),
      bcc: getRecipientFieldValue("bcc"),
      subject: document.getElementById("compose-subject").value,
      body: document.getElementById("compose-body").value,
      scheduled_at: document.getElementById("compose-schedule-at").value,
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
  const isNewChat = Boolean(res.new_chat || (res.ui_actions || []).some((a) => a.type === "new_chat"));
  const replyText = res.reply || "I couldn't determine an action for that request. Please rephrase it.";
  if (res.conversation_id) {
    state.activeChatId = res.conversation_id;
    localStorage.setItem("jarvis_active_chat", String(state.activeChatId));
  }
  appendAssistantMessage(replyText, res.rich_cards || [], res.agent_steps || []);
  if (isNewChat) {
    state.chatHistory.push({ role: "assistant", content: replyText, rich_cards: res.rich_cards || [], agent_steps: res.agent_steps || [] });
    document.getElementById("assistant-input")?.focus();
  } else {
    state.chatHistory.push(
      { role: "user", content: message, context: uiContext },
      { role: "assistant", content: replyText, rich_cards: res.rich_cards || [], agent_steps: res.agent_steps || [] },
    );
  }
  await refreshAssistantChatList();
}

async function loadAuthStatus() {
  const status = await apiFetch("/auth/status/");
  const displayName = status.display_name || status.email || "Jarvis User";
  const nameEl = document.getElementById("account-name");
  const avatarEl = document.getElementById("account-avatar");
  const metaEl = document.getElementById("account-meta");
  if (nameEl) nameEl.textContent = displayName;
  document.getElementById("account-email").textContent = status.email || "";
  document.getElementById("account-provider").textContent =
    status.provider === "gmail" ? "Gmail Connected" : "Demo Mode (Local)";

  if (avatarEl) {
    avatarEl.replaceChildren();
    avatarEl.classList.remove("hidden");
    if (status.picture) {
      const img = document.createElement("img");
      img.src = status.picture;
      img.alt = displayName;
      avatarEl.appendChild(img);
    } else {
      const initials = displayName
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => part[0].toUpperCase())
        .join("") || "J";
      avatarEl.textContent = initials;
    }
  }
  if (metaEl) {
    const parts = [];
    if (typeof status.unread_count === "number") parts.push(`${status.unread_count} unread`);
    if (typeof status.messages_total === "number") parts.push(`${status.messages_total} total`);
    if (typeof status.contacts_count === "number") parts.push(`${status.contacts_count} contacts`);
    metaEl.textContent = parts.join(" · ");
  }

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

function openJarvisSpotlight() {
  const overlay = document.getElementById("jarvis-spotlight-overlay");
  const input = document.getElementById("jarvis-spotlight-input");
  const assistantPill = document.getElementById("assistant-context-pill");
  const spotlightPill = document.getElementById("jarvis-spotlight-context");
  if (!overlay || !input) return;
  if (assistantPill && spotlightPill) {
    spotlightPill.textContent = assistantPill.textContent;
  }
  overlay.classList.remove("hidden");
  document.body.classList.add("spotlight-open");
  input.focus();
  input.select();
}

function closeJarvisSpotlight() {
  const overlay = document.getElementById("jarvis-spotlight-overlay");
  if (!overlay) return;
  overlay.classList.add("hidden");
  document.body.classList.remove("spotlight-open");
}

function toggleJarvisSpotlight() {
  const overlay = document.getElementById("jarvis-spotlight-overlay");
  if (!overlay) return;
  if (overlay.classList.contains("hidden")) openJarvisSpotlight();
  else closeJarvisSpotlight();
}

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  initGmailRecipientInputs();
  loadAuthStatus();
  fetchEmails();
  ensureContactsCached();
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

  document.getElementById("btn-clear-bin")?.addEventListener("click", async () => {
    if (!window.confirm("Permanently delete all emails in your Bin?")) return;
    const res = await apiFetch("/api/emails/bin/clear/", { method: "POST", body: "{}" });
    if (res.error) {
      showToast(res.error);
      return;
    }
    showToast(`Cleared Bin (${res.deleted_count || 0} email(s) deleted)`);
    fetchEmails();
  });

  document.getElementById("contact-cancel-edit")?.addEventListener("click", resetContactForm);

  document.getElementById("contact-add-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const editId = document.getElementById("contact-edit-id")?.value.trim();
    const name = document.getElementById("contact-name").value.trim();
    const email = document.getElementById("contact-email").value.trim();
    const notes = document.getElementById("contact-notes")?.value.trim() || "";
    const url = editId ? `/api/contacts/${editId}/` : "/api/contacts/";
    const method = editId ? "PUT" : "POST";
    const res = await apiFetch(url, {
      method,
      body: JSON.stringify({ name, email, notes }),
    });
    if (res.contact) {
      showToast(`${editId ? "Updated" : "Saved"} ${res.contact.name}`);
      resetContactForm();
      fetchContacts();
    } else {
      showToast(res.error || "Failed to save contact");
    }
  });

  document.getElementById("btn-compose").addEventListener("click", () => openCompose());
  document.getElementById("btn-discard-compose").addEventListener("click", () => {
    state.composeDraftId = null;
    state.composeCalendarEventId = null;
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

  document.getElementById("btn-restore-bin")?.addEventListener("click", async () => {
    if (!state.openEmailId) return;
    const res = await apiFetch(`/api/emails/${state.openEmailId}/move/`, {
      method: "POST",
      body: JSON.stringify({ folder: "restore" }),
    });
    if (res.error) {
      showToast(res.error);
      return;
    }
    showToast("Restored to Inbox");
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
    ["to", "cc", "bcc"].forEach((field) => commitRecipientInput(field));
    const toVal = getRecipientFieldValue("to").trim();
    const ccVal = getRecipientFieldValue("cc").trim();
    const bccVal = getRecipientFieldValue("bcc").trim();
    const subjectVal = document.getElementById("compose-subject").value.trim();
    const bodyVal = document.getElementById("compose-body").value;
    if (!toVal) {
      showToast("Please add at least one recipient in To");
      document.getElementById("compose-to-entry")?.focus();
      return;
    }
    if (!subjectVal && !bodyVal.trim()) {
      showToast("Please enter a subject or message");
      document.getElementById("compose-subject")?.focus();
      return;
    }
    const ok = await sendComposeDraft({
      draft_id: state.composeDraftId,
      calendar_event_id: state.composeCalendarEventId,
      to: toVal,
      cc: ccVal,
      bcc: bccVal,
      subject: subjectVal,
      body: bodyVal,
      thread_id: state.composeThreadId,
      in_reply_to: state.composeInReplyTo,
    });
    if (ok) {
      state.composeDraftId = null;
      state.composeCalendarEventId = null;
    }
  });

  ["compose-subject", "compose-schedule-at"].forEach((id) =>
    document.getElementById(id).addEventListener("input", syncComposeConfirmationCards)
  );

  document.getElementById("btn-save-draft").addEventListener("click", saveCurrentComposeDraft);

  document.getElementById("btn-schedule-send").addEventListener("click", async () => {
    ["to", "cc", "bcc"].forEach((field) => commitRecipientInput(field));
    const scheduledAt = document.getElementById("compose-schedule-at").value;
    if (!scheduledAt) {
      showToast("Please pick a date and time to schedule send");
      return;
    }
    const recipient = getRecipientFieldValue("to").trim();
    const ccVal = getRecipientFieldValue("cc").trim();
    const bccVal = getRecipientFieldValue("bcc").trim();
    const subject = document.getElementById("compose-subject").value.trim();
    const body = document.getElementById("compose-body").value.trim();
    if (!recipient || !subject || !body) { showToast("Complete the recipient, subject, and message before scheduling"); return; }
    const when = new Date(scheduledAt);
    if (when <= new Date()) { showToast("Choose a future date and time"); return; }
    const ccLine = ccVal ? `\nCc: ${ccVal}` : "";
    const bccLine = bccVal ? `\nBcc: ${bccVal}` : "";
    const confirmed = window.confirm(`Review your draft before scheduling:\n\nTo: ${recipient}${ccLine}${bccLine}\nSubject: ${subject}\nSend at: ${when.toLocaleString()}\n\nMessage:\n${body}\n\nSchedule this email?`);
    if (!confirmed) return;
    const res = await apiFetch("/api/emails/schedule/", {
      method: "POST",
      body: JSON.stringify({
        draft_id: state.composeDraftId,
        confirmed: true,
        to: recipient,
        cc: ccVal,
        bcc: bccVal,
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

  window.addEventListener("keydown", async (e) => {
    if (e.altKey && !e.ctrlKey && !e.metaKey && (e.code === "KeyN" || e.key?.toLowerCase() === "n")) {
      e.preventDefault();
      closeJarvisSpotlight();
      await createAssistantChat();
      document.getElementById("assistant-input")?.focus();
      return;
    }
    if (e.ctrlKey && !e.altKey && !e.metaKey && (e.code === "Space" || e.key === " ")) {
      e.preventDefault();
      toggleJarvisSpotlight();
      return;
    }
    const spotlightOverlay = document.getElementById("jarvis-spotlight-overlay");
    if (e.key === "Escape" && spotlightOverlay && !spotlightOverlay.classList.contains("hidden")) {
      e.preventDefault();
      closeJarvisSpotlight();
    }
  });

  const spotlightOverlay = document.getElementById("jarvis-spotlight-overlay");
  if (spotlightOverlay) {
    spotlightOverlay.addEventListener("click", (e) => {
      if (e.target === spotlightOverlay) closeJarvisSpotlight();
    });
  }

  const spotlightForm = document.getElementById("jarvis-spotlight-form");
  if (spotlightForm) {
    spotlightForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = document.getElementById("jarvis-spotlight-input");
      const msg = input ? input.value.trim() : "";
      if (!msg) return;
      input.value = "";
      closeJarvisSpotlight();
      await sendAssistantCommand(msg);
    });
  }

  document.getElementById("btn-new-chat").addEventListener("click", async () => {
    await createAssistantChat();
    document.getElementById("assistant-input")?.focus();
  });

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
    const form = document.getElementById("calendar-add-form");
    const isOpening = form.classList.contains("hidden") || Boolean(document.getElementById("calendar-event-edit-id")?.value);
    resetCalendarForm();
    form.classList.toggle("hidden", !isOpening);
    if (isOpening) document.getElementById("calendar-event-title")?.focus();
  });
  document.getElementById("calendar-cancel-add").addEventListener("click", () => {
    resetCalendarForm();
    document.getElementById("calendar-add-form").classList.add("hidden");
  });
  document.getElementById("calendar-add-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const editId = document.getElementById("calendar-event-edit-id")?.value.trim() || "";
    const isEditing = Boolean(editId);
    const title = document.getElementById("calendar-event-title").value.trim();
    const rawStart = document.getElementById("calendar-event-start").value;
    const startAt = new Date(rawStart);
    const reminderMinutes = Number(document.getElementById("calendar-event-reminder").value);
    const description = document.getElementById("calendar-event-description")?.value.trim() || "";
    const attendees = document.getElementById("calendar-event-attendees")?.value.trim() || "";
    const informUsers = Boolean(document.getElementById("calendar-event-inform")?.checked);
    if (!title || !rawStart || Number.isNaN(startAt.getTime())) { showToast("Add an event title and valid date/time"); return; }
    if (startAt <= new Date()) { showToast("Choose a future date and time"); return; }
    const confirmPrompt = isEditing
      ? `Update this event on your Jarvis calendar?\n\n${title}\n${startAt.toLocaleString()}\nReminder: ${reminderMinutes ? `${reminderMinutes} minutes before` : "at event time"}`
      : `Add this event to your Jarvis calendar?\n\n${title}\n${startAt.toLocaleString()}\nReminder: ${reminderMinutes ? `${reminderMinutes} minutes before` : "at event time"}`;
    if (!window.confirm(confirmPrompt)) return;
    const url = isEditing ? `/api/calendar/events/${editId}/` : "/api/calendar/events/";
    const method = isEditing ? "PUT" : "POST";
    const result = await apiFetch(url, { method, body: JSON.stringify({
      confirmed: true,
      title,
      description,
      attendees,
      inform_users: informUsers,
      draft_update: isEditing ? informUsers : false,
      start_at: startAt.toISOString(),
      reminder_minutes: reminderMinutes,
      tz_offset_minutes: new Date().getTimezoneOffset(),
    }) });
    if (result.event) {
      showToast(isEditing ? "Event updated" : "Event added to your calendar");
      state.selectedCalendarEventId = result.event.id;
      resetCalendarForm();
      document.getElementById("calendar-add-form").classList.add("hidden");
      await fetchCalendar();
      await showCalendarEmail(result.event);
      if (informUsers && result.draft) {
        openCompose({
          calendarEventId: result.draft.calendar_event_id || result.event.id,
          to: result.draft.to || "",
          cc: result.draft.cc || "",
          bcc: result.draft.bcc || "",
          subject: result.draft.subject || "",
          body: result.draft.body || "",
          title: isEditing ? "Inform Users about Event Update" : "Inform Users about Event",
        });
        appendAssistantMessage(
          isEditing
            ? `Updated **${result.event.title}** on your Calendar and drafted an update email. Review and confirm when ready to send.`
            : `Added **${result.event.title}** to your Calendar and drafted an invitation email. Review and confirm when ready to send.`,
          [{ type: "send_confirmation", draft: result.draft }],
        );
      }
    } else showToast(result.error || (isEditing ? "Couldn't update event" : "Couldn't add event"));
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
    loadAuthStatus();
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
