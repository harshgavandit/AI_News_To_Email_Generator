import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { JSDOM } from "jsdom";

const html = readFileSync(new URL("../../public/admin-editor.html", import.meta.url), "utf8");
const script = readFileSync(new URL("../../public/admin-editor.js", import.meta.url), "utf8")
  .replace(/^import[^\r\n]*\r?\n/m, "").replace("export function", "function")
  .replace(/if \(typeof document.*startEditor\(\);/, "");
const flush = () => new Promise(resolve => setImmediate(resolve));
const id = "a".repeat(64);

test("owner queue keeps its key in memory and supports edits, approval and undo", async () => {
  const { window } = new JSDOM(html, { url: "https://informa.test/admin-editor.html", runScripts: "outside-only" });
  const doc = window.document;
  const requests = [];
  let status = "pending";
  const item = { id, kind: "labels", confidence: .96, status, mode: "heuristic", created: 1700000000,
    revision: 0, action: { story_id: "chip", labels: { topic: "chips" } },
    reason: ["Compare the source and archive labels.", "<script>untrusted</script>"], signal: "Topic mismatch",
    evidence: [{ id: "chip", title: "Chip report", url: "https://example.com/report", publisher: "Test", date: "2026-11-01" }] };
  window.node = (tag, label, css) => {
    const element = doc.createElement(tag);
    if (label != null) element.textContent = label;
    if (css) element.className = css;
    return element;
  };
  window.readableError = error => error.message;
  window.fetch = async (path, request) => {
    requests.push([path, request]);
    if (request.method === "POST") status = JSON.parse(request.body).action === "undo" ? "undone" : "approved";
    const data = { pending: status === "pending" ? 1 : 0,
      options: { topics: { chips: "Hardware" }, regions: { EU: "Europe" }, languages: { en: "English" } },
      items: status === "pending" ? [item] : [], bulk_confidence: .92,
      activity: status === "pending" ? [] : [{ kind: "labels", action: "approve", status, created: 1700000000,
        suggestion_id: id, revision: 1 }] };
    return { ok: true, json: async () => data };
  };
  const submit = form => form.dispatchEvent(new window.Event("submit", { cancelable: true }));
  try {
    window.eval(script + "\nstartEditor();");
    assert.equal(requests.length, 0);
    const login = doc.getElementById("editor-login");
    login.elements.key.value = "fixture-owner-input";
    submit(login);
    await flush();
    assert.equal(login.elements.key.value, "");
    assert.equal(window.localStorage.length, 0);
    const card = doc.querySelector("#editor-items article");
    assert.match(card.textContent, /Heuristic only/);
    assert.equal(card.querySelector("script"), null);
    assert.equal(card.querySelector("a").href, "https://example.com/report");
    const edit = card.querySelector("form");
    edit.elements.region.value = "EU";
    submit(edit);
    await flush();
    const approval = requests.find(([path]) => path.endsWith(id));
    assert.deepEqual(JSON.parse(approval[1].body), { action: "approve", revision: 0, edit: { topic: "chips", region: "EU" } });
    doc.querySelector("#editor-activity button").click();
    await flush();
    assert.deepEqual(JSON.parse(requests.filter(([path]) => path.endsWith(id))[1][1].body), { action: "undo", revision: 1 });
    doc.getElementById("editor-lock").click();
    assert.equal(doc.getElementById("editor-work").hidden, true);
    assert.equal(doc.getElementById("editor-activity").children.length, 0);
  } finally { window.close(); }
});
