import { readingContent } from "./reading-content.js";

const byId = (id) => document.getElementById(id);
const node = (tag, text, className = "") => { const el = document.createElement(tag); el.textContent = text; el.className = className; return el; };
const message = (id, text, error = false) => { byId(id).textContent = text; byId(id).classList.toggle("error", error); };
let config = null, selected = null, captchaId = null, captchaToken = "", ownerKey = "", ownerRevision = 0, nextCursor = null, authRevision = 0;
let lookupRevision = 0;
let draftArticleId = null;

async function request(path, options = {}) {
  const response = await fetch(path, { ...options, cache: "no-store", signal: AbortSignal.timeout(25000) });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : `Request failed (${response.status}). Try again.`);
  return data;
}
const post = (path, body, headers = {}) => request(path, { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body) });
const ownerHeaders = () => ({ Authorization: `Bearer ${ownerKey}` });
function link(url, text) {
  const anchor = node("a", text);
  try { const parsed = new URL(url); if (parsed.protocol === "https:" && !parsed.username && !parsed.password) anchor.href = parsed.href; } catch { /* No unsafe link. */ }
  anchor.target = "_blank"; anchor.rel = "noopener noreferrer";
  return anchor;
}
function updateAvailability() {
  const verified = Boolean(config?.verified);
  const canSubmit = Boolean(selected && verified);
  const fields = byId("contribution-fields");
  fields.disabled = fields.hidden = !canSubmit;
  byId("contribution-reload").disabled = !config?.verified;
  byId("author-step-inbox").textContent = verified ? "Inbox verified" : "Connect your email address";
  byId("author-step-article").textContent = selected ? "Article found" : "Use an Informa AI story link";
  byId("author-step-permission").textContent = canSubmit ? "Ready for your submission" : "Submit your text for review";
  const pending = byId("contribution-pending");
  pending.hidden = canSubmit;
  if (!canSubmit) pending.textContent = selected ? "Verify your inbox to unlock the submission form." :
    verified ? "Find an article to unlock the submission form." : "Verify your inbox and find the article to unlock the submission form.";
}

async function captcha() {
  if (!window.turnstile) {
    await new Promise((resolve, reject) => {
      const existing = document.querySelector("script[data-author-captcha]");
      if (existing) existing.remove();
      const script = document.createElement("script"); script.dataset.authorCaptcha = "true";
      script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      const timeout = setTimeout(() => reject(new Error("The verification check timed out. Try again.")), 12000);
      script.addEventListener("load", () => { clearTimeout(timeout); resolve(); }, { once: true });
      script.addEventListener("error", () => { clearTimeout(timeout); reject(new Error("The verification check could not load. Try again.")); }, { once: true });
      document.head.append(script);
    });
  }
  if (captchaId !== null) window.turnstile.remove(captchaId);
  captchaId = window.turnstile.render(byId("contribution-captcha"), { sitekey: config.site_key,
    callback(token) { captchaToken = token; byId("contribution-send-code").disabled = false; },
    "expired-callback"() { captchaToken = ""; byId("contribution-send-code").disabled = true; },
    "error-callback"() { captchaToken = ""; byId("contribution-send-code").disabled = true; byId("contribution-retry-auth").hidden = false; },
  });
}

async function refreshAuth() {
  const revision = ++authRevision;
  try {
    const data = await request("/api/mail/contributions/config");
    if (revision !== authRevision) return;
    config = data;
    byId("contribution-grant-text").textContent = config.permission_statement;
    byId("contribution-identity").hidden = !config.verified;
    byId("contribution-email").textContent = config.verified_email || "";
    byId("contribution-challenge").hidden = config.verified || !config.enabled;
    byId("contribution-verify").hidden = true;
    byId("contribution-retry-auth").hidden = true;
    updateAvailability();
    if (config.verified) {
      message("contribution-auth-status", "Inbox verified. You can submit and manage reading permissions.");
      await loadOwn();
    } else if (config.enabled) {
      message("contribution-auth-status", "Complete the check to receive a verification code.");
      await captcha();
    } else message("contribution-auth-status", "Inbox verification is currently unavailable. Author submissions will reopen when delivery is configured.");
  } catch (error) {
    if (revision !== authRevision) return;
    message("contribution-auth-status", error.message, true);
    byId("contribution-retry-auth").hidden = false;
  }
}

