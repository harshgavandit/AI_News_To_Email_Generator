'use strict';
const $ = (id) => document.getElementById(id);
const state = {articles: [], total: 0, cursor: null, digest: null, health: null, controller: null, mail: null};
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
  for (const article of filtered) {
    const card = node('article', 'story');
    const top = node('div', 'story-top');
    top.append(node('span', `source-badge ${article.source}`, sourceNames[article.source] || article.publisher));
    const date = node('time', '', new Date(article.published_at).toLocaleDateString(undefined, {month: 'short', day: 'numeric'})); date.dateTime = article.published_at; top.append(date);
    const heading = node('h3'); heading.append(externalLink(article.url, article.title));
    const bottom = node('div', 'story-bottom'); bottom.append(node('span', '', article.publisher), externalLink(article.url, article.source === 'youtube' ? 'Watch story ↗' : 'Read story ↗'));
    card.append(top, heading, node('p', '', article.description || 'Explore the full story at the original source.'), bottom); $('stories').append(card);
  }
  $('show-more').hidden = !state.cursor;
  status('news-status', `${filtered.length} of ${state.total} ${state.total === 1 ? 'story' : 'stories'}`);
}
async function loadNews(append = false) {
  if (state.controller) state.controller.abort();
  const controller = new AbortController();
  state.controller = controller;
  $('stories').setAttribute('aria-busy', 'true');
  $('show-more').disabled = true;
  status('news-status', 'Loading stories…');
  try {
    const params = new URLSearchParams({hours: $('window').value, kind: $('kind').value,
      publisher: $('publisher').value, q: $('search').value, limit: '9'});
    if (append && state.cursor) params.set('cursor', state.cursor);
    const data = await request(`/api/news?${params}`, {signal: controller.signal});
    if (state.controller !== controller) return;
    state.articles = append ? state.articles.concat(data.articles) : data.articles;
    state.cursor = data.next_cursor; state.total = data.total; renderStories();
    const unavailable = data.sources.filter(s => s.enabled !== false && s.available === false).length;
    $('source-notice').hidden = !unavailable;
    $('source-notice').textContent = `${unavailable} ${unavailable === 1 ? 'source is' : 'sources are'} temporarily unavailable. Previously collected stories are still shown when available.`;
    $('updated').textContent = data.fetched_at ? `Last source check: ${new Date(data.fetched_at).toLocaleString()}` : 'Waiting for the first source refresh';
  } catch (error) {
    if (error.name !== 'AbortError') {status('news-status', error.message, true); $('updated').textContent = 'Could not load stories';}
  } finally {
    if (state.controller === controller) {$('stories').setAttribute('aria-busy', 'false'); $('show-more').disabled = false;}
  }
}
for (const id of ['window','kind','publisher']) $(id).addEventListener('change', () => loadNews());
$('refresh').addEventListener('click', () => loadNews());
let searchTimer; $('search').addEventListener('input', () => {clearTimeout(searchTimer); searchTimer = setTimeout(loadNews, 300);});
$('show-more').addEventListener('click', () => loadNews(true));
request('/api/sources').then(({sources}) => {
  for (const s of sources.filter(s => s.enabled)) {
    for (const id of ['publisher','digest-sources']) {
      const option = node('option','',s.label); option.value = s.id; $(id).append(option);
    }
    sourceNames[s.source] ??= s.label;
  }
}).catch(() => {});
function renderDigest() {
  const digest = state.digest.digest; $('preview').replaceChildren();
  $('preview').append(node('div', 'eyebrow muted', 'AI BRIEF / YOUR PERSONAL EDITION'), node('p', 'email-greeting', digest.introduction.greeting), node('p', 'email-intro', digest.introduction.introduction));
  for (const article of digest.articles) {
    const item = node('section', 'digest-item'); const meta = node('div', 'digest-meta');
    meta.append(node('span', '', `${String(article.rank).padStart(2, '0')} / ${(sourceNames[article.article_type] || article.article_type)}`), node('span', '', `${article.relevance_score.toFixed(1)} / 10 relevance`));
    item.append(meta, node('h3', '', article.title), node('p', '', article.summary));
    if (article.reasoning) item.append(node('p', 'reason', `Why it’s here: ${article.reasoning}`));
    item.append(externalLink(article.url, 'Read the original story ↗')); $('preview').append(item);
  }
  $('preview-section').hidden = false; status('email-status', '');
  $('preview-section').scrollIntoView({behavior: 'smooth', block: 'start'});
}
$('digest-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const source = $('digest-sources').value;
  const button = $('generate'); button.disabled = true; button.textContent = 'Connecting the dots…';
  status('digest-status', 'Reading the feed excerpts, summarizing, and ranking your stories. This can take about a minute.');
  try {
    state.digest = await request('/api/digest', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: $('reader-name').value.trim() || 'Reader', focus: $('focus').value, hours: Number($('digest-window').value), top_n: Number($('article-count').value), ...(source === 'all' ? {} : {sources:[source]})})});
    status('digest-status', `Your brief is ready: ${state.digest.digest.articles.length} stories, with the original sources.`); renderDigest();
  } catch (error) {status('digest-status', error.message, true);}
  finally {button.disabled = false; button.textContent = 'Generate my brief ✦';}
});
$('copy').addEventListener('click', async () => {try {await navigator.clipboard.writeText(state.digest.digest.markdown); status('email-status', 'Brief copied to your clipboard.');} catch {status('email-status', 'Clipboard access was unavailable. Download the email instead.', true);}});
$('download').addEventListener('click', () => {const url = URL.createObjectURL(new Blob([state.digest.digest.html], {type: 'text/html;charset=utf-8'})); const link = node('a'); link.href = url; link.download = 'your-ai-brief.html'; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); status('email-status', 'Your email preview has been downloaded.');});
$('owner-send').addEventListener('click', () => {
  if (!state.health?.email_configured) {status('email-status', 'Gmail delivery is not configured yet. Add MY_EMAIL, APP_PASSWORD and ADMIN_TOKEN to the server environment.', true); return;}
  status('dialog-status', ''); $('owner-dialog').showModal();
});
$('close-dialog').addEventListener('click', () => {$('owner-dialog').close(); $('owner-key').value = '';});
$('owner-dialog').addEventListener('close', () => {$('owner-key').value = '';});
$('email-form').addEventListener('submit', async (event) => {
  event.preventDefault(); $('confirm-send').disabled = true; status('dialog-status', 'Sending your brief…');
  try {const result = await request('/api/email', {method: 'POST', headers: {'Content-Type': 'application/json', Authorization: `Bearer ${$('owner-key').value}`}, body: JSON.stringify({digest:state.digest.digest,signature:state.digest.signature,expires:state.digest.expires})}); $('owner-dialog').close(); status('email-status', result.message);}
  catch (error) {status('dialog-status', error.message, true);}
  finally {$('confirm-send').disabled = false;}
});
request('/api/health').then(data => {state.health = data; $('owner-send').hidden = !data.email_configured; if (!data.ai_configured) {$('generate').disabled = true; $('config-note').textContent = 'AI generation will be available when the server is configured.';}}).catch(() => {});
function jsonPost(url, data) {
  return request(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
}
let captchaWidget, captchaToken, captchaLoader;
function mailStep(step) {
  for (const id of ['request-code','verify-code','send-brief']) $(id).hidden = id !== step;
}
async function showCaptcha() {
  if (captchaWidget !== undefined) {window.turnstile.reset(captchaWidget); captchaToken = ''; return;}
  captchaLoader ??= new Promise((resolve,reject) => {
    const script = node('script'); script.src='https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
    script.onload=resolve; script.onerror=reject; document.head.append(script);
  });
  await captchaLoader;
  await new Promise(resolve => window.turnstile.ready(resolve));
  if (captchaWidget !== undefined) return;
  captchaWidget=window.turnstile.render('#mail-captcha',{sitekey:state.mail.site_key, action:'verify_email',
    callback:token=>{captchaToken=token;},
    'expired-callback':()=>{captchaToken='';}, 'error-callback':()=>{captchaToken='';}});
}
$('send').addEventListener('click', async () => {
  try {
    state.mail = await request('/api/mail/config');
    if (!state.mail.enabled || !state.digest?.preview_id) {
      status('email-status','Public email delivery is not available yet. You can still copy or download this brief.'); return;
    }
    status('mail-status',state.mail.pilot ? 'Inbox delivery is in a limited test. You can still copy or download your brief.' : '');
    mailStep(state.mail.verified ? 'send-brief' : 'request-code');
    $('mail-dialog').showModal();
    if (!state.mail.verified) await showCaptcha();
  } catch {status('email-status','Email delivery is temporarily unavailable.',true);}
});
$('mail-close').addEventListener('click',()=> $('mail-dialog').close());
$('mail-dialog').addEventListener('close',()=>{
  $('mail-code').value=''; $('mail-address').value='';
});
async function submitMail(event, task) {
  event.preventDefault();
  const button=event.currentTarget.querySelector('button[type="submit"]');
  button.disabled=true;
  status('mail-status','Working…');
  try {await task();} catch(error) {status('mail-status',error.message,true);}
  finally {button.disabled=false;}
}
$('request-code').addEventListener('submit', event=>submitMail(event, async()=>{
  if (!captchaToken) throw new Error('Complete the bot check first.');
  const token=captchaToken; captchaToken='';
  try {
    await jsonPost('/api/mail/challenge',{email:$('mail-address').value,captcha:token});
    mailStep('verify-code'); $('mail-code').focus(); status('mail-status','Check your inbox for the verification code.');
  } catch(error) {await showCaptcha(); throw error;}
}));
$('verify-code').addEventListener('submit', event=>submitMail(event, async()=>{
  await jsonPost('/api/mail/verify',{code:$('mail-code').value});
  $('mail-code').value=''; $('mail-address').value='';
  mailStep('send-brief'); status('mail-status','Inbox verified.');
}));
$('send-brief').addEventListener('submit', event=>submitMail(event, async()=>{
  const result=await jsonPost('/api/mail/send',{preview_id:state.digest.preview_id});
  $('mail-dialog').close(); status('email-status',result.message);
}));
for(const id of ['different-email','forget-email']) $(id).addEventListener('click',async()=>{
  try {
    await jsonPost('/api/mail/logout',{});
    $('mail-code').value=''; $('mail-address').value=''; mailStep('request-code'); await showCaptcha(); status('mail-status','');
  } catch(error){status('mail-status',error.message,true);}
});
loadNews();
