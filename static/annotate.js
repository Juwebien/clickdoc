/* clickdoc · annotation client.
 *
 * Behaviour:
 *  - Every element marked [data-anchor="id"] is annotatable on click.
 *  - A floating "+" FAB lets the user annotate the page itself when
 *    no anchor was selected.
 *  - On click, a modal opens with: type (comment/spec/precision),
 *    textarea, the line excerpt (text content of the clicked element),
 *    list of existing annotations for the same anchor, and Save.
 *  - Annotations are POSTed to /api/annotations, listed via GET, and
 *    badges are rendered next to each anchor showing the count.
 *  - Existing annotations can be marked "addressed" (useful when Ju
 *    reviews them, but the primary "addressed" path is for agents
 *    triaging via the CLI feed).
 */

(function () {
  const PAGE = location.pathname; // e.g. /pages/filesystem.html
  const API = '/api/annotations';

  const state = {
    annotsByAnchor: new Map(), // anchor → list
    annotsForPage: [],
  };

  /* ---------- DOM helpers ---------- */
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }
  function el(tag, props, kids) {
    const n = document.createElement(tag);
    if (props) Object.assign(n, props);
    (kids || []).forEach(k => n.appendChild(typeof k === 'string' ? document.createTextNode(k) : k));
    return n;
  }
  function escapeHTML(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  /* ---------- Modal scaffolding ---------- */
  function buildOverlay() {
    if ($('#annot-overlay')) return;
    const overlay = el('div', { id: 'annot-overlay' });
    overlay.addEventListener('click', e => { if (e.target.id === 'annot-overlay') closeModal(); });
    const panel = el('div', { id: 'annot-panel' });
    panel.innerHTML = `
      <h3 id="annot-title">Annotate</h3>
      <div class="excerpt" id="annot-excerpt"></div>
      <div class="existing" id="annot-existing"></div>
      <label>Type</label>
      <div class="types">
        <button data-type="comment" class="active">Comment</button>
        <button data-type="spec">Spec</button>
        <button data-type="precision">Précision</button>
      </div>
      <label>Message</label>
      <textarea id="annot-text" placeholder="What should I know / change / clarify?"></textarea>
      <div class="actions">
        <button class="btn" id="annot-cancel">Cancel</button>
        <button class="btn primary" id="annot-save">Save</button>
      </div>
      <div id="annot-status" role="status" aria-live="polite"></div>
    `;
    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    $('#annot-cancel').addEventListener('click', closeModal);
    $('#annot-save').addEventListener('click', saveCurrent);
    $$('#annot-panel .types button').forEach(b => {
      b.addEventListener('click', () => {
        $$('#annot-panel .types button').forEach(x => x.classList.remove('active'));
        b.classList.add('active');
      });
    });
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') closeModal();
    });
  }

  let current = { anchor: null, excerpt: '', annots: [] };

  function openModal(anchor, excerpt) {
    buildOverlay();
    current = { anchor: anchor || null, excerpt: excerpt || '' , annots: anchor ? (state.annotsByAnchor.get(anchor) || []) : [] };
    $('#annot-title').textContent = anchor ? `Annotate · #${anchor}` : 'Annotate page';
    $('#annot-excerpt').textContent = excerpt || `(no excerpt — annotation attached to the page ${PAGE})`;
    $('#annot-text').value = '';
    $$('#annot-panel .types button').forEach((b, i) => b.classList.toggle('active', i === 0));
    renderExisting();
    $('#annot-overlay').classList.add('open');
    setTimeout(() => $('#annot-text').focus(), 30);
  }

  function closeModal() {
    const o = $('#annot-overlay');
    if (o) o.classList.remove('open');
  }

  function renderExisting() {
    const box = $('#annot-existing');
    box.innerHTML = '';
    if (!current.annots.length) {
      box.style.display = 'none';
      return;
    }
    box.style.display = 'block';
    const label = el('label', {});
    label.textContent = `Existing annotations (${current.annots.length})`;
    box.appendChild(label);
    current.annots.forEach(a => {
      const item = el('div', { className: 'item' + (a.status === 'addressed' ? ' addressed' : '') });
      const meta = el('div', { className: 'meta' });
      meta.textContent = `#${a.id} · ${a.type} · ${a.status} · ${a.author} · ${a.created_at}`;
      item.appendChild(meta);
      const body = el('div', {});
      body.textContent = a.comment;
      item.appendChild(body);
      if (a.response) {
        const resp = el('div', { className: 'response' });
        resp.textContent = '↳ ' + a.response;
        item.appendChild(resp);
      }
      if (a.status === 'open') {
        const actions = el('div', { style: 'margin-top:6px; display:flex; gap:6px;' });
        const mark = el('button', { className: 'btn' });
        mark.textContent = 'Mark addressed';
        mark.addEventListener('click', async () => {
          await fetch(`${API}/${a.id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'addressed' }),
          });
          await loadAnnots();
          // re-open with same anchor so updated state shows
          openModal(current.anchor, current.excerpt);
        });
        actions.appendChild(mark);
        const del = el('button', { className: 'btn danger' });
        del.textContent = 'Delete';
        del.addEventListener('click', async () => {
          if (!confirm('Delete annotation #' + a.id + '?')) return;
          await fetch(`${API}/${a.id}`, { method: 'DELETE' });
          await loadAnnots();
          openModal(current.anchor, current.excerpt);
        });
        actions.appendChild(del);
        item.appendChild(actions);
      }
      box.appendChild(item);
    });
  }

  function setStatus(msg, cls) {
    const el = $('#annot-status');
    if (!el) return;
    el.className = cls || '';
    el.innerHTML = msg ? (cls === 'warn' || cls === '' || cls === 'pending'
      ? '<span class="annot-spinner"></span>' + msg
      : msg) : '';
  }

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  // POST → verify via GET that the row really persisted.
  // The server may transiently restart (clickdoc.path watcher) during heavy edits;
  // we treat the POST as tentative and only consider success when a subsequent GET
  // confirms the row exists with our id. Up to 5 verify attempts with backoff.
  async function postAndVerify(body) {
    const saveBtn = $('#annot-save');
    const cancelBtn = $('#annot-cancel');
    saveBtn.disabled = true;
    cancelBtn.disabled = true;
    try {
      setStatus('Saving…', 'pending');
      const res = await fetch(API, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const txt = await res.text();
        setStatus('Save failed (' + res.status + '): ' + txt, 'error');
        return null;
      }
      const created = await res.json();
      const id = created && created.id;
      if (!id) {
        setStatus('Save returned no id; cannot verify.', 'error');
        return null;
      }
      // Verify via GET with retry. Server restart picks up the WAL on boot, so
      // even a mid-flight restart leaves the row visible after a short wait.
      const delays = [200, 400, 800, 1600, 3200];
      for (let i = 0; i < delays.length; i++) {
        setStatus(`Verifying #${id} (attempt ${i+1}/${delays.length})…`, 'pending');
        try {
          const g = await fetch(`${API}?page=${encodeURIComponent(PAGE)}`);
          if (g.ok) {
            const list = await g.json();
            if (Array.isArray(list) && list.some(a => a.id === id)) {
              setStatus(`✓ Saved as #${id}`, 'ok');
              return created;
            }
          }
        } catch (_) { /* network blip — retry */ }
        await sleep(delays[i]);
      }
      setStatus(`Saved with id #${id} but verification timed out — check inbox.`, 'warn');
      return created;
    } catch (e) {
      setStatus('Save failed: ' + (e && e.message || e), 'error');
      return null;
    } finally {
      saveBtn.disabled = false;
      cancelBtn.disabled = false;
    }
  }

  async function saveCurrent() {
    const text = $('#annot-text').value.trim();
    if (!text) {
      $('#annot-text').focus();
      setStatus('Type a message before saving.', 'warn');
      return;
    }
    const type = $('#annot-panel .types button.active')?.dataset.type || 'comment';
    const body = {
      page: PAGE,
      anchor: current.anchor,
      line_excerpt: current.excerpt,
      type,
      comment: text,
    };
    const created = await postAndVerify(body);
    if (created) {
      await loadAnnots();
      // Brief delay so the user sees the ✓ confirmation before the modal closes.
      setTimeout(closeModal, 600);
    }
  }

  /* ---------- Anchor wiring ---------- */
  function wireAnchors() {
    $$('[data-anchor]').forEach(node => {
      // attach click on the element itself, but ignore links/buttons/inputs
      node.addEventListener('click', e => {
        const tgt = e.target;
        if (tgt.closest('a,button,input,textarea,select')) return;
        if (tgt.classList.contains('annot-badge')) return; // badge has its own handler
        const txt = node.innerText || node.textContent || '';
        openModal(node.dataset.anchor, txt.slice(0, 400));
      });
      // ensure each anchor has its badge slot (we re-render in refreshBadges)
      ensureBadgeSlot(node);
    });
  }

  function ensureBadgeSlot(node) {
    let badge = node.querySelector(':scope > .annot-badge');
    if (badge) return badge;
    badge = el('span', { className: 'annot-badge', title: 'Open annotations' });
    badge.style.display = 'none';
    badge.addEventListener('click', e => {
      e.stopPropagation();
      const txt = node.innerText || node.textContent || '';
      openModal(node.dataset.anchor, txt.slice(0, 400));
    });
    node.appendChild(badge);
    return badge;
  }

  function refreshBadges() {
    let openCount = 0;
    $$('[data-anchor]').forEach(node => {
      const id = node.dataset.anchor;
      const list = state.annotsByAnchor.get(id) || [];
      const badge = ensureBadgeSlot(node);
      if (!list.length) {
        badge.style.display = 'none';
      } else {
        const open = list.filter(a => a.status === 'open').length;
        badge.style.display = 'inline-block';
        badge.textContent = open ? `● ${list.length}` : `✓ ${list.length}`;
        badge.classList.toggle('addressed', open === 0);
      }
      openCount += list.filter(a => a.status === 'open').length;
    });
    const fab = $('#annot-fab');
    if (fab) fab.classList.toggle('has-open', openCount > 0);
  }

  async function loadAnnots() {
    try {
      const res = await fetch(`${API}?page=${encodeURIComponent(PAGE)}`);
      if (!res.ok) return;
      const list = await res.json();
      state.annotsForPage = list;
      state.annotsByAnchor.clear();
      list.forEach(a => {
        const key = a.anchor || '__page__';
        const arr = state.annotsByAnchor.get(key) || [];
        arr.push(a);
        state.annotsByAnchor.set(key, arr);
      });
      refreshBadges();
    } catch (_) { /* offline backend; skip */ }
  }

  /* ---------- Floating FAB ---------- */
  function wireFab() {
    if ($('#annot-fab')) return;
    const fab = el('button', { id: 'annot-fab', title: 'Add an annotation for this page' });
    fab.textContent = '+';
    fab.addEventListener('click', () => {
      // Use the user's current selection as the excerpt when present.
      const sel = window.getSelection?.().toString()?.trim();
      openModal(null, sel || '');
    });
    document.body.appendChild(fab);
  }

  /* ---------- Boot ---------- */
  function boot() {
    buildOverlay();
    wireAnchors();
    wireFab();
    loadAnnots();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