function readArticleId(input) {
  const value = input.trim();
  const valid = /^[A-Za-z0-9_-]{1,40}$/;
  if (valid.test(value)) return value;
  try {
    const url = new URL(value, location.origin);
    const id = url.searchParams.get("article");
    if (url.origin === location.origin && !url.username && !url.password && id && valid.test(id) &&
        ["/", "/index.html"].includes(url.pathname)) return id;
  } catch { /* Invalid or external story link. */ }
  return "";
}

function resetArticleLookup() {
  lookupRevision++;
  selected = null;
  byId("contribution-selected").hidden = true;
  byId("contribution-grant").checked = false;
  updateAvailability();
}

async function findArticle() {
  resetArticleLookup();
  const revision = lookupRevision;
  const id = readArticleId(byId("contribution-article").value);
  if (!id) return message("lookup-status", "Paste an Informa AI story link or a valid article ID.", true);
  message("lookup-status", "Finding the original article…");
  try {
    const data = await request(`/api/articles/${encodeURIComponent(id)}`);
    if (revision !== lookupRevision) return;
    selected = data.article;
    if (draftArticleId && draftArticleId !== selected.id) byId("contribution-form").reset();
    draftArticleId = selected.id;
    byId("contribution-title").textContent = selected.title;
    const original = link(selected.url, "View original ↗");
    byId("contribution-original").href = original.href;
    byId("contribution-selected").hidden = false;
    if (!byId("contribution-author").value) byId("contribution-author").value = selected.author || "";
    message("lookup-status", config?.verified ? "Article found. Add your text and permission evidence below." : "Article found. Verify your inbox to continue.");
    updateAvailability();
  } catch (error) { if (revision === lookupRevision) message("lookup-status", error.message, true); }
}

byId("article-lookup").addEventListener("submit", (event) => { event.preventDefault(); findArticle(); });
byId("contribution-article").addEventListener("input", () => { resetArticleLookup(); message("lookup-status", ""); });
byId("contribution-retry-auth").addEventListener("click", refreshAuth);
byId("contribution-challenge").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!captchaToken) return message("contribution-auth-status", "Complete the verification check first.", true);
  byId("contribution-send-code").disabled = true;
  try {
    await post("/api/mail/challenge", { email: byId("contribution-email-input").value.trim(), captcha: captchaToken });
    byId("contribution-challenge").hidden = true; byId("contribution-verify").hidden = false;
    byId("contribution-code").focus(); message("contribution-auth-status", "Code sent. Check your inbox.");
  } catch (error) { message("contribution-auth-status", error.message, true); }
  finally { captchaToken = ""; if (window.turnstile && captchaId !== null) window.turnstile.reset(captchaId); }
});
byId("contribution-verify").addEventListener("submit", async (event) => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  try { await post("/api/mail/verify", { code: byId("contribution-code").value.trim() }); await refreshAuth(); }
  catch (error) { message("contribution-auth-status", error.message, true); }
  finally { button.disabled = false; }
});
byId("contribution-change-email").addEventListener("click", () => { byId("contribution-verify").hidden = true; byId("contribution-challenge").hidden = false; byId("contribution-email-input").focus(); });
byId("contribution-signout").addEventListener("click", async () => {
  const button = byId("contribution-signout");
  button.disabled = true;
  authRevision++;
  byId("contribution-fields").disabled = byId("contribution-reload").disabled = true;
  try {
    await post("/api/mail/logout", {});
    config = null;
    byId("contribution-list").replaceChildren();
    byId("contribution-form").reset();
    byId("contribution-status").textContent = "";
    message("contribution-list-status", "Verify your inbox to see your private submissions.");
    await refreshAuth();
  }
  catch (error) { message("contribution-auth-status", error.message, true); }
  finally { button.disabled = false; updateAvailability(); }
});
byId("contribution-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selected || !config?.verified) return;
  const revision = authRevision;
  const submittedArticleId = selected.id;
  byId("contribution-submit").disabled = true;
  try {
    const data = await post("/api/mail/contributions", { article_id: selected.id,
      author_name: byId("contribution-author").value.trim(), body_markdown: byId("contribution-body").value,
      permission_evidence: byId("contribution-evidence").value.trim(), grant_permission: byId("contribution-grant").checked,
      terms_version: config.terms_version });
    if (revision !== authRevision) return;
    message("contribution-status", data.message);
    if (selected?.id === submittedArticleId) byId("contribution-grant").checked = false;
    await loadOwn();
  } catch (error) { if (revision === authRevision) message("contribution-status", error.message, true); }
  finally { byId("contribution-submit").disabled = false; }
});

