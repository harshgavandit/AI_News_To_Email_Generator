// Construct allowed elements explicitly. Raw source HTML never enters the live DOM.
export function readingContent(html) {
  const parsed = new DOMParser().parseFromString(String(html).slice(0, 180000), "text/html");
  const allowed = new Set(["P", "H2", "H3", "H4", "H5", "H6", "UL", "OL", "LI", "BLOCKQUOTE", "PRE", "CODE", "EM", "STRONG", "A", "HR", "BR", "TABLE", "THEAD", "TBODY", "TR", "TH", "TD", "DEL"]);
  const blocked = new Set(["SCRIPT", "STYLE", "IFRAME", "OBJECT", "EMBED", "SVG", "MATH", "FORM", "IMG", "INPUT"]);
  function clean(source) {
    if (source.nodeType === Node.TEXT_NODE) return document.createTextNode(source.textContent);
    if (source.nodeType !== Node.ELEMENT_NODE || blocked.has(source.tagName)) return document.createDocumentFragment();
    const target = allowed.has(source.tagName) ? document.createElement(source.tagName.toLowerCase()) : document.createDocumentFragment();
    if (source.tagName === "A") {
      try {
        const href = new URL(source.getAttribute("href"));
        if (href.protocol === "https:" && !href.username && !href.password && (!href.port || href.port === "443")) {
          target.href = href.href; target.target = "_blank"; target.rel = "noopener noreferrer";
        }
      } catch { /* Render unsafe links as ordinary text. */ }
    }
    for (const child of source.childNodes) target.append(clean(child));
    return target;
  }
  return [...parsed.body.childNodes].map(clean);
}
