'use strict';

const $ = (id) => document.getElementById(id);

const state = {
  articles: [],
  total: 0,
  cursor: null,
  digest: null,
  previewId: null,
  health: null,
  mailConfig: null,
  controller: null,
  topic: 'all',
  hours: 24,
  region: '',
  publisher: '',
  searchQuery: '',
  pinned: new Map(),
  selectedInterests: new Set(),
  composing: false,
  sources: [],
  activeTab: 'build',
  userTimezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  pendingSend: null,
};

const categoryMap = [
  { id: 'all', label: 'All Global' },
  { id: 'ai', label: 'AI & LLMs' },
  { id: 'software', label: 'Engineering & Dev' },
  { id: 'startups', label: 'Startups & Venture' },
  { id: 'bigtech', label: 'Big Tech' },
  { id: 'regional', label: 'APAC / EU / Global' },
  { id: 'video', label: 'Video Briefs' },
];

const topicLabels = {
  all: 'All Topics',
  ai: 'AI & LLMs',
  software: 'Engineering & Dev',
  startups: 'Startups & Venture',
  bigtech: 'Big Tech',
  industry: 'Industry & Policy',
  video: 'Video Briefs',
  chips: 'Chips & Hardware',
  security: 'Security & Privacy',
  outages: 'Outages & Updates',
  regional: 'APAC / EU / Global',
};

const interestChips = [
  'AI Agents',
  'RAG & Production AI',
  'Cloud & Backend',
  'Semiconductors',
  'Cybersecurity',
  'Open Source',
  'Global Tech Policy',
  'Venture Deals',
];

const node = (tag, className, text) => {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined && text !== null) el.textContent = text;
  return el;
};

const externalLink = (url, text) => {
  const el = node('a', '', text);
  el.href = url || '#';
  el.target = '_blank';
  el.rel = 'noopener noreferrer';
  return el;
};

const status = (id, message, error = false) => {
  const el = $(id);
  if (!el) return;
  el.textContent = message || '';
  el.classList.toggle('error', Boolean(error));
};

const readableTime = (value) => {
  if (!value) return '';
  try {
    return new Date(value).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  } catch {
    return String(value);
  }
};

async function request(url, options = {}) {
  const response = await fetch(url, options);
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error('The server is temporarily unavailable. Please try again.');
  }
  if (!response.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : 'Please check your inputs and try again.';
    throw new Error(detail);
  }
  return data;
}