function card(row, owner) {
  const item = node("article", "", "submission-card");
  item.append(node("h3", row.author_name), node("p", `${row.state} · Submitted ${new Date(row.created * 1000).toLocaleString()}`), link(row.article_url, "Original article ↗"));
  if (owner) item.append(node("p", `Verified inbox: ${row.verified_email}`));
  if (row.review_note) item.append(node("p", `Editorial note: ${row.review_note}`));
  const actions = node("div", "", "submission-actions");
  const view = node("button", owner ? "Review submission" : "View submitted text", "button secondary"); view.type = "button";
  view.addEventListener("click", async () => {
    const revision = owner ? ownerRevision : authRevision;
    const current = () => revision === (owner ? ownerRevision : authRevision);
    view.disabled = true;
    try {
      const data = await request(`${owner ? "/api/admin/contributions" : "/api/mail/contributions"}/${row.id}`, owner ? { headers: ownerHeaders() } : {});
      if (!current()) return;
      item.querySelector(".submission-detail")?.remove();
      const detail = node("div", "", "submission-detail");
      detail.append(node("h4", "Permission evidence"), node("p", data.permission_evidence));
      const preview = node("div", "", "submission-preview"); preview.append(...readingContent(data.preview_html));
      detail.append(node("h4", "Reading preview"), preview);
      const raw = node("details", ""); raw.append(node("summary", "Submitted Markdown"), node("pre", data.body_markdown)); detail.append(raw);
      if (data.events?.length) {
        const history = node("details", ""), list = node("ol", ""); history.append(node("summary", "Review history"));
        for (const entry of data.events) list.append(node("li", `${entry.action} · ${entry.actor} · ${new Date(entry.at * 1000).toLocaleString()}${entry.note ? ` — ${entry.note}` : ""}`));
        history.append(list); detail.append(history);
      }
      if (owner && ["pending", "approved"].includes(data.state)) detail.append(reviewForm(data));
      item.append(detail);
    } catch (error) { if (current()) message(owner ? "editor-status" : "contribution-list-status", error.message, true); }
    finally { view.disabled = false; }
  });
  actions.append(view);
  if (!owner && ["pending", "approved"].includes(row.state)) {
    const withdraw = node("button", "Withdraw permission", "text-button"); withdraw.type = "button";
    withdraw.addEventListener("click", async () => {
      const revision = authRevision;
      withdraw.disabled = true;
      try {
        await post(`/api/mail/contributions/${row.id}/withdraw`, {});
        if (revision !== authRevision) return;
        await loadOwn();
        if (revision === authRevision) message("contribution-list-status", "Permission withdrawn. Future full-text delivery is disabled.");
      } catch (error) {
        if (revision === authRevision) message("contribution-list-status", error.message, true);
      } finally { withdraw.disabled = false; }
    });
    actions.append(withdraw);
  }
  item.append(actions); return item;
}

