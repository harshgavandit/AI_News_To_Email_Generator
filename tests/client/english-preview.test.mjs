import assert from "node:assert/strict";
import test from "node:test";
import { previewSegments, translatePreview } from "../../public/english-preview.js";

test("preview translates only the non-English parts and preserves the original story", async () => {
  const story = { title: "New software release", language: "en", excerpt_language: "pt-BR" };
  const segments = previewSegments(story, "O lançamento agora está disponível.");
  const calls = [];
  const translator = {
    async create({ sourceLanguage, targetLanguage }) {
      calls.push([sourceLanguage, targetLanguage]);
      return {
        async translate(text) { calls.push(text); return "The release is now available."; },
        destroy() { calls.push("destroy"); },
      };
    },
  };
  const result = await translatePreview(segments, { translator, signal: new AbortController().signal });
  assert.deepEqual(result, [{ text: story.title, language: "en" }, { text: "The release is now available.", language: "en" }]);
  assert.deepEqual(calls, [["pt", "en"], "O lançamento agora está disponível.", "destroy"]);
  assert.equal(story.excerpt_language, "pt-BR");
});

test("leaving a story aborts the preview and releases the translator", async () => {
  const controller = new AbortController();
  let destroyed = false;
  const translator = { async create() {
    return { async translate() { controller.abort(); return "late result"; }, destroy() { destroyed = true; } };
  } };
  await assert.rejects(translatePreview([{ text: "Article en français", language: "fr" }], {
    translator, signal: controller.signal,
  }), { name: "AbortError" });
  assert.equal(destroyed, true);
});
