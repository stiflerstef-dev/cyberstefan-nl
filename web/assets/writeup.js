// ── Flag SVG snippets ─────────────────────────────────────────────────────────
const FLAGS = {
  nl: {
    viewBox: '0 0 900 600',
    inner: '<rect width="900" height="600" fill="#21468B"/><rect width="900" height="400" fill="#fff"/><rect width="900" height="200" fill="#AE1C28"/>',
    code: 'NL'
  },
  en: {
    viewBox: '0 0 60 30',
    inner: '<rect width="60" height="30" fill="#012169"/><path d="M0,0 L60,30 M60,0 L0,30" stroke="#fff" stroke-width="6"/><path d="M0,0 L60,30 M60,0 L0,30" stroke="#C8102E" stroke-width="4"/><path d="M30,0 V30 M0,15 H60" stroke="#fff" stroke-width="10"/><path d="M30,0 V30 M0,15 H60" stroke="#C8102E" stroke-width="6"/>',
    code: 'EN'
  }
};

function setFlagBtn(svgEl, codeEl, flagKey) {
  const f = FLAGS[flagKey];
  svgEl.setAttribute('viewBox', f.viewBox);
  svgEl.innerHTML = f.inner;
  if (codeEl) codeEl.textContent = f.code;
}

// ── Translations ──────────────────────────────────────────────────────────────
const T = {
  en: {
    back:          'All writeups',
    loading:       'Loading writeup...',
    not_found:     'Writeup not found.',
    invalid_id:    'Invalid writeup ID.',
    media_loading: 'Media is being generated in the background...',
    podcast:       'Podcast',
    podcast_en:    'English',
    podcast_nl:    'Dutch',
    presentation:  'Presentation',
    slides_tech:   'Technical',
    slides_non:    'Non-technical',
    media_title:   'Podcast & Presentation',
    footer:      'Built with FastAPI &amp; SQLite &mdash; automated via <code>ctf-writeup</code> CLI',
    switch_lang: 'nl',
    cta_htb:     'Want to try this CTF challenge yourself?',
    cta_thm:     'Want to try this CTF challenge yourself?',
    cta_btn:     'Click here',
    date: d => new Date(d).toLocaleDateString('en-US', { weekday:'long', year:'numeric', month:'long', day:'numeric' }),
  },
  nl: {
    back:          'Alle writeups',
    loading:       'Writeup laden...',
    not_found:     'Writeup niet gevonden.',
    invalid_id:    'Ongeldig writeup ID.',
    media_loading: 'Media wordt gegenereerd op de achtergrond...',
    podcast:       'Podcast',
    podcast_en:    'Engels',
    podcast_nl:    'Nederlands',
    presentation:  'Presentatie',
    slides_tech:   'Technisch',
    slides_non:    'Niet-technisch',
    media_title:   'Podcast & Presentatie',
    footer:      'Gebouwd met FastAPI &amp; SQLite &mdash; geautomatiseerd via <code>ctf-writeup</code> CLI',
    switch_lang: 'en',
    cta_htb:     'Wil je deze CTF ook proberen?',
    cta_thm:     'Wil je deze CTF ook proberen?',
    cta_btn:     'Ga dan hier naartoe',
    date: d => new Date(d).toLocaleDateString('nl-NL', { weekday:'long', year:'numeric', month:'long', day:'numeric' }),
  }
};

// ── Language management ───────────────────────────────────────────────────────
let lang = localStorage.getItem('lang') || 'en';

function applyLang(l) {
  lang = l;
  localStorage.setItem('lang', l);
  document.getElementById('html-root').lang = l;
  document.getElementById('footer-text').innerHTML    = T[l].footer;
  const loadingText = document.getElementById('loading-text');
  if (loadingText) loadingText.textContent = T[l].loading;

  document.querySelectorAll('.lang-flag-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.lang === l);
  });
}

document.querySelectorAll('.lang-flag-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    applyLang(btn.dataset.lang);
    if (window._writeupData) render(window._writeupData);
  });
});

applyLang(lang);

// ── Markdown renderer ─────────────────────────────────────────────────────────
function renderMarkdown(md) {
  if (!md) return '<p>No content.</p>';
  let html = esc(md);

  html = html.replace(/```[\w]*\n([\s\S]*?)```/g, (_, code) =>
    `<pre><code>${code.trimEnd()}</code></pre>`);
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm,  '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm,   '<h2>$1</h2>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g,     '<em>$1</em>');
  html = html.replace(/(^- .+\n?)+/gm, block => {
    const items = block.trim().split('\n').map(l =>
      `<li>${l.replace(/^- /, '')}</li>`).join('');
    return `<ul>${items}</ul>`;
  });
  html = html.split(/\n\n+/).map(block => {
    block = block.trim();
    if (!block) return '';
    if (/^<(h[1-6]|ul|ol|pre|li)/.test(block)) return block;
    return `<p>${block.replace(/\n/g, '<br>')}</p>`;
  }).join('\n');

  return html;
}

