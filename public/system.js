"use strict";

/*
 * Informa AI design-system behaviours. Progressive enhancement only: every page
 * works without this file, and nothing here changes data or application state.
 */
(() => {
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const frame = (fn) => {
    let queued = false;
    return (...args) => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => { queued = false; fn(...args); });
    };
  };

  // Reading progress hairline and back-to-top control.
  const progress = document.createElement("div");
  progress.className = "sys-progress";
  progress.setAttribute("aria-hidden", "true");
  const top = document.createElement("button");
  top.type = "button";
  top.className = "sys-top";
  top.setAttribute("aria-label", "Back to top");
  top.innerHTML = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 16V4M4.5 9.5 10 4l5.5 5.5"/></svg>';
  top.addEventListener("click", () => {
    scrollTo({ top: 0, behavior: reduceMotion.matches ? "auto" : "smooth" });
  });
  const update = frame(() => {
    const max = document.documentElement.scrollHeight - innerHeight;
    const ratio = max > 0 ? Math.min(1, scrollY / max) : 0;
    progress.style.setProperty("--sys-scroll", ratio.toFixed(4));
    top.dataset.visible = String(scrollY > innerHeight * 1.2);
  });
  document.body.append(progress, top);
  addEventListener("scroll", update, { passive: true });
  addEventListener("resize", update, { passive: true });
  update();

  // Toasts give sighted readers the confirmation that screen readers already get.
  const region = document.createElement("div");
  region.className = "sys-toast-region";
  document.body.append(region);
  const toast = (message, ms = 2600) => {
    if (!message) return;
    while (region.children.length > 2) region.firstChild.remove();
    const item = document.createElement("div");
    item.className = "sys-toast";
    item.textContent = message;
    region.append(item);
    setTimeout(() => {
      item.dataset.leaving = "";
      setTimeout(() => item.remove(), 220);
    }, ms);
  };
  window.informaToast = toast;
  const actionStatus = document.getElementById("story-action-status");
  if (actionStatus) {
    let last = "";
    new MutationObserver(() => {
      const text = actionStatus.textContent.trim();
      if (text && text !== last) toast(text);
      last = text;
    }).observe(actionStatus, { childList: true, characterData: true, subtree: true });
  }

  // Story cards: staggered entrance index and a cursor-following highlight.
  const stories = document.getElementById("stories");
  if (stories) {
    const indexCards = () => {
      let i = 0;
      for (const card of stories.children) card.style.setProperty("--sys-i", String(i++));
    };
    new MutationObserver(indexCards).observe(stories, { childList: true });
    indexCards();
    if (matchMedia("(hover: hover) and (pointer: fine)").matches && !reduceMotion.matches) {
      const move = frame((event) => {
        const card = event.target.closest?.(".story");
        if (!card) return;
        const box = card.getBoundingClientRect();
        card.style.setProperty("--mx", `${event.clientX - box.left}px`);
        card.style.setProperty("--my", `${event.clientY - box.top}px`);
      });
      stories.addEventListener("pointermove", move, { passive: true });
    }
  }

  // Feature cards lean a few degrees toward the pointer.
  const TILT = ".about-note, .edition-coverage";
  if (matchMedia("(hover: hover) and (pointer: fine)").matches && !reduceMotion.matches) {
    for (const card of document.querySelectorAll(TILT)) card.dataset.sysTilt = "";
    const tilt = frame((event) => {
      const card = event.target.closest?.("[data-sys-tilt]");
      if (!card) return;
      const box = card.getBoundingClientRect();
      const x = (event.clientX - box.left) / box.width - .5;
      const y = (event.clientY - box.top) / box.height - .5;
      card.dataset.tilting = "";
      card.style.setProperty("--tx", `${(x * 5).toFixed(2)}deg`);
      card.style.setProperty("--ty", `${(-y * 5).toFixed(2)}deg`);
    });
    document.addEventListener("pointermove", tilt, { passive: true });
    document.addEventListener("pointerout", (event) => {
      const card = event.target.closest?.("[data-sys-tilt]");
      if (!card || card.contains(event.relatedTarget)) return;
      delete card.dataset.tilting;
      card.style.setProperty("--tx", "0deg");
      card.style.setProperty("--ty", "0deg");
    }, { passive: true });
  }

  // "/" focuses story search, matching the convention of other reading tools.
  addEventListener("keydown", (event) => {
    if (event.key !== "/" || event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
    const target = event.target;
    if (target?.closest?.("input, textarea, select, [contenteditable], dialog[open]")) return;
    const search = document.getElementById("search");
    if (!search || search.offsetParent === null) return;
    event.preventDefault();
    search.focus();
    search.select();
  });
})();
