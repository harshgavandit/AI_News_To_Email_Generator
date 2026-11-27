import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { renderCheckedAnswer } from "../../public/checked-answer.js";

test("checked answers render citation links and send an explicit report without contact data", async () => {
  const dom = new JSDOM("<div id='answer'></div>");
  const old = globalThis.document;
  globalThis.document = dom.window.document;
  try {
    const output = document.querySelector("#answer");
    const reports = [];
    const result = {
      status: "answered",
      answer: "Service returned at noon. [1]",
      citations: [{ n: 1, id: "story-1", publisher: "Example Press", title: "Service restored", url: "https://example.org/story" }],
      checks: { sourced: true, quotes_verified: true, links_clean: true },
    };
    assert.equal(renderCheckedAnswer(output, result, "When did service return?", { report: async payload => reports.push(payload) }), true);
    assert.equal(output.querySelector(".source-checked").textContent, "Source-checked");
    assert.equal(output.querySelector("p a").href, result.citations[0].url);
    assert.deepEqual(reports, []);
    output.querySelector("button").click();
    await Promise.resolve();
    assert.deepEqual(reports, [{ kind: "ai_answer", question: "When did service return?", story_ids: ["story-1"] }]);
    assert.equal(renderCheckedAnswer(output, { ...result, checks: { ...result.checks, sourced: false } }, "When?"), false);
    assert.equal(output.childElementCount, 0);
  } finally {
    globalThis.document = old;
    dom.window.close();
  }
});
