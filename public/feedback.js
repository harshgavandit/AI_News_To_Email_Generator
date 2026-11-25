// "Send feedback" on every page, and "Was this useful?" where a page asks for it ([data-useful]).
// Sends only what the reader types, the page path and an optional reply address.
const KINDS = [["idea", "An idea"], ["bug", "Something's broken"], ["coverage", "Missing story or source"],
  ["praise", "Something I like"], ["other", "Other"]];

function el(tag, attributes = {}, text) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (value === true) node.setAttribute(name, "");
    else if (value !== false && value !== undefined) node.setAttribute(name, value);
  }
  if (text !== undefined) node.textContent = text;
  return node;
}

export async function sendFeedback(payload, { fetcher = globalThis.fetch, page = globalThis.location?.pathname || "/" } = {}) {
  const response = await fetcher("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ page, ...payload }) });
  if (response.ok) return;
  let detail = "Your feedback couldn't be sent. Try again in a few minutes.";
  try {
    const body = await response.json();
    if (typeof body.detail === "string") detail = body.detail;
    else if (Array.isArray(body.detail) && body.detail[0]?.msg) detail = String(body.detail[0].msg).replace(/^Value error, /, "");
  } catch { /* keep the default */ }
  throw new Error(detail);
}

function buildDialog(options) {
  const dialog = el("dialog", { class: "feedback-dialog", "aria-labelledby": "feedback-title" });
  const form = el("form", { class: "feedback-form", novalidate: true });
  const head = el("div", { class: "feedback-head" });
  const close = el("button", { type: "button", class: "dialog-close", "aria-label": "Close feedback" }, "×");
  head.append(el("h2", { id: "feedback-title" }, "Send feedback"), close);
  const intro = el("p", { class: "muted" }, "Tell us what to fix or build next. It goes straight to the person who makes Informa AI.");
  const kinds = el("fieldset", { class: "feedback-kinds" });
  kinds.append(el("legend", {}, "What is it about?"));
  for (const [value, label] of KINDS) {
    const wrap = el("label");
    wrap.append(el("input", { type: "radio", name: "kind", value, checked: value === "idea" }), ` ${label}`);
    kinds.append(wrap);
  }
  const messageLabel = el("label", { for: "feedback-message" }, "Your message");
  const message = el("textarea", { id: "feedback-message", name: "message", rows: "5", maxlength: "2000", required: true,
    placeholder: "What happened, or what would make this more useful?" });
  const contactLabel = el("label", { for: "feedback-contact" }, "Email for a reply (optional)");
  const contact = el("input", { id: "feedback-contact", name: "contact", type: "email", maxlength: "200", autocomplete: "email" });
  const trap = el("div", { class: "feedback-trap", "aria-hidden": "true" });
  trap.append(el("label", { for: "feedback-website" }, "Leave this empty"),
    el("input", { id: "feedback-website", name: "website", tabindex: "-1", autocomplete: "off" }));
  const note = el("p", { class: "small muted" }, "We store your message, this page's address and the email you add, nothing else. ");
  note.append(Object.assign(el("a", { href: "/privacy.html#feedback" }), { textContent: "Privacy" }));
  const actions = el("div", { class: "feedback-actions" });
  const submit = el("button", { type: "submit", class: "button primary" }, "Send");
  actions.append(submit);
  const status = el("p", { class: "status", role: "status", "aria-live": "polite" });
  form.append(head, intro, kinds, messageLabel, message, contactLabel, contact, trap, note, actions, status);
  dialog.append(form);
  close.addEventListener("click", () => dialog.close());
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    if (String(data.get("message") || "").trim().length < 3) {
      status.textContent = "Write a few words so we know what to fix or build.";
      message.focus();
      return;
    }
    submit.disabled = true;
    status.textContent = "Sending…";
    try {
      await sendFeedback({ kind: data.get("kind") || "other", message: String(data.get("message")).trim(),
        contact: String(data.get("contact") || "").trim(), website: String(data.get("website") || "") }, options);
      form.reset();
      status.textContent = "Thank you. Your feedback was sent.";
    } catch (error) {
      status.textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  });
  document.body.append(dialog);
  return { dialog, form, status, message };
}

export function mountFeedback(options = {}) {
  let parts;
  const open = (kind = "idea") => {
    parts ||= buildDialog(options);
    const radio = [...parts.form.querySelectorAll("input[name=kind]")].find(input => input.value === kind);
    if (radio) radio.checked = true;
    parts.message.placeholder = kind === "coverage"
      ? "Name the story or publisher. Include the original link if you have it."
      : "What happened, or what would make this more useful?";
    parts.status.textContent = "";
    if (typeof parts.dialog.showModal === "function") parts.dialog.showModal(); else parts.dialog.setAttribute("open", "");
    parts.message.focus();
  };
  const triggers = [...document.querySelectorAll("[data-feedback-open]")];
  if (!triggers.some(trigger => !trigger.dataset.feedbackKind)) {
    const home = document.querySelector(".site-footer .footer-nav") || document.querySelector(".site-tools");
    if (home) {
      const button = el("button", { type: "button", class: "text-button feedback-trigger", "data-feedback-open": true }, "Send feedback");
      home.append(button);
      triggers.push(button);
    }
  }
  for (const trigger of triggers) trigger.addEventListener("click", () => open(trigger.dataset.feedbackKind || "idea"));
  for (const box of document.querySelectorAll("[data-useful]")) mountUseful(box, open, options);
  return { open };
}

export function mountUseful(box, open, options = {}) {
  if (box.dataset.usefulMounted) return;
  box.dataset.usefulMounted = "1";
  const update = box.dataset.useful === "update";
  const question = el("span", { class: "useful-question" }, update ? "Were these updates useful?" : "Was this page useful?");
  const yes = el("button", { type: "button", class: "button secondary" }, "Yes");
  const no = el("button", { type: "button", class: "button secondary" }, "No");
  const status = el("span", { class: "useful-status", role: "status", "aria-live": "polite" });
  box.replaceChildren(question, yes, no, status);
  const answer = async (kind) => {
    yes.disabled = no.disabled = true;
    try {
      const useful = kind === "useful";
      const category = update ? (useful ? "update_yes" : "update_no") : kind;
      await sendFeedback({ kind: category, message: "" }, options);
      status.replaceChildren(useful ? "Thanks! " : "Thanks for saying so. ");
      const more = el("button", { type: "button", class: "text-button" }, useful ? "Anything to add?" : "What was missing?");
      more.addEventListener("click", () => open(update && !useful ? "coverage" : "idea"));
      status.append(more);
    } catch (error) {
      status.textContent = error.message;
      yes.disabled = no.disabled = false;
    }
  };
  yes.addEventListener("click", () => answer("useful"));
  no.addEventListener("click", () => answer("not_useful"));
}