async function loadOwn() {
  const revision = authRevision;
  try { const data = await request("/api/mail/contributions"); if (revision !== authRevision || !config?.verified) return; byId("contribution-list").replaceChildren(...data.submissions.map((row) => card(row, false))); message("contribution-list-status", data.submissions.length ? `${data.submissions.length} recent submissions` : "No submissions yet. Your text stays private until approved."); }
  catch (error) { if (revision === authRevision) message("contribution-list-status", error.message, true); }
}
byId("contribution-reload").addEventListener("click", loadOwn);

function reviewForm(row) {
  const form = node("form", "");
  const actionId = `review-action-${row.id}`, noteId = `review-note-${row.id}`, verifiedId = `review-verified-${row.id}`;
  const actionLabel = node("label", "Editorial decision"); actionLabel.htmlFor = actionId;
  const action = document.createElement("select"); action.id = actionId; action.required = true;
  const options = row.state === "approved" ? [["revoke", "Revoke full-text access"]] : [["", "Choose a decision"], ["approve", "Approve reading permission"], ["reject", "Reject submission"]];
  for (const [value, label] of options) { const option = node("option", label); option.value = value; action.append(option); }
  const noteLabel = node("label", "Review note"); noteLabel.htmlFor = noteId;
  const note = document.createElement("textarea"); note.id = noteId; note.required = true; note.minLength = 10; note.maxLength = 1000; note.rows = 3;
  const grant = node("label", "", "permission-check"); grant.htmlFor = verifiedId;
  const verified = document.createElement("input"); verified.type = "checkbox"; verified.id = verifiedId;
  grant.append(verified, document.createTextNode("I have independently verified the rights holder's permission and reviewed the submitted text."));
  action.addEventListener("change", () => { verified.required = action.value === "approve"; });
  const button = node("button", "Save editorial decision", "button primary"); button.type = "submit";
  form.append(actionLabel, action, noteLabel, note, grant, button);
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); const revision = ownerRevision; button.disabled = true;
    try { await post(`/api/admin/contributions/${row.id}/review`, { action: action.value, note: note.value.trim(), permission_verified: verified.checked }, ownerHeaders()); if (revision === ownerRevision) { await loadQueue(); message("editor-status", "Editorial decision saved."); } }
    catch (error) { message("editor-status", error.message, true); }
    finally { button.disabled = false; }
  });
  return form;
}

async function loadQueue(append = false) {
  if (!ownerKey) return;
  const revision = ownerRevision, params = new URLSearchParams({ state: byId("editor-state").value });
  if (append && nextCursor) params.set("cursor", nextCursor);
  byId("editor-more").disabled = true;
  try {
    const data = await request(`/api/admin/contributions?${params}`, { headers: ownerHeaders() });
    if (revision !== ownerRevision || !ownerKey) return;
    if (!append) byId("editor-list").replaceChildren();
    byId("editor-list").append(...data.submissions.map((row) => card(row, true)));
    nextCursor = data.next_cursor;
    byId("editor-more").hidden = !nextCursor; byId("editor-controls").hidden = false;
    message("editor-status", data.submissions.length ? "Review the permission evidence and full text before approving." : "No submissions in this status.");
  } catch (error) { message("editor-status", error.message, true); }
  finally { byId("editor-more").disabled = false; }
}
byId("editor-login").addEventListener("submit", (event) => { event.preventDefault(); ownerKey = byId("editor-token").value.trim(); byId("editor-token").value = ""; ownerRevision++; loadQueue(); });
byId("editor-state").addEventListener("change", () => { ownerRevision++; loadQueue(); });
byId("editor-refresh").addEventListener("click", () => loadQueue());
byId("editor-more").addEventListener("click", () => loadQueue(true));
byId("editor-signout").addEventListener("click", () => { ownerKey = ""; ownerRevision++; nextCursor = null; byId("editor-list").replaceChildren(); byId("editor-controls").hidden = byId("editor-more").hidden = true; message("editor-status", "Owner workspace locked."); });

const articleParam = new URLSearchParams(location.search).get("article");
if (articleParam && /^[A-Za-z0-9_-]{1,40}$/.test(articleParam)) { byId("contribution-article").value = articleParam; findArticle(); }
refreshAuth();
