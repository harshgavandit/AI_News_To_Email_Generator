import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { JSDOM } from "jsdom";
import { mountAsk } from "../../public/ask.js";

const html = readFileSync(new URL("../../public/ask.html", import.meta.url), "utf8");

for (const mode of ["answered", "refused", "insufficient", "rate-limit", "unavailable"]) {
  test(`Ask Informa renders ${mode} and re-enables the form`, async () => {
    const dom = new JSDOM(html);
    const old = globalThis.document;
    globalThis.document = dom.window.document;
    try {
      const root = document.querySelector("[data-ask]");
      const request = new Response(JSON.stringify({
        status: mode, answer: mode === "answered" ? "Service returned at noon. [1]" : "Fixed message.",
        citations: [{ n: 1, id: "story-1", url: "https://example.org/story", title: "Restored", publisher: "Example Press" }],
        checks: { sourced: true, quotes_verified: true, links_clean: true },
      }), { status: mode === "rate-limit" ? 429 : mode === "unavailable" ? 503 : 200 });
      const usage = [];
      let complete;
      const submitted = new Promise(resolve => { complete = resolve; });
      mountAsk(root, { fetcher: async (url, options) => {
        assert.equal(url, "/api/ask");
        assert.equal(JSON.parse(options.body).days, 7);
        return request;
      }, track: (...event) => { usage.push(event); if (event[1] !== "question") complete(); } });
      root.querySelector("[data-ask-example]").click();
      assert.match(root.querySelector("textarea").value, /AI coding/);
      root.querySelector("form").dispatchEvent(new dom.window.Event("submit", { cancelable: true }));
      assert.equal(root.querySelector("[type=submit]").disabled, true);
      await submitted;
      const status = root.querySelector("[data-ask-status]").textContent;
      assert.match(status, mode === "answered" ? /Answer ready/ : mode === "rate-limit" ? /question limit/ : mode === "unavailable" ? /temporarily unavailable/ : /Fixed message/);
      assert.equal(Boolean(root.querySelector(".source-checked")), mode === "answered");
      assert.equal(root.querySelector("[type=submit]").disabled, false);
      assert.ok(usage.every(event => event.length === 2 && event[0] === "ask_informa"));
    } finally {
      globalThis.document = old;
      dom.window.close();
    }
  });
}