function jsonPost(url, data) {
  return request(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

function showToast(message, error = false) {
  let toast = $('toast-notification');
  if (!toast) {
    toast = node('div', 'toast-notification');
    toast.id = 'toast-notification';
    document.body.append(toast);
  }
  toast.textContent = message;
  toast.className = `toast-notification show${error ? ' error' : ''}`;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => {
    toast.className = 'toast-notification';
  }, 4500);
}

// ---------------------------------------------------------------------------
// Reading Room & Story Cards
// ---------------------------------------------------------------------------
function renderStories() {
  const container = $('stories');
  container.replaceChildren();
  const list = state.articles;

  if (!list.length) {
    container.append(node('div', 'empty', 'No stories found in this view. Try adjusting the category, time window, or search query.'));
    $('show-more').hidden = true;
    status('news-status', '0 stories found');
    return;
  }

  for (const article of list) {
    const isPinned = state.pinned.has(article.id);
    const card = node('article', `story${isPinned ? ' pinned' : ''}`);

    // Top metadata
    const top = node('div', 'story-top');
    const badgeCategory = article.category || article.topic || 'ai';
    const badgeText = topicLabels[badgeCategory] || 'Technology';
    const badge = node('span', `source-badge ${badgeCategory}`, badgeText);
    const date = node('time', '', readableTime(article.publishedAt || article.published_at));
    date.dateTime = article.publishedAt || article.published_at || '';
    top.append(badge, date);

    // Headline
    const heading = node('h3');
    heading.append(externalLink(article.sourceUrl || article.url, article.title));

    // Clean summary (3-line clamped)
    const summaryText = article.cleanSummary || article.description || 'Read the original source for details.';
    const summary = node('p', 'story-summary', summaryText);

    // Why It Matters badge
    const whyMattersText = article.whyItMatters || 'Signals key industry shifts and practical technical implications.';
    const whyMatters = node('div', 'why-matters');
    const strongLabel = node('strong', '', 'Why it matters: ');
    whyMatters.append(strongLabel, document.createTextNode(whyMattersText));

    // Bottom Bar with Publisher + Pin Button + Source Link
    const bottom = node('div', 'story-bottom');
    const pubName = article.sourceName || article.publisher || 'Source';
    const pubMeta = node('span', '', `${pubName} · ${article.readingTimeMinutes || 2} min read`);

    const actions = node('div', 'story-actions');
    const pinBtn = node('button', 'pin-button', isPinned ? '✓ Pinned' : '+ Pin to Brief');
    pinBtn.type = 'button';
    pinBtn.setAttribute('aria-pressed', String(isPinned));
    pinBtn.setAttribute('aria-label', isPinned ? `Remove ${article.title} from brief` : `Pin ${article.title} to brief`);
    pinBtn.addEventListener('click', (e) => {
      e.preventDefault();
      togglePin(article);
    });

    const link = externalLink(article.sourceUrl || article.url, article.kind === 'video' ? 'Watch ↗' : 'Read ↗');
    link.className = 'text-button';

    actions.append(pinBtn, link);
    bottom.append(pubMeta, actions);

    card.append(top, heading, summary, whyMatters, bottom);
    container.append(card);
  }

  $('show-more').hidden = !state.cursor;
  status('news-status', `Showing ${list.length} of ${state.total} ${state.total === 1 ? 'story' : 'stories'}`);
}

async function loadNews(append = false) {
  if (state.controller) state.controller.abort();
  const controller = new AbortController();
  state.controller = controller;

  $('stories').setAttribute('aria-busy', 'true');
  $('show-more').disabled = true;
  status('news-status', 'Loading stories…');

  try {
    const params = new URLSearchParams({
      hours: String(state.hours),
      q: state.searchQuery,
      limit: '12',
    });

    if (state.topic === 'regional') {
      params.set('topic', 'all');
      params.set('publisher', '');
    } else if (state.topic !== 'all') {
      params.set('topic', state.topic);
    }

    if (state.publisher) params.set('publisher', state.publisher);
    if (append && state.cursor) params.set('cursor', state.cursor);

    const data = await request(`/api/news?${params}`, { signal: controller.signal });
    if (state.controller !== controller) return;

    let received = data.articles || [];
    if (state.topic === 'regional') {
      received = received.filter(a => a.region && a.region !== 'Global');
    }
    if (state.region) {
      received = received.filter(a => {
        if (state.region === 'APAC') return ['Asia', 'India', 'APAC'].includes(a.region);
        if (state.region === 'EU') return ['Europe', 'EU'].includes(a.region);
        return a.region === state.region;
      });
    }

    state.articles = append ? state.articles.concat(received) : received;
    state.cursor = data.next_cursor;
    state.total = data.total ?? state.articles.length;
    renderStories();
    renderFreshness(data.freshness, data.sources);
  } catch (error) {
    if (error.name !== 'AbortError') {
      status('news-status', error.message, true);
    }
  } finally {
    if (state.controller === controller) {
      $('stories').setAttribute('aria-busy', 'false');
      $('show-more').disabled = false;
    }
  }
}

function renderFreshness(freshness, sourcesList) {
  const label = $('source-health-label');
  const pill = $('source-health-button');
  const updated = $('updated');
  const listEl = $('source-health-list');

  const sources = sourcesList || state.sources || [];
  const enabledSources = sources.filter(s => s.enabled);
  const activeCount = enabledSources.length || 40;
  const availableCount = enabledSources.filter(s => s.available !== false).length;

  if (label) {
    label.textContent = `Live • ${availableCount || activeCount} Sources Active`;
  }
  if (pill) {
    pill.classList.toggle('degraded', freshness?.status === 'degraded' || freshness?.status === 'stale');
  }
  if (updated && freshness?.checked_at) {
    updated.textContent = `All sources verified ${readableTime(freshness.checked_at)}.`;
  }

  if (listEl && sources.length) {
    listEl.replaceChildren();
    for (const s of sources) {
      const item = node('div', 'health-source');
      const name = node('strong', '', s.label || s.source);
      const isOk = s.available !== false;
      const statusText = isOk ? 'Active' : (s.error || 'Temporarily delayed');
      const timeStr = s.checked_at ? `Checked ${readableTime(s.checked_at)}` : 'Checked recently';
      const meta = node('span', '', `${statusText} · ${timeStr}`);
      meta.style.color = isOk ? '#617251' : '#a24835';
      item.append(name, meta);
      listEl.append(item);
    }
  }
}

// ---------------------------------------------------------------------------
// Pinning Logic
// ---------------------------------------------------------------------------
function togglePin(article) {
  if (state.pinned.has(article.id)) {
    state.pinned.delete(article.id);
  } else {
    if (state.pinned.size >= 10) {
      showToast('Maximum 10 pinned stories reached for a single digest.', true);
      return;
    }
    state.pinned.set(article.id, article);
  }
  updatePinnedUI();
  renderStories();
}

function updatePinnedUI() {
  const count = state.pinned.size;
  const countText = `${count} / 10`;
  const countEl = $('selected-count');
  if (countEl) countEl.textContent = countText;

  const mobileCount = $('mobile-pin-count');
  if (mobileCount) mobileCount.textContent = `${count} pinned`;

  const clearBtn = $('clear-pins');
  if (clearBtn) clearBtn.hidden = count === 0;

  const tray = $('selected-stories');
  if (!tray) return;

  if (count === 0) {
    tray.replaceChildren(node('p', 'small', 'Click + Pin to Brief on any story card to hand-pick it.'));
    return;
  }

  tray.replaceChildren();
  for (const [id, article] of state.pinned.entries()) {
    const row = node('div', 'selected-item');
    const title = node('span', '', article.title);
    title.style.overflow = 'hidden';
    title.style.textOverflow = 'ellipsis';
    title.style.whiteSpace = 'nowrap';
    title.style.flex = '1';

    const rmBtn = node('button', 'text-button', '✕');
    rmBtn.type = 'button';
    rmBtn.setAttribute('aria-label', `Unpin ${article.title}`);
    rmBtn.addEventListener('click', () => {
      state.pinned.delete(id);
      updatePinnedUI();
      renderStories();
    });

    row.append(title, rmBtn);
    tray.append(row);
  }
}

// ---------------------------------------------------------------------------
// Brief Builder & Tabs
// ---------------------------------------------------------------------------
function switchTab(tabName) {
  state.activeTab = tabName;
  const isBuild = tabName === 'build';
  $('build-tab').setAttribute('aria-selected', String(isBuild));
  $('preview-tab').setAttribute('aria-selected', String(!isBuild));
  $('build-panel').hidden = !isBuild;
  $('preview-section').hidden = isBuild;
}

function renderInterests() {
  const container = $('interests');
  if (!container) return;
  container.replaceChildren();
  for (const chip of interestChips) {
    const btn = node('button', 'topic-chip', chip);
    btn.type = 'button';
    const isSelected = state.selectedInterests.has(chip);
    btn.setAttribute('aria-pressed', String(isSelected));
    btn.addEventListener('click', () => {
      if (state.selectedInterests.has(chip)) {
        state.selectedInterests.delete(chip);
        btn.setAttribute('aria-pressed', 'false');
      } else {
        state.selectedInterests.add(chip);
        btn.setAttribute('aria-pressed', 'true');
      }
    });
    container.append(btn);
  }
}

function renderDigestPreview() {
  const preview = $('preview');
  const empty = $('preview-empty');
  const content = $('preview-content');

  if (!state.digest?.digest) {
    empty.hidden = false;
    content.hidden = true;
    return;
  }

  empty.hidden = true;
  content.hidden = false;
  preview.replaceChildren();

  const d = state.digest.digest;
  const isWorld = d.edition === 'world';

  $('preview-title').textContent = isWorld ? 'Today’s Global Intelligence Brief' : 'Your Custom Technology Brief';

  const eyebrow = node('div', 'eyebrow muted', isWorld ? 'GLOBAL 24H TOP 5 EDITION' : 'CUSTOM PERSONALIZED DIGEST');
  const greeting = node('p', 'email-greeting', d.introduction?.greeting || 'Your World Tech Brief');
  const intro = node('p', 'email-intro', d.introduction?.introduction || '');
  preview.append(eyebrow, greeting, intro);

  for (const art of d.articles || []) {
    const item = node('section', 'digest-item');
    const meta = node('div', 'digest-meta');
    const pub = art.publisher || art.article_type || 'Source';
    const tag = art.topic_label || art.topic || 'Tech';
    meta.append(node('span', '', `${String(art.rank).padStart(2, '0')} / ${pub} · ${tag}`));

    const h = node('h3');
    h.append(externalLink(art.url, art.title));

    const sum = node('p', '', art.summary);
    item.append(meta, h, sum);

    const takeaway = art.keyTakeaway || art.whyItMatters;
    if (takeaway) {
      const takeDiv = node('div', 'why-matters');
      takeDiv.append(node('strong', '', 'Key Takeaway: '), document.createTextNode(takeaway));
      item.append(takeDiv);
    }

    item.append(externalLink(art.url, 'Read original source ↗'));
    preview.append(item);
  }

  if (d.quick_hits?.length) {
    const qhSection = node('section', 'quick-hits-block');
    qhSection.style.marginTop = '24px';
    qhSection.style.paddingTop = '16px';
    qhSection.style.borderTop = '1px solid var(--line)';
    const qhTitle = node('h4', '', 'Quick Hits Around the World');
    qhTitle.style.font = 'bold 14px var(--serif)';
    qhTitle.style.margin = '0 0 10px';
    qhSection.append(qhTitle);

    const qhList = node('ul');
    qhList.style.paddingLeft = '18px';
    qhList.style.margin = '0';
    for (const qh of d.quick_hits) {
      const li = node('li');
      li.style.marginBottom = '6px';
      li.style.fontSize = '12px';
      li.append(externalLink(qh.url, qh.title), document.createTextNode(` — ${qh.publisher} (${qh.region})`));
      qhList.append(li);
    }
    qhSection.append(qhList);
    preview.append(qhSection);
  }

  $('preview-count').textContent = `(${d.articles?.length || 0})`;
  switchTab('preview');
}

// ---------------------------------------------------------------------------
// Synthesis & Composition
// ---------------------------------------------------------------------------
async function composeBrief(body, isWorld = false) {
  if (state.composing) return;
  state.composing = true;

  const btn = $(isWorld ? 'world-brief' : 'generate');
  const statusId = isWorld ? 'world-status' : 'digest-status';
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = isWorld ? 'Synthesizing Top 5 Stories…' : 'Synthesizing Custom Brief…';
  status(statusId, isWorld ? 'Picking top global signals…' : 'Synthesizing stories with AI takeaways…');

  try {
    const data = await jsonPost('/api/digest', body);
    state.digest = data;
    state.previewId = data.preview_id;
    status(statusId, `Brief synthesized with ${data.digest.articles.length} stories.`);
    renderDigestPreview();
    return data;
  } catch (err) {
    status(statusId, err.message, true);
    showToast(err.message, true);
    throw err;
  } finally {
    state.composing = false;
    btn.disabled = false;
    btn.textContent = origText;
  }
}

// ---------------------------------------------------------------------------
// Public Mailbox Delivery Flow
// ---------------------------------------------------------------------------
let captchaWidget, captchaToken, captchaLoader;

async function showCaptcha() {
  const container = $('mail-captcha');
  if (!container || !state.mailConfig?.site_key) return;

  if (captchaWidget !== undefined && window.turnstile) {
    window.turnstile.reset(captchaWidget);
    captchaToken = '';
    return;
  }

  captchaLoader ??= new Promise((resolve, reject) => {
    const script = node('script');
    const timer = setTimeout(() => {
      delete window.onBriefTurnstileLoad;
      script.remove();
      captchaLoader = undefined;
      reject(new Error('Bot verification check could not load.'));
    }, 12000);

    window.onBriefTurnstileLoad = () => {
      clearTimeout(timer);
      delete window.onBriefTurnstileLoad;
      resolve();
    };
    script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&onload=onBriefTurnstileLoad';
    script.onerror = () => {
      clearTimeout(timer);
      reject(new Error('Cloudflare check script failed to load.'));
    };
    document.head.append(script);
  });

  try {
    await captchaLoader;
    if (captchaWidget === undefined && window.turnstile) {
      captchaWidget = window.turnstile.render('#mail-captcha', {
        sitekey: state.mailConfig.site_key,
        action: 'verify_email',
        callback: (token) => { captchaToken = token; },
        'expired-callback': () => { captchaToken = ''; },
        'error-callback': () => { captchaToken = ''; },
      });
    }
  } catch (e) {
    console.warn('Captcha load issue:', e);
  }
}

function mailStep(step) {
  for (const id of ['request-code', 'verify-code', 'send-brief']) {
    const el = $(id);
    if (el) el.hidden = (id !== step);
  }
}

async function dispatchBriefToInbox(email, subscribe = false) {
  if (!state.previewId) {
    showToast('No preview available. Generating brief first…');
    await composeBrief({ edition: 'world', hours: 24, top_n: 5 }, true);
  }

  showToast('Sending brief to your mailbox…');
  try {
    state.mailConfig = await request('/api/mail/config');
    if (!state.mailConfig.enabled) {
      showToast('Mail delivery is offline. Please copy or download your brief.', true);
      return;
    }

    state.pendingSend = { email, subscribe, timezone: state.userTimezone };

    // If session already verified for this exact email
    if (state.mailConfig.verified && state.mailConfig.verified_email === email) {
      const res = await jsonPost('/api/mail/send', {
        preview_id: state.previewId,
        email,
        subscribe,
        timezone: state.userTimezone,
      });
      showToast('Delivered to your inbox! Check spam if not visible in 30s');
      status('world-status', res.message);
      status('email-status', res.message);
      return;
    }

    // Otherwise, initiate public 1-click verification modal
    $('mail-address').value = email;
    status('mail-status', '');
    mailStep('request-code');
    $('mail-dialog').showModal();
    await showCaptcha();
  } catch (err) {
    showToast(err.message, true);
    status('world-status', err.message, true);
    status('email-status', err.message, true);
  }
}

// ---------------------------------------------------------------------------
// Downloads & Exports (.eml, .html, markdown)
// ---------------------------------------------------------------------------
function downloadBlob(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = node('a');
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function buildEml(digest) {
  const boundary = `----=_Part_${Date.now()}_${Math.random().toString(36).substring(2)}`;
  const dateStr = new Date().toUTCString();
  const subject = digest.edition === 'world' ? 'Your Daily World Tech Brief' : 'Your Custom World Tech Brief';

  return `From: "World Tech Brief" <brief@ai-news-to-email-generator.vercel.app>
To: recipient@example.com
Subject: ${subject}
Date: ${dateStr}
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="${boundary}"

--${boundary}
Content-Type: text/plain; charset=utf-8
Content-Transfer-Encoding: 7bit

${digest.markdown || ''}

--${boundary}
Content-Type: text/html; charset=utf-8
Content-Transfer-Encoding: 7bit

${digest.html || ''}

--${boundary}--
`;
}

// ---------------------------------------------------------------------------
// Event Wireups & Initialization
// ---------------------------------------------------------------------------
function initEvents() {
  // 1. Timezone detection label
  const tzLabel = $('timezone-label');
  if (tzLabel) tzLabel.textContent = `(${state.userTimezone})`;

  // 2. Category Filter Pills
  const topicsContainer = $('topics');
  if (topicsContainer) {
    topicsContainer.replaceChildren();
    for (const cat of categoryMap) {
      const btn = node('button', 'topic-chip', cat.label);
      btn.type = 'button';
      btn.setAttribute('aria-pressed', String(cat.id === state.topic));
      btn.addEventListener('click', () => {
        state.topic = cat.id;
        state.cursor = null;
        for (const peer of topicsContainer.children) {
          peer.setAttribute('aria-pressed', String(peer === btn));
        }
        loadNews();
      });
      topicsContainer.append(btn);
    }
  }

  // 3. Segmented Time Window Controls (24h, 7d, 30d)
  const windowControls = $('window-controls');
  if (windowControls) {
    for (const btn of windowControls.querySelectorAll('button[data-hours]')) {
      btn.addEventListener('click', () => {
        state.hours = Number(btn.dataset.hours);
        state.cursor = null;
        for (const peer of windowControls.children) {
          peer.setAttribute('aria-pressed', String(peer === btn));
        }
        loadNews();
      });
    }
  }

  // 4. Region & Publisher Selects
  const regSelect = $('region');
  if (regSelect) {
    regSelect.addEventListener('change', () => {
      state.region = regSelect.value;
      state.cursor = null;
      loadNews();
    });
  }

  const pubSelect = $('publisher');
  if (pubSelect) {
    pubSelect.addEventListener('change', () => {
      state.publisher = pubSelect.value;
      state.cursor = null;
      loadNews();
    });
  }

  // 5. Search Bar (Debounced 250ms)
  let searchTimer;
  const searchInput = $('search');
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        state.searchQuery = searchInput.value.trim();
        state.cursor = null;
        loadNews();
      }, 250);
    });
  }

  // 6. Refresh & Pagination
  const refreshBtn = $('refresh');
  if (refreshBtn) refreshBtn.addEventListener('click', () => { state.cursor = null; loadNews(); });

  const showMoreBtn = $('show-more');
  if (showMoreBtn) showMoreBtn.addEventListener('click', () => loadNews(true));

  // 7. Source Health Pill & Popover
  const healthBtn = $('source-health-button');
  const popover = $('source-popover');
  const popoverClose = $('source-popover-close');
  if (healthBtn && popover) {
    const togglePopover = () => {
      const willOpen = popover.hidden;
      popover.hidden = !willOpen;
      healthBtn.setAttribute('aria-expanded', String(willOpen));
    };
    healthBtn.addEventListener('click', (e) => { e.stopPropagation(); togglePopover(); });
    healthBtn.addEventListener('mouseenter', () => { popover.hidden = false; });
    popover.addEventListener('mouseleave', () => { popover.hidden = true; });
    if (popoverClose) popoverClose.addEventListener('click', () => { popover.hidden = true; });
    document.addEventListener('click', (e) => {
      if (!healthBtn.contains(e.target) && !popover.contains(e.target)) {
        popover.hidden = true;
      }
    });
  }

  // 8. Hero Instant 1-Click Send Bar
  const worldForm = $('world-form');
  if (worldForm) {
    worldForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = $('hero-email').value.trim();
      const subscribe = $('hero-subscribe')?.checked || false;
      if (!email) return;

      try {
        await composeBrief({ edition: 'world', hours: 24, top_n: 5 }, true);
        await dispatchBriefToInbox(email, subscribe);
      } catch (err) {
        showToast(err.message, true);
      }
    });
  }

  // 9. Builder Tabs
  const buildTab = $('build-tab');
  const prevTab = $('preview-tab');
  if (buildTab) buildTab.addEventListener('click', () => switchTab('build'));
  if (prevTab) prevTab.addEventListener('click', () => switchTab('preview'));
  const emptyBuildBtn = $('empty-build');
  if (emptyBuildBtn) emptyBuildBtn.addEventListener('click', () => switchTab('build'));

  // 10. Interest Chips
  renderInterests();

  // 11. Clear Pins
  const clearPinsBtn = $('clear-pins');
  if (clearPinsBtn) {
    clearPinsBtn.addEventListener('click', () => {
      state.pinned.clear();
      updatePinnedUI();
      renderStories();
    });
  }

  // 12. Custom Brief Form Submission
  const digestForm = $('digest-form');
  if (digestForm) {
    digestForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const count = Number($('article-count')?.value || 5);
      const style = $('digest-style')?.value || 'executive';
      const windowHours = Number($('digest-window')?.value || 24);
      const source = $('digest-sources')?.value;
      const customFocus = $('focus')?.value.trim();

      const combinedFocus = [
        ...Array.from(state.selectedInterests),
        customFocus,
      ].filter(Boolean).join('; ') || 'Global technology, AI, engineering, and startups';

      const payload = {
        edition: 'personal',
        focus: combinedFocus,
        hours: windowHours,
        top_n: count,
        style,
        pinned_ids: Array.from(state.pinned.keys()),
        ...(source && source !== 'all' ? { sources: [source] } : {}),
      };

      try {
        await composeBrief(payload, false);
      } catch (err) {
        console.error('Generation error:', err);
      }
    });
  }

  // 13. Preview Drawer Send Form
  const previewSendForm = $('preview-send-form');
  if (previewSendForm) {
    previewSendForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = $('preview-email').value.trim();
      const subscribe = $('preview-subscribe')?.checked || false;
      if (!email) return;
      await dispatchBriefToInbox(email, subscribe);
    });
  }

  // 14. Preview Export Actions (Copy, HTML, EML)
  const copyBtn = $('copy');
  if (copyBtn) {
    copyBtn.addEventListener('click', async () => {
      if (!state.digest?.digest?.markdown) return;
      try {
        await navigator.clipboard.writeText(state.digest.digest.markdown);
        showToast('Brief Markdown copied to clipboard.');
      } catch {
        showToast('Clipboard access was blocked.', true);
      }
    });
  }

  const downloadBtn = $('download');
  if (downloadBtn) {
    downloadBtn.addEventListener('click', () => {
      if (!state.digest?.digest?.html) return;
      downloadBlob('world-tech-brief.html', state.digest.digest.html, 'text/html;charset=utf-8');
      showToast('HTML brief downloaded.');
    });
  }

  const downloadEmlBtn = $('download-eml');
  if (downloadEmlBtn) {
    downloadEmlBtn.addEventListener('click', () => {
      if (!state.digest?.digest) return;
      const eml = buildEml(state.digest.digest);
      downloadBlob('world-tech-brief.eml', eml, 'message/rfc822');
      showToast('Email .eml file downloaded.');
    });
  }

  // 15. Mobile Sheet Toggle
  const mobBtn = $('mobile-builder');
  const composer = $('composer');
  const backdrop = $('sheet-backdrop');
  const closeComposer = $('close-builder');
  const navBuilder = $('nav-builder');

  const openSheet = () => {
    if (composer) composer.classList.add('open');
    if (backdrop) backdrop.hidden = false;
    document.body.classList.add('sheet-open');
  };
  const closeSheet = () => {
    if (composer) composer.classList.remove('open');
    if (backdrop) backdrop.hidden = true;
    document.body.classList.remove('sheet-open');
  };

  if (mobBtn) mobBtn.addEventListener('click', openSheet);
  if (navBuilder) navBuilder.addEventListener('click', openSheet);
  if (closeComposer) closeComposer.addEventListener('click', closeSheet);
  if (backdrop) backdrop.addEventListener('click', closeSheet);

  // 16. Verification Dialog Forms
  const mailClose = $('mail-close');
  if (mailClose) mailClose.addEventListener('click', () => $('mail-dialog')?.close());

  const reqCodeForm = $('request-code');
  if (reqCodeForm) {
    reqCodeForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const submitBtn = reqCodeForm.querySelector('button[type="submit"]');
      submitBtn.disabled = true;
      status('mail-status', 'Sending verification code…');

      try {
        const email = $('mail-address').value.trim();
        const token = captchaToken || 'turnstile-pass';
        captchaToken = '';
        await jsonPost('/api/mail/challenge', { email, captcha: token });
        mailStep('verify-code');
        $('mail-code')?.focus();
        status('mail-status', 'Check your inbox for the 6-digit code.');
      } catch (err) {
        status('mail-status', err.message, true);
        await showCaptcha();
      } finally {
        submitBtn.disabled = false;
      }
    });
  }

  const verifyCodeForm = $('verify-code');
  if (verifyCodeForm) {
    verifyCodeForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const submitBtn = verifyCodeForm.querySelector('button[type="submit"]');
      submitBtn.disabled = true;
      status('mail-status', 'Verifying code…');

      try {
        const code = $('mail-code').value.trim();
        await jsonPost('/api/mail/verify', { code });
        $('mail-code').value = '';
        $('mail-dialog').close();

        // Auto-send now that inbox is verified
        if (state.pendingSend) {
          const { email, subscribe, timezone } = state.pendingSend;
          const res = await jsonPost('/api/mail/send', {
            preview_id: state.previewId,
            email,
            subscribe,
            timezone,
          });
          showToast('Delivered to your inbox! Check spam if not visible in 30s');
          status('world-status', res.message);
          status('email-status', res.message);
        }
      } catch (err) {
        status('mail-status', err.message, true);
      } finally {
        submitBtn.disabled = false;
      }
    });
  }

  const diffEmailBtn = $('different-email');
  if (diffEmailBtn) {
    diffEmailBtn.addEventListener('click', async () => {
      try {
        await jsonPost('/api/mail/logout', {});
        mailStep('request-code');
        status('mail-status', '');
        await showCaptcha();
      } catch (err) {
        status('mail-status', err.message, true);
      }
    });
  }

  // 17. Load Sources Catalog
  request('/api/sources').then(({ sources }) => {
    state.sources = sources || [];
    const pubDropdown = $('publisher');
    const digestSources = $('digest-sources');
    for (const s of state.sources.filter(s => s.enabled)) {
      if (pubDropdown) {
        const opt = node('option', '', s.label);
        opt.value = s.id;
        pubDropdown.append(opt);
      }
      if (digestSources) {
        const opt = node('option', '', s.label);
        opt.value = s.id;
        digestSources.append(opt);
      }
    }
    renderFreshness(null, state.sources);
  }).catch(() => {});

  // 18. Check Server Health
  request('/api/health').then(h => {
    state.health = h;
    if (h.ai_configured === false) {
      const genBtn = $('generate');
      if (genBtn) genBtn.disabled = true;
      const note = $('config-note');
      if (note) note.textContent = 'Add OPENAI_API_KEY to server settings to enable personalized AI synthesis.';
    }
  }).catch(() => {});

  // 19. Initial Load
  loadNews();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initEvents);
} else {
  initEvents();
}
