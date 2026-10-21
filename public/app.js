'use strict';
const $ = (id) => document.getElementById(id);
const state = {source: 'all', articles: [], visible: 9, digest: null, health: null, controller: null};
const sourceNames = {openai: 'OpenAI', anthropic: 'Anthropic', youtube: 'YouTube'};
const node = (tag, className, text) => {const el = document.createElement(tag); if (className) el.className = className; if (text !== undefined) el.textContent = text; return el;};
const externalLink = (url, text) => {const el = node('a', '', text); el.href = url; el.target = '_blank'; el.rel = 'noopener noreferrer'; return el;};
const status = (id, message, error = false) => {$(id).textContent = message; $(id).classList.toggle('error', error);};
async function request(url, options = {}) {
  const response = await fetch(url, options);
  let data;
  try {data = await response.json();} catch {throw new Error('The server is temporarily unavailable. Please try again.');}
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Please check your settings and try again.');
  return data;
}
function renderStories() {
  $('stories').replaceChildren();
  const filtered = state.articles;
  if (!filtered.length) $('stories').append(node('div', 'empty', 'No stories in this view. Try a longer time window or another source.'));
  for (const article of filtered.slice(0, state.visible)) {
    const card = node('article', 'story');
    const top = node('div', 'story-top');
    top.append(node('span', `source-badge ${article.source}`, sourceNames[article.source]));
    const date = node('time', '', new Date(article.published_at).toLocaleDateString(undefined, {month: 'short', day: 'numeric'})); date.dateTime = article.published_at; top.append(date);
    const heading = node('h3'); heading.append(externalLink(article.url, article.title));
    const bottom = node('div', 'story-bottom'); bottom.append(node('span', '', article.publisher), externalLink(article.url, article.source === 'youtube' ? 'Watch story ↗' : 'Read story ↗'));
    card.append(top, heading, node('p', '', article.description || 'Explore the full story at the original source.'), bottom); $('stories').append(card);
  }
  $('show-more').hidden = filtered.length <= state.visible;
  status('news-status', `${filtered.length} ${filtered.length === 1 ? 'story' : 'stories'} to explore`);
}
async function loadNews() {
  if (state.controller) state.controller.abort();
  state.controller = new AbortController();
  $('stories').setAttribute('aria-busy', 'true');
  status('news-status', 'Gathering stories from the sources…');
  try {
    const params = new URLSearchParams({hours: $('window').value, source: state.source, q: $('search').value});
    const data = await request(`/api/news?${params}`, {signal: state.controller.signal});
    state.articles = data.articles; state.visible = 9; renderStories();
    const unavailable = [...new Set(data.sources.filter(s => !s.available).map(s => sourceNames[s.source]))];
    $('source-notice').hidden = !unavailable.length && !data.stale;
    $('source-notice').textContent = data.stale ? 'Sources are temporarily unavailable. Showing the last fetched stories.' : `${unavailable.join(', ')} ${unavailable.length === 1 ? 'has' : 'have'} a feed temporarily unavailable. Other available stories are shown below.`;
    $('updated').textContent = `Sources checked ${new Date(data.fetched_at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}`;
  } catch (error) {if (error.name !== 'AbortError') {status('news-status', error.message, true); $('updated').textContent = 'Could not refresh sources';}}
  finally {$('stories').setAttribute('aria-busy', 'false');}
}
document.querySelectorAll('[data-source]').forEach(button => button.addEventListener('click', () => {
  state.source = button.dataset.source;
  document.querySelectorAll('[data-source]').forEach(b => {b.classList.toggle('active', b === button); b.setAttribute('aria-pressed', String(b === button));}); loadNews();
}));
$('window').addEventListener('change', loadNews); $('refresh').addEventListener('click', loadNews);
let searchTimer; $('search').addEventListener('input', () => {clearTimeout(searchTimer); searchTimer = setTimeout(loadNews, 300);});
$('show-more').addEventListener('click', () => {state.visible += 9; renderStories();});
function renderDigest() {
  const digest = state.digest.digest; $('preview').replaceChildren();
  $('preview').append(node('div', 'eyebrow muted', 'AI BRIEF / YOUR PERSONAL EDITION'), node('p', 'email-greeting', digest.introduction.greeting), node('p', 'email-intro', digest.introduction.introduction));
  for (const article of digest.articles) {
    const item = node('section', 'digest-item'); const meta = node('div', 'digest-meta');
    meta.append(node('span', '', `${String(article.rank).padStart(2, '0')} / ${sourceNames[article.article_type]}`), node('span', '', `${article.relevance_score.toFixed(1)} / 10 relevance`));
    item.append(meta, node('h3', '', article.title), node('p', '', article.summary));
    if (article.reasoning) item.append(node('p', 'reason', `Why it’s here: ${article.reasoning}`));
    item.append(externalLink(article.url, 'Read the original story ↗')); $('preview').append(item);
  }
  $('preview-section').hidden = false; status('email-status', '');
  $('preview-section').scrollIntoView({behavior: 'smooth', block: 'start'});
}
$('digest-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const sources = [...document.querySelectorAll('input[name="sources"]:checked')].map(e => e.value);
  if (!sources.length) {status('digest-status', 'Choose at least one source for your brief.', true); return;}
  const button = $('generate'); button.disabled = true; button.textContent = 'Connecting the dots…';
  status('digest-status', 'Reading the feed excerpts, summarizing, and ranking your stories. This can take about a minute.');
  try {
    state.digest = await request('/api/digest', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: $('reader-name').value, focus: $('focus').value, hours: Number($('digest-window').value), top_n: Number($('article-count').value), sources})});
    status('digest-status', `Your brief is ready: ${state.digest.digest.articles.length} stories, with the original sources.`); renderDigest();
  } catch (error) {status('digest-status', error.message, true);}
  finally {button.disabled = false; button.textContent = 'Generate my brief ✦';}
});
$('copy').addEventListener('click', async () => {try {await navigator.clipboard.writeText(state.digest.digest.markdown); status('email-status', 'Brief copied to your clipboard.');} catch {status('email-status', 'Clipboard access was unavailable. Download the email instead.', true);}});
$('download').addEventListener('click', () => {const url = URL.createObjectURL(new Blob([state.digest.digest.html], {type: 'text/html;charset=utf-8'})); const link = node('a'); link.href = url; link.download = 'your-ai-brief.html'; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); status('email-status', 'Your email preview has been downloaded.');});
$('send').addEventListener('click', () => {
  if (!state.health?.email_configured) {status('email-status', 'Gmail delivery is not configured yet. Add MY_EMAIL, APP_PASSWORD and ADMIN_TOKEN to the server environment.', true); return;}
  status('dialog-status', ''); $('owner-dialog').showModal();
});
$('close-dialog').addEventListener('click', () => {$('owner-dialog').close(); $('owner-key').value = '';});
$('owner-dialog').addEventListener('close', () => {$('owner-key').value = '';});
$('email-form').addEventListener('submit', async (event) => {
  event.preventDefault(); $('confirm-send').disabled = true; status('dialog-status', 'Sending your brief…');
  try {const result = await request('/api/email', {method: 'POST', headers: {'Content-Type': 'application/json', Authorization: `Bearer ${$('owner-key').value}`}, body: JSON.stringify(state.digest)}); $('owner-dialog').close(); status('email-status', result.message);}
  catch (error) {status('dialog-status', error.message, true);}
  finally {$('confirm-send').disabled = false;}
});
request('/api/health').then(data => {state.health = data; if (!data.ai_configured) {$('generate').disabled = true; $('config-note').textContent = 'AI generation will be available when the server is configured.';}}).catch(() => {});
loadNews();
