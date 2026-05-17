/* clickdoc · TOC active-section highlight + mobile drawer + annotation
 * count badges next to page links in the sidebar.
 *
 * Design notes (2026-05-17):
 *   - On mobile the topbar is fixed at the top of the viewport; we inject
 *     the current page H1 into a .topbar-title span so the user always knows
 *     where they are.
 *   - The sidebar is a left-slide drawer on mobile, controlled by .open
 *     class. A .toc-backdrop element is appended dynamically so tapping
 *     outside closes the drawer.
 *   - Body gets .drawer-open class to lock scroll while the drawer is up.
 *   - Esc closes the drawer.
 */
(function () {
  const toc = document.getElementById('toc');
  if (!toc) return;

  // ---------- Mobile topbar enhancement ----------------------------------
  const menuToggle = document.querySelector('.menu-toggle');
  const btn = menuToggle ? menuToggle.querySelector('button') : null;

  if (menuToggle) {
    // Inject .topbar-title with the current page H1 (falls back to <title>).
    let title = '';
    const h1 = document.querySelector('header.page h1, h1');
    if (h1) title = h1.textContent.trim();
    // Strip a common "<Project> · " prefix from the document title fallback.
    if (!title) title = document.title.replace(/^[^·]+·\s*/, '').trim() || document.title;
    if (title.length > 60) title = title.slice(0, 58) + '…';

    // Re-arrange button label to a hamburger icon if it still says "☰ Menu".
    if (btn) {
      btn.textContent = '☰';
      btn.setAttribute('aria-label', 'Ouvrir le menu');
      btn.setAttribute('aria-expanded', 'false');
    }

    if (!menuToggle.querySelector('.topbar-title')) {
      const t = document.createElement('span');
      t.className = 'topbar-title';
      t.textContent = title;
      menuToggle.appendChild(t);
    }
  }

  // ---------- Drawer backdrop --------------------------------------------
  let backdrop = document.querySelector('.toc-backdrop');
  if (!backdrop) {
    backdrop = document.createElement('div');
    backdrop.className = 'toc-backdrop';
    backdrop.setAttribute('aria-hidden', 'true');
    document.body.appendChild(backdrop);
  }

  function openDrawer() {
    toc.classList.add('open');
    backdrop.classList.add('open');
    document.body.classList.add('drawer-open');
    if (btn) btn.setAttribute('aria-expanded', 'true');
  }
  function closeDrawer() {
    toc.classList.remove('open');
    backdrop.classList.remove('open');
    document.body.classList.remove('drawer-open');
    if (btn) btn.setAttribute('aria-expanded', 'false');
  }
  function toggleDrawer() {
    if (toc.classList.contains('open')) closeDrawer(); else openDrawer();
  }

  if (btn) btn.addEventListener('click', toggleDrawer);
  backdrop.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });
  // Tapping a link closes the drawer (so user lands on the new page clean).
  toc.querySelectorAll('a').forEach(a => a.addEventListener('click', closeDrawer));

  // ---------- Active-section highlight on scroll (intra-page) ------------
  const sections = document.querySelectorAll('section[id]');
  const intraLinks = toc.querySelectorAll('a[href^="#"]');
  if (sections.length && intraLinks.length) {
    const onScroll = () => {
      let current = '';
      const offset = 80;
      sections.forEach(s => { if (s.getBoundingClientRect().top - offset <= 0) current = s.id; });
      intraLinks.forEach(l => l.classList.toggle('active', l.getAttribute('href') === '#' + current));
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  // Mark current page link as active (cross-page nav).
  const here = location.pathname;
  toc.querySelectorAll('a[href]').forEach(a => {
    const href = a.getAttribute('href') || '';
    if (href.startsWith('/pages/') && href === here) a.classList.add('active');
  });

  // ---------- Annotation count badges (open) -----------------------------
  fetch('/api/annotations').then(r => r.ok ? r.json() : []).then(list => {
    const byPage = new Map();
    list.forEach(a => {
      if (a.status !== 'open') return;
      byPage.set(a.page, (byPage.get(a.page) || 0) + 1);
    });
    toc.querySelectorAll('a[href^="/pages/"]').forEach(a => {
      const c = byPage.get(a.getAttribute('href'));
      a.querySelectorAll('.badge').forEach(b => b.remove());
      if (c) {
        const b = document.createElement('span');
        b.className = 'badge';
        b.textContent = c;
        a.appendChild(b);
      }
    });
  }).catch(() => {});
})();
