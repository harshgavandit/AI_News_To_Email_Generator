function translatorLanguage(language) {
  if (language === "zh-TW") return "zh-Hant";
  return typeof language === "string" && /^[a-z]{2}(?:-[a-z0-9]+)*$/i.test(language)
    ? language.toLowerCase().split("-")[0] : "";
}

export function previewSegments(article, excerpt) {
  const titleLanguage = translatorLanguage(article.language);
  const excerptLanguage = translatorLanguage(article.excerpt_language) || titleLanguage;
  return [
    { text: article.title, language: titleLanguage },
    { text: excerpt, language: excerptLanguage },
  ];
}

export async function translatePreview(segments, { translator, signal }) {
  const translators = new Map();
  try {
    const translated = [];
    for (const { text, language } of segments) {
      signal.throwIfAborted();
      if (!text || !language || language === "en") {
        translated.push({ text, language });
        continue;
      }
      if (!translators.has(language)) {
        translators.set(language, await translator.create({ sourceLanguage: language, targetLanguage: "en", signal }));
      }
      const result = await translators.get(language).translate(text, { signal });
      signal.throwIfAborted();
      if (!result.trim()) throw new Error("Empty translation");
      translated.push({ text: result, language: "en" });
    }
    return translated;
  } finally {
    for (const instance of translators.values()) instance.destroy();
  }
}
