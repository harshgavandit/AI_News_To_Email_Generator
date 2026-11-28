import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { JSDOM } from "jsdom";
import { mountAsk, readDeepResponse } from "../../public/ask.js";

const answer = {
  status: "answered",
  summary: "The first report was published. [1]",
  sections: [{ heading: "Key developments", text: "The first report was published. [1]", citations: [1] }],
  timeline: [{ date: "2026-01-04", event: "The first report was published. [1]", citations: [1] }],
  citations: [{ n: 1, id: "story-a", url: "https://getinformdaily.com/?article=story-a#reading-room", publisher: "Example", title: "First report" }],
  checks: { sourced: true, quotes_verified: true, links_clean: true },
};

function sse(frames) {
  const bytes = new TextEncoder().encode(frames.map(([type, data]) => "event: " + type + "\r\ndata: " + JSON.stringify(data) + "\r\n\r\n").join(""));
  return new Response(new ReadableStream({
    start(controller) {
      for (let i = 0; i < bytes.length; i += 7) controller.enqueue(bytes.slice(i, i + 7));
      controller.close();
    },
  }), { headers: { "Content-Type": "text/event-stream" } });
}

test("Deep Ask parses split SSE frames, progress, and final JSON", async () => {
  const steps = [];
  const response = sse([["step", { message: "Searching 2 of 4…" }], ["done", answer]]);
  assert.deepEqual(await readDeepResponse(response, message => steps.push(message)), answer);
  assert.deepEqual(steps, ["Searching 2 of 4…"]);
  assert.deepEqual(await readDeepResponse(Response.json(answer), () => assert.fail("No progress expected")), answer);
});

for (const page of ["ask", "index"]) {
  test(page + " sends Deep research with a month window, renders the timeline, and reports deep mode", async () => {
    const html = readFileSync(new URL("../../public/" + page + ".html", import.meta.url), "utf8");
    const dom = new JSDOM(html);
    const old = globalThis.document;
    globalThis.document = dom.window.document;
    try {
      const root = document.querySelector("[data-ask]");
      const reports = [];
      const usage = [];
      let resolveFinish;
      const finished = new Promise(resolve => { resolveFinish = resolve; });
      mountAsk(root, {
        fetcher: async (path, options) => {
          assert.equal(path, "/api/ask/deep");
          assert.equal(options.headers.Accept, "text/event-stream");
          assert.deepEqual(JSON.parse(options.body), { question: "What happened to the chips?", days: 30 });
          return sse([["step", { message: "Planning…" }], ["done", answer]]);
        },
        track: (...event) => {
          usage.push(event);
          if (event[1] !== "question") resolveFinish();
        },
        report: async payload => { reports.push(payload); },
      });
      const deep = root.querySelector('input[value="deep"]');
      deep.checked = true;
      deep.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      root.querySelector('[name="question"]').value = "What happened to the chips?";
      root.querySelector("form").dispatchEvent(new dom.window.Event("submit", { cancelable: true }));
      assert.equal(root.querySelector("[data-ask-status]").textContent, "Planning…");
      await finished;
      assert.match(root.querySelector("[data-ask-status]").textContent, /report ready/i);
      assert.equal(root.querySelector(".source-checked").textContent, "Source-checked");
      assert.equal(root.querySelector("time").dateTime, "2026-01-04");
      assert.equal(root.querySelector(".deep-report p a").href, answer.citations[0].url);
      root.querySelector(".deep-report button").click();
      await Promise.resolve();
      assert.equal(reports.length, 1);
      assert.deepEqual(reports[0], { kind: "ai_answer", mode: "deep", question: "What happened to the chips?", story_ids: ["story-a"] });
      assert.deepEqual(usage, [["deep_ask", "question"], ["deep_ask", "answered"]]);
    } finally {
      globalThis.document = old;
      dom.window.close();
    }
  });
}

test("a stream error becomes an unavailable result and interrupted streams surface an error", async () => {
  const result = { status: "insufficient", reason: "unavailable", summary: "Deep research is temporarily unavailable." };
  assert.deepEqual(await readDeepResponse(sse([["error", result]]), () => {}), result);
  await assert.rejects(readDeepResponse(sse([]), () => {}), /ended without a report/);
});