function esc(str) {
  return String(str).replace(/[&<>"']/g, c =>
    ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}

// ── Affiliate links ───────────────────────────────────────────────────────────
const AFF = {
  HackTheBox: 'https://www.hackthebox.com',
  TryHackMe:  'https://tryhackme.com',
};

// ── Load writeup ──────────────────────────────────────────────────────────────
// window._WRITEUP_ID can be set by slug pages (e.g. /writeup/sau/) to override URL parsing
async function load() {
  const id = window._WRITEUP_ID || location.pathname.split('/').filter(Boolean).pop();
  if (!id || isNaN(id)) {
    document.getElementById('root').innerHTML =
      `<div class="error-msg">${T[lang].invalid_id}</div>`;
    return;
  }
  try {
    const res = await fetch(`/api/writeups/${id}`);
    if (res.status === 404) throw new Error(T[lang].not_found);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const w = await res.json();
    window._writeupData = w;
    render(w);
    document.title = `${w.machine} — CTF Writeup | CyberStefan`;
    const seoDesc = `${w.machine} (${w.difficulty}, ${w.platform}) CTF writeup — hoe ik de machine heb opgelost, welke technieken ik gebruikte en wat je ervan kunt leren. Door CyberStefan.`;
    document.querySelector('meta[name="description"]').setAttribute('content', seoDesc);
    document.querySelector('meta[property="og:title"]').setAttribute('content', `${w.machine} CTF Writeup — CyberStefan`);
    document.querySelector('meta[property="og:description"]').setAttribute('content', seoDesc);
    document.querySelector('meta[property="og:url"]').setAttribute('content', window.location.href);
    document.querySelector('link[rel="canonical"]').setAttribute('href', window.location.href);
  } catch (e) {
    document.getElementById('root').innerHTML =
      `<div class="error-msg">${e.message}</div>`;
  }
}

function render(w) {
  const t = T[lang];
  const tags = (w.tags || []).map(tag =>
    `<span class="badge badge-tag">${esc(tag)}</span>`).join('');

  document.getElementById('root').innerHTML = `
    <a href="/" class="back-link">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="m15 18-6-6 6-6"/>
      </svg>
      ${t.back}
    </a>

    <div class="writeup-header">
      <h1 class="writeup-title">${esc(w.machine)}</h1>
      <div class="writeup-meta">
        <span class="badge badge-difficulty-${w.difficulty}">${w.difficulty}</span>
        <span class="badge badge-platform-${w.platform}">${w.platform}</span>
        <span class="badge" style="color:var(--muted);border-color:var(--border)">${w.status}</span>
      </div>
      ${tags ? `<div class="writeup-tags">${tags}</div>` : ''}
      <p class="writeup-date" style="margin-top:10px">${t.date(w.created_at)}</p>
    </div>

    <div class="writeup-body">${renderMarkdown(lang === 'nl' && w.writeup_nl ? w.writeup_nl : w.writeup)}</div>

    ${AFF[w.platform] ? `
    <div style="margin-top:32px;padding:18px 20px;background:#161b22;border:1px solid #30363d;border-radius:10px;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap">
      <span style="font-size:.9rem;color:#cdd9e5">${t[w.platform === 'HackTheBox' ? 'cta_htb' : 'cta_thm']}</span>
      <a href="${AFF[w.platform]}" target="_blank" rel="noopener sponsored" style="display:inline-flex;align-items:center;gap:6px;background:#58a6ff;color:#0d1117;font-size:.82rem;font-weight:600;padding:8px 16px;border-radius:6px;text-decoration:none;white-space:nowrap">
        ${t.cta_btn}
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
      </a>
    </div>` : ''}

    <div id="media-section"></div>
  `;

  loadMedia(w.id);
}

// ── Media ─────────────────────────────────────────────────────────────────────
async function loadMedia(id) {
  const el = document.getElementById('media-section');
  try {
    const res = await fetch(`/api/writeups/${id}/media`);
    const data = await res.json();
    if (data.status === 'pending') {
      el.innerHTML = `<div class="media-pending">
        <div class="spinner" style="display:inline-block;margin-right:8px"></div>
        ${T[lang].media_loading}
      </div>`;
      setTimeout(() => loadMedia(id), 10000);
      return;
    }
    el.innerHTML = buildMediaSection(data.files);
  } catch (e) {
    // Geen media beschikbaar
  }
}

function buildMediaSection(f) {
  if (!f || Object.keys(f).length === 0) return '';
  const t = T[lang];

  const audioEN    = f.audio_technical        ? `/${f.audio_technical}`         : null;
  const audioNL    = f.audio_nontechnical     ? `/${f.audio_nontechnical}`      : null;
  const slidesTechKey = lang === 'nl' ? 'slides_technical_nl' : 'slides_technical';
  const slidesTech = f[slidesTechKey]         ? `/${f[slidesTechKey]}`          :
                     f.slides_technical       ? `/${f.slides_technical}`        : null;
  const slidesNonKey = lang === 'nl' ? 'slides_nontechnical_nl' : 'slides_nontechnical_en';
  const slidesNon  = f[slidesNonKey]          ? `/${f[slidesNonKey]}`           :
                     f.slides_nontechnical    ? `/${f.slides_nontechnical}`     : null;

  if (!audioEN && !audioNL && !slidesTech && !slidesNon) return '';

  let html = `<div class="media-section">
    <h2 class="media-title">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
      ${t.media_title}
    </h2>
    <div class="media-grid">`;

  const activeAudio = lang === 'nl' ? audioNL : audioEN;
  if (activeAudio) {
    html += `<div class="media-card">
      <div class="media-card-title">🎙️ ${t.podcast}</div>
      <audio controls src="${activeAudio}" style="width:100%"></audio>
    </div>`;
  }

  if (slidesTech || slidesNon) {
    html += `<div class="media-card">
      <div class="media-card-title">📊 ${t.presentation}</div>
      <div class="slides-buttons">`;
    if (slidesTech) html += `<a href="${slidesTech}" target="_blank" class="slides-btn slides-btn-tech">${t.slides_tech}</a>`;
    if (slidesNon)  html += `<a href="${slidesNon}"  target="_blank" class="slides-btn slides-btn-non">${t.slides_non}</a>`;
    html += `</div></div>`;
  }

  html += `</div></div>`;
  return html;
}

load();
