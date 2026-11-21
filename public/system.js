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

  const finePointer = matchMedia("(hover: hover) and (pointer: fine)").matches;
  const motionAllowed = () => !reduceMotion.matches;

  // The header gains a shadow once content scrolls beneath it.
  const markScrolled = frame(() => {
    if (scrollY > 8) document.documentElement.dataset.sysScrolled = "";
    else delete document.documentElement.dataset.sysScrolled;
  });
  addEventListener("scroll", markScrolled, { passive: true });
  markScrolled();

  // Story cards lean toward the pointer while a specular highlight follows it.
  if (stories && finePointer) {
    const lean = frame((event) => {
      if (!motionAllowed() || stories.classList.contains("story-list")) return;
      const card = event.target.closest?.(".story");
      if (!card || !stories.contains(card)) return;
      const box = card.getBoundingClientRect();
      const x = (event.clientX - box.left) / box.width - .5;
      const y = (event.clientY - box.top) / box.height - .5;
      card.dataset.tilting = "";
      card.style.setProperty("--tx", `${(x * 4).toFixed(2)}deg`);
      card.style.setProperty("--ty", `${(-y * 4).toFixed(2)}deg`);
    });
    stories.addEventListener("pointermove", lean, { passive: true });
    stories.addEventListener("pointerout", (event) => {
      const card = event.target.closest?.(".story");
      if (!card || card.contains(event.relatedTarget)) return;
      delete card.dataset.tilting;
      card.style.setProperty("--tx", "0deg");
      card.style.setProperty("--ty", "0deg");
    }, { passive: true });
  }

  // The masthead is a layered plate: it tilts slightly and its photograph moves behind the text.
  const masthead = document.querySelector(".desk-masthead");
  if (masthead) {
    if (finePointer) {
      const steer = frame((event) => {
        if (!motionAllowed()) return;
        const box = masthead.getBoundingClientRect();
        const x = (event.clientX - box.left) / box.width - .5;
        const y = (event.clientY - box.top) / box.height - .5;
        masthead.dataset.tilting = "";
        masthead.style.setProperty("--hx", `${(x * 2.4).toFixed(2)}deg`);
        masthead.style.setProperty("--hy", `${(-y * 2.4).toFixed(2)}deg`);
        masthead.style.setProperty("--px", `${(-x * 18).toFixed(1)}px`);
        masthead.style.setProperty("--py", `${(-y * 12).toFixed(1)}px`);
      });
      masthead.addEventListener("pointermove", steer, { passive: true });
      masthead.addEventListener("pointerleave", () => {
        delete masthead.dataset.tilting;
        for (const name of ["--hx", "--hy", "--px", "--py"]) masthead.style.removeProperty(name);
      });
    }
    const drift = frame(() => {
      if (!motionAllowed()) return;
      const box = masthead.getBoundingClientRect();
      if (box.bottom < 0 || box.top > innerHeight) return;
      masthead.style.setProperty("--hs", `${Math.max(-40, Math.min(40, -box.top * .12)).toFixed(1)}px`);
    });
    addEventListener("scroll", drift, { passive: true });
  }

  // Panels and cards below the fold rise into place when they first scroll into view.
  const REVEAL = [
    ".research-panel", ".information-card", ".priority-signals", ".curiosity-card", ".briefing-intro",
    ".source-row", ".directory-results-panel", ".creator-panel", ".contribution-panel", ".about-note",
    ".visit-catchup", ".coverage-overview", ".saved-library", ".site-footer",
  ].join(", ");
  if ("IntersectionObserver" in window) {
    const reveal = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting);
      visible.forEach((entry, index) => {
        const element = entry.target;
        reveal.unobserve(element);
        element.style.setProperty("--sys-ri", String(index));
        element.dataset.sysReveal = "shown";
        // Once settled, hand transforms back to the element's own hover styles.
        setTimeout(() => {
          delete element.dataset.sysReveal;
          element.style.removeProperty("--sys-ri");
        }, 1400);
      });
    }, { rootMargin: "0px 0px -6% 0px", threshold: .08 });
    const scan = frame(() => {
      if (!motionAllowed()) return;
      for (const element of document.querySelectorAll(REVEAL)) {
        if (element.dataset.sysRevealSeen !== undefined || element.closest("dialog, [hidden]")) continue;
        element.dataset.sysRevealSeen = "";
        // Only content that starts below the viewport is hidden; nothing visible ever blinks.
        if (element.getBoundingClientRect().top < innerHeight * .92) continue;
        element.dataset.sysReveal = "pending";
        reveal.observe(element);
      }
    });
    scan();
    new MutationObserver(scan).observe(document.body, { childList: true, subtree: true });
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
