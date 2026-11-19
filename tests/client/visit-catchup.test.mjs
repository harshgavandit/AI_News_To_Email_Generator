import assert from "node:assert/strict";
import test from "node:test";
import { setImmediate } from "node:timers/promises";
import { JSDOM } from "jsdom";
import { createVisitCatchup } from "../../public/visit-catchup.js";

const as_of = "2026-11-18T10:00:00Z";
const since = "2026-11-17T10:00:00Z";
const evidence = [{
  id: "news-a", title: "<img src=x> Publisher updates its announcement", publisher: "A Publisher",
  url: "https://publisher.example/reports/a", published_at: "2026-11-15T16:00:00Z", language: "en",
  change_type: "event_update", observed_at: "2026-11-18T09:12:00Z", update_reason: "source_revision",
  excerpt: "The publisher described the updated announcement.",
}];
const firstVisit = { since, as_of, window: "first_visit", evidence, answer: null, notice: "Publisher evidence can be incomplete." };

function mount(options, url = "https://informa.test/") {
  const { window } = new JSDOM(`<section id="visit-catchup" class="visit-catchup" aria-labelledby="visit-catchup-title" hidden>
    <h3 id="visit-catchup-title">What changed?</h3><div id="visit-catchup-content"></div></section>`, { url });
  const region = window.document.getElementById("visit-catchup");
  return { region, window, catchup: createVisitCatchup({ region, ...options }) };
}

test("first visit opens source evidence and requests AI only on demand with the original window", async () => {
  const requests = [];
  const opened = [];
  const { region, window, catchup } = mount({
    async request(path, options) {
      assert.equal(path, "/api/intelligence/visit-catchup");
      assert.equal(options.method, "POST");
      const body = JSON.parse(options.body);
      requests.push(body);
      if (!body.analyze) return firstVisit;
      return { ...firstVisit, window: "since_visit", answer: { status: "answered", limitations: "Based on the cited report.", claims: [
        {kind: "analysis", text: "The update clarifies the earlier announcement.", source_ids: ["news-a"], quotes: [evidence[0].excerpt]},
        {kind: "analysis", text: "This has an unsupported citation.", source_ids: ["missing"]},
      ] } };
    },
    async openArticle(id, trigger) { opened.push([id, trigger]); },
  }, "https://informa.test/?view=catchup&window=90d");
  try {
    catchup.show({ until: as_of });
    assert.equal(region.hidden, false);
    assert.match(region.querySelector("[role=status]").textContent, /Checking the archive/);
    await setImmediate();
    assert.deepEqual(requests, [{ since: null, as_of, analyze: false }]);
    assert.equal(region.querySelector("h3").textContent, "Your first catch-up");
    const row = region.querySelector(".visit-catchup-entry");
    assert.equal(row.querySelector("img"), null);
    assert.match(row.textContent, /Developing story.*The publisher revised this report/);
    assert.equal(row.querySelector("time").dateTime, evidence[0].published_at);
    assert.equal(row.querySelector(".visit-catchup-observed").dateTime, evidence[0].observed_at);
    const reader = row.querySelector(".visit-catchup-reader");
    assert.equal(reader.getAttribute("href"), "https://informa.test/?view=catchup&window=90d&article=news-a#reading-room");
    reader.click();
    await setImmediate();
    assert.deepEqual(opened, [["news-a", reader]]);
    region.querySelector(".visit-catchup-actions button").click();
    await setImmediate();
    assert.deepEqual(requests[1], { since, as_of, analyze: true });
    assert.equal(region.querySelector("h3").textContent, "Your first catch-up");
    assert.equal(region.querySelectorAll(".visit-catchup-claim").length, 1);
    assert.equal(region.querySelector(".visit-catchup-claim a").getAttribute("href"), evidence[0].url);
    assert.equal(region.querySelector(".visit-catchup-claim time").dateTime, evidence[0].published_at);
    assert.equal(region.querySelector(".visit-catchup-claim blockquote").textContent, evidence[0].excerpt);
    [...region.querySelectorAll("button")].find(button => button.textContent === "Check for updates").click();
    await setImmediate();
    assert.deepEqual(requests[2], { since: null, as_of, analyze: false });
    assert.equal(region.querySelectorAll(".visit-catchup-claim").length, 0);
  } finally { window.close(); }
});

test("catch-up retry, AI failure, and unavailable storage preserve their own states", async () => {
  let attempts = 0;
  const { region, window, catchup } = mount({
    async request(_path, {body}) {
      const input = JSON.parse(body);
      assert.equal(input.since, input.analyze ? since : null);
      if (++attempts === 1) throw new Error("unavailable");
      if (input.analyze) throw new Error("AI unavailable");
      return firstVisit;
    },
    async openArticle() { throw new Error("Article no longer retained"); },
  });
  try {
    const status = region.querySelector(".visit-catchup-status");
    catchup.show({ since, until: as_of, persistent: false });
    await setImmediate();
    assert.match(status.textContent, /could not be loaded/);
    assert.equal(region.querySelector("h3").textContent, "Your 24-hour catch-up");
    assert.match(region.querySelector(".visit-catchup-note").textContent, /could not save visit history/);
    const [analyze, retry] = region.querySelectorAll("button");
    retry.click();
    await setImmediate();
    assert.equal(retry.hidden, true);
    assert.match(status.textContent, /1 development/);
    analyze.click();
    await setImmediate();
    assert.match(status.textContent, /source evidence is still available/);
    assert.ok(region.querySelector(".visit-catchup-entry"));
    assert.equal(analyze.disabled, false);
    region.querySelector(".visit-catchup-reader").click();
    await setImmediate();
    assert.match(region.querySelector(".visit-catchup-reader-status").textContent, /reader could not be opened/);
  } finally { window.close(); }
});

test("leaving cancels a stale request and the replacement period can show an empty result", async () => {
  let currentSignal, complete;
  let requests = 0;
  const { region, window, catchup } = mount({
    request(_path, {signal}) {
      if (++requests > 1) return Promise.resolve({ ...firstVisit, window: "clamped", evidence: [] });
      currentSignal = signal;
      return new Promise(resolve => { complete = resolve; });
    },
  });
  try {
    catchup.show({ until: as_of });
    catchup.hide();
    assert.equal(region.hidden, true);
    assert.equal(currentSignal.aborted, true);
    catchup.show({ since: "2026-11-01T00:00:00Z", until: as_of });
    complete(firstVisit);
    await setImmediate();
    assert.equal(requests, 2);
    assert.match(region.querySelector(".visit-catchup-note").textContent, /seven-day limit/);
    assert.match(region.querySelector(".visit-catchup-status").textContent, /No developments/);
    assert.equal(region.querySelector("button").hidden, true);
    assert.equal(region.querySelector(".visit-catchup-entry"), null);
  } finally { window.close(); }
});
