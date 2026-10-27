// ============================================================================
// Life Inbox — Main Application JavaScript
// A personal AI-powered inbox organizer
// ============================================================================

(() => {
  'use strict';

  // --------------------------------------------------------------------------
  // Utility helpers
  // --------------------------------------------------------------------------

  /** Convert an ISO timestamp string to a human-friendly relative time. */
  function relativeTime(iso) {
    if (!iso) return '';
    const now = Date.now();
    const then = new Date(iso).getTime();
    const diff = Math.max(0, now - then);
    const seconds = Math.floor(diff / 1000);
    if (seconds < 10) return 'just now';
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    if (days < 30) return `${days}d ago`;
    const months = Math.floor(days / 30);
    if (months < 12) return `${months}mo ago`;
    const years = Math.floor(months / 12);
    return `${years}y ago`;
  }

  /** Sanitize a string for safe insertion as HTML text content. */
  function esc(str) {
    const d = document.createElement('div');
    d.textContent = str ?? '';
    return d.innerHTML;
  }

  /** Shorthand for querySelector. */
  const $ = (sel, ctx = document) => ctx.querySelector(sel);
  const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

  // --------------------------------------------------------------------------
  // Toast notifications
  // --------------------------------------------------------------------------

  function showToast(message, type = 'info') {
    const container = $('.toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.setAttribute('role', 'alert');

    const icons = {
      success: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>`,
      error: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
      info: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`,
    };

    toast.innerHTML = `
      <span class="toast__icon">${icons[type] || icons.info}</span>
      <span class="toast__msg">${esc(message)}</span>
      <button class="toast__close" aria-label="Dismiss">&times;</button>
    `;

    container.appendChild(toast);

    // Trigger entrance animation on next frame
    requestAnimationFrame(() => toast.classList.add('toast--visible'));

    const dismiss = () => {
      toast.classList.remove('toast--visible');
      toast.classList.add('toast--exit');
      toast.addEventListener('transitionend', () => toast.remove(), { once: true });
      // Fallback removal
      setTimeout(() => toast.remove(), 500);
    };

    toast.querySelector('.toast__close').addEventListener('click', dismiss);
    setTimeout(dismiss, 4000);
  }

  // --------------------------------------------------------------------------
  // API helpers
  // --------------------------------------------------------------------------

  async function api(path, opts = {}) {
    const { method = 'GET', body, params } = opts;
    let url = path;
    if (params) {
      const sp = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) {
        if (v !== '' && v !== null && v !== undefined) sp.set(k, v);
      }
      const qs = sp.toString();
      if (qs) url += `?${qs}`;
    }
    const fetchOpts = { method, headers: {} };
    if (body !== undefined) {
      fetchOpts.headers['Content-Type'] = 'application/json';
      fetchOpts.body = JSON.stringify(body);
    }
    const res = await fetch(url, fetchOpts);
    if (res.status === 204) return null;
    if (!res.ok) {
      let detail = `Request failed (${res.status})`;
      try {
        const err = await res.json();
        if (err.detail) detail = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail);
      } catch { /* ignore */ }
      throw new Error(detail);
    }
    return res.json();
  }

  // --------------------------------------------------------------------------
  // Theme toggle
  // --------------------------------------------------------------------------

  function initTheme() {
    const saved = localStorage.getItem('theme') || 'light';
    applyTheme(saved);

    const btn = $('#themeToggle');
    if (btn) btn.addEventListener('click', () => {
      const next = document.body.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      localStorage.setItem('theme', next);
    });
  }

  function applyTheme(theme) {
    document.body.setAttribute('data-theme', theme);
    const btn = $('#themeToggle');
    if (!btn) return;
    const sunIcon = btn.querySelector('.icon-sun, [data-icon="sun"]');
    const moonIcon = btn.querySelector('.icon-moon, [data-icon="moon"]');
    // Convention: show sun icon in dark mode (click to go light), moon in light mode
    if (sunIcon) sunIcon.classList.toggle('hidden', theme === 'light');
    if (moonIcon) moonIcon.classList.toggle('hidden', theme === 'dark');
  }

  // --------------------------------------------------------------------------
  // Section navigation
  // --------------------------------------------------------------------------

  const SECTIONS = ['dashboard', 'inbox', 'analysis', 'tasks'];

  function initNavigation() {
    const navItems = $$('.nav-item[data-section]');

    navItems.forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const section = item.dataset.section;
        navigateTo(section);
        // Close sidebar on mobile
        const sidebar = $('.sidebar');
        if (sidebar) sidebar.classList.remove('open');
      });
    });

    // Menu toggle for mobile
    const menuToggle = $('.menu-toggle, .hamburger, [data-menu-toggle]');
    if (menuToggle) {
      menuToggle.addEventListener('click', () => {
        const sidebar = $('.sidebar');
        if (sidebar) sidebar.classList.toggle('open');
      });
    }

    // Restore from hash
    const hash = location.hash.replace('#', '');
    navigateTo(SECTIONS.includes(hash) ? hash : 'dashboard');

    // Listen for hash changes
    window.addEventListener('hashchange', () => {
      const h = location.hash.replace('#', '');
      if (SECTIONS.includes(h)) navigateTo(h, false);
    });
  }

  function navigateTo(section, pushHash = true) {
    if (!SECTIONS.includes(section)) section = 'dashboard';

    // Update sections visibility
    SECTIONS.forEach(s => {
      const el = $(`#${s}-section`);
      if (el) el.classList.toggle('hidden', s !== section);
    });

    // Update active nav
    $$('.nav-item[data-section]').forEach(item => {
      item.classList.toggle('active', item.dataset.section === section);
    });

    if (pushHash) history.replaceState(null, '', `#${section}`);

    // Lazy-load data for the section
    if (section === 'inbox') loadNotes();
    if (section === 'tasks') loadTasks();
    if (section === 'dashboard') refreshDashboard();
    if (section === 'analysis') loadLatestAnalysis();
  }

  // --------------------------------------------------------------------------
  // Skeleton / loading helpers
  // --------------------------------------------------------------------------

  function skeletonCards(container, count = 4) {
    if (!container) return;
    container.innerHTML = Array.from({ length: count }, () => `
      <div class="note-card skeleton-card" aria-hidden="true">
        <div class="skeleton skeleton-line skeleton-line--title"></div>
        <div class="skeleton skeleton-line"></div>
        <div class="skeleton skeleton-line skeleton-line--short"></div>
      </div>
    `).join('');
  }

  function setButtonLoading(btn, loading) {
    if (!btn) return;
    if (loading) {
      btn.dataset.origText = btn.textContent;
      btn.disabled = true;
      btn.classList.add('btn--loading');
      const spinner = document.createElement('span');
      spinner.className = 'spinner';
      spinner.setAttribute('aria-hidden', 'true');
      btn.prepend(spinner);
    } else {
      btn.disabled = false;
      btn.classList.remove('btn--loading');
      const spinner = btn.querySelector('.spinner');
      if (spinner) spinner.remove();
      if (btn.dataset.origText) {
        // keep existing text
        delete btn.dataset.origText;
      }
    }
  }

  // --------------------------------------------------------------------------
  // Notes (Inbox items)
  // --------------------------------------------------------------------------

  function initNotes() {
    const addBtn = $('#addNoteBtn');
    const textarea = $('#noteText');

    if (addBtn) addBtn.addEventListener('click', addNote);
    if (textarea) {
      textarea.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === 'Enter') {
          e.preventDefault();
          addNote();
        }
      });
    }

    // Search / filter form
    const form = $('#itemSearchForm');
    if (form) {
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        syncFiltersToUrl();
        loadNotes();
      });
      form.addEventListener('reset', (e) => {
        // Let the browser reset first, then reload
        setTimeout(() => {
          syncFiltersToUrl();
          loadNotes();
        }, 0);
      });
    }
  }

  async function addNote() {
    const textarea = $('#noteText');
    const addBtn = $('#addNoteBtn');
    const status = $('#noteStatus');
    const text = textarea ? textarea.value.trim() : '';

    if (!text) {
      if (status) status.textContent = 'Please enter some text.';
      showToast('Please enter some text.', 'error');
      return;
    }

    setButtonLoading(addBtn, true);
    if (status) status.textContent = 'Adding…';

    try {
      await api('/api/items', { method: 'POST', body: { raw_text: text } });
      showToast('Note added!', 'success');
      if (textarea) textarea.value = '';
      if (status) status.textContent = '';
      await loadNotes();
    } catch (err) {
      showToast(err.message, 'error');
      if (status) status.textContent = err.message;
    } finally {
      setButtonLoading(addBtn, false);
    }
  }

  function getFilterParams() {
    return {
      q: ($('#itemSearch') || {}).value || '',
      item_type: ($('#itemTypeFilter') || {}).value || '',
      category: ($('#categoryFilter') || {}).value || '',
      priority: ($('#priorityFilter') || {}).value || '',
      processing_status: ($('#processingStatusFilter') || {}).value || '',
      limit: 100,
    };
  }

  function syncFiltersToUrl() {
    const params = getFilterParams();
    const sp = new URLSearchParams(location.search);
    ['q', 'item_type', 'category', 'priority', 'processing_status'].forEach(k => {
      if (params[k]) sp.set(k, params[k]);
      else sp.delete(k);
    });
    const qs = sp.toString();
    history.replaceState(null, '', `${location.pathname}${qs ? '?' + qs : ''}${location.hash}`);
  }

  function syncFiltersFromUrl() {
    const sp = new URLSearchParams(location.search);
    const set = (sel, key) => { const el = $(sel); if (el) el.value = sp.get(key) || ''; };
    set('#itemSearch', 'q');
    set('#itemTypeFilter', 'item_type');
    set('#categoryFilter', 'category');
    set('#priorityFilter', 'priority');
    set('#processingStatusFilter', 'processing_status');
  }

  async function loadNotes() {
    const container = $('#notes');
    const statusEl = $('#searchStatus');
    if (!container) return;

    skeletonCards(container, 4);

    try {
      const params = getFilterParams();
      const items = await api('/api/items', { params });
      renderNotes(container, items);
      if (statusEl) {
        statusEl.textContent = items.length
          ? `${items.length} item${items.length !== 1 ? 's' : ''} found`
          : '';
      }
      // Update dashboard stat
      const statEl = $('#statTotalItems');
      if (statEl) statEl.textContent = items.length;
    } catch (err) {
      container.innerHTML = `<p class="empty-state">Failed to load notes.</p>`;
      showToast(err.message, 'error');
    }
  }

  function renderNotes(container, items) {
    if (!items || items.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:.4">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/>
          </svg>
          <p>No items yet. Add your first note above!</p>
        </div>`;
      return;
    }

    container.innerHTML = items.map(item => noteCardHTML(item)).join('');

    // Attach edit / delete listeners
    container.querySelectorAll('[data-action="edit"]').forEach(btn => {
      btn.addEventListener('click', () => startEditNote(btn.closest('.note-card'), btn.dataset.id));
    });
    container.querySelectorAll('[data-action="delete"]').forEach(btn => {
      btn.addEventListener('click', () => deleteNote(btn.dataset.id));
    });
  }

  function noteCardHTML(item) {
    const badges = [];
    if (item.item_type) badges.push(`<span class="badge badge--type">${esc(item.item_type)}</span>`);
    if (item.processing_status) badges.push(`<span class="badge badge--status">${esc(item.processing_status)}</span>`);

    return `
      <div class="note-card" data-id="${item.id}">
        <div class="note-card__body">
          <div class="note-card__header">
            ${item.title ? `<h4 class="note-card__title">${esc(item.title)}</h4>` : ''}
            <span class="note-card__time" title="${esc(item.created_at)}">${relativeTime(item.created_at)}</span>
          </div>
          <p class="note-card__text">${esc(item.raw_text)}</p>
          ${badges.length ? `<div class="note-card__badges">${badges.join('')}</div>` : ''}
        </div>
        <div class="note-card__actions">
          <button class="btn btn--sm btn--ghost" data-action="edit" data-id="${item.id}" title="Edit">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          </button>
          <button class="btn btn--sm btn--ghost btn--danger" data-action="delete" data-id="${item.id}" title="Delete">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6m5 0V4a1 1 0 011-1h2a1 1 0 011 1v2"/></svg>
          </button>
        </div>
      </div>`;
  }

  // --------------------------------------------------------------------------
  // Edit note (inline)
  // --------------------------------------------------------------------------

  function startEditNote(card, id) {
    if (!card) return;
    const textEl = card.querySelector('.note-card__text');
    const actionsEl = card.querySelector('.note-card__actions');
    if (!textEl) return;

    const original = textEl.textContent;
    const bodyEl = card.querySelector('.note-card__body');

    // Replace body with edit form
    bodyEl.innerHTML = `
      <textarea class="edit-textarea" rows="3">${esc(original)}</textarea>
      <div class="edit-actions">
        <button class="btn btn--sm btn--primary save-edit-btn">Save</button>
        <button class="btn btn--sm btn--ghost cancel-edit-btn">Cancel</button>
      </div>`;
    if (actionsEl) actionsEl.classList.add('hidden');

    const textarea = bodyEl.querySelector('.edit-textarea');
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);

    // Escape to cancel
    textarea.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        loadNotes();
      }
    });

    bodyEl.querySelector('.cancel-edit-btn').addEventListener('click', () => loadNotes());
    bodyEl.querySelector('.save-edit-btn').addEventListener('click', async () => {
      const newText = textarea.value.trim();
      if (!newText) { showToast('Text cannot be empty.', 'error'); return; }
      const saveBtn = bodyEl.querySelector('.save-edit-btn');
      setButtonLoading(saveBtn, true);
      try {
        await api(`/api/items/${id}`, { method: 'PUT', body: { raw_text: newText } });
        showToast('Note updated!', 'success');
        await loadNotes();
      } catch (err) {
        showToast(err.message, 'error');
        setButtonLoading(saveBtn, false);
      }
    });
  }

  // --------------------------------------------------------------------------
  // Delete note
  // --------------------------------------------------------------------------

  async function deleteNote(id) {
    if (!confirm('Delete this note? This cannot be undone.')) return;

    const card = $(`.note-card[data-id="${id}"]`);
    if (card) {
      card.classList.add('note-card--removing');
    }

    try {
      await api(`/api/items/${id}`, { method: 'DELETE' });
      showToast('Note deleted.', 'success');
      // Wait for animation then reload
      setTimeout(() => loadNotes(), 300);
    } catch (err) {
      showToast(err.message, 'error');
      if (card) card.classList.remove('note-card--removing');
    }
  }

  // --------------------------------------------------------------------------
  // Analysis
  // --------------------------------------------------------------------------

  function initAnalysis() {
    const btn = $('#analyzeBtn');
    if (btn) btn.addEventListener('click', runAnalysis);
  }

  async function runAnalysis() {
    const btn = $('#analyzeBtn');
    const statusEl = $('#analysisStatus');
    const output = $('#aiOutput');

    setButtonLoading(btn, true);
    if (statusEl) statusEl.textContent = 'Analyzing inbox — this may take a moment…';
    if (output) output.innerHTML = `
      <div class="analysis-loading">
        <span class="spinner spinner--lg"></span>
        <p>Running AI analysis on your inbox…</p>
      </div>`;

    try {
      const result = await api('/api/analyze', { method: 'POST' });
      renderAnalysis(result);
      showToast('Analysis complete!', 'success');
      if (statusEl) statusEl.textContent = '';
      refreshDashboard();
    } catch (err) {
      showToast(err.message, 'error');
      if (statusEl) statusEl.textContent = `Error: ${err.message}`;
      if (output) output.innerHTML = `<p class="empty-state">Analysis failed. Please try again.</p>`;
    } finally {
      setButtonLoading(btn, false);
    }
  }

  async function loadLatestAnalysis() {
    const output = $('#aiOutput');
    const statusEl = $('#analysisStatus');
    if (!output) return;

    try {
      const result = await api('/api/analyze/latest');
      if (result === null) {
        output.innerHTML = `
          <div class="empty-state">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:.4">
              <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
            <p>No analysis yet. Click <strong>Analyze</strong> to get started!</p>
          </div>`;
        if (statusEl) statusEl.textContent = '';
        return;
      }
      renderAnalysis(result);
      populateCategoryFilter(result);
    } catch (err) {
      if (statusEl) statusEl.textContent = '';
      output.innerHTML = `<p class="empty-state">Could not load analysis.</p>`;
    }
  }

  function renderAnalysis(data) {
    const output = $('#aiOutput');
    if (!output || !data) return;

    let html = '';

    // Mode & timestamp
    if (data.mode || data.generated_at) {
      html += `<div class="analysis-meta">`;
      if (data.mode) html += `<span class="badge badge--mode">${esc(data.mode)} mode</span>`;
      if (data.generated_at) html += `<span class="analysis-meta__time">${relativeTime(data.generated_at)}</span>`;
      html += `</div>`;
    }

    // Priority view
    if (data.priority_view) {
      html += `<div class="analysis-section"><h3 class="analysis-section__title">Priority View</h3>`;
      for (const [level, items] of Object.entries(data.priority_view)) {
        if (!items || items.length === 0) continue;
        const levelClass = level.toLowerCase();
        html += `<div class="priority-group priority-group--${levelClass}">`;
        html += `<h4 class="priority-group__label"><span class="priority-dot priority-dot--${levelClass}"></span>${esc(level)} Priority</h4>`;
        html += `<ul class="priority-list">`;
        items.forEach(it => {
          html += `<li>${esc(it.title || it.id)}</li>`;
        });
        html += `</ul></div>`;
      }
      html += `</div>`;
    }

    // Buckets
    if (data.buckets && data.buckets.length) {
      html += `<div class="analysis-section"><h3 class="analysis-section__title">Categories</h3>`;
      html += `<div class="buckets-grid">`;
      data.buckets.forEach(bucket => {
        html += `<div class="bucket-card">`;
        html += `<h4 class="bucket-card__name">${esc(bucket.name)}</h4>`;
        if (bucket.notes && bucket.notes.length) {
          html += `<ul class="bucket-card__list">`;
          bucket.notes.forEach(note => {
            const priClass = (note.priority || '').toLowerCase();
            html += `<li>
              <span class="bucket-note__title">${esc(note.title || note.id)}</span>
              ${note.priority ? `<span class="badge badge--pri badge--pri--${priClass}">${esc(note.priority)}</span>` : ''}
            </li>`;
          });
          html += `</ul>`;
        } else {
          html += `<p class="bucket-card__empty">No notes</p>`;
        }
        html += `</div>`;
      });
      html += `</div></div>`;
    }

    // Todos
    if (data.todos && data.todos.length) {
      html += `<div class="analysis-section"><h3 class="analysis-section__title">Suggested To-Dos</h3>`;
      html += `<div class="todo-list">`;
      data.todos.forEach(todo => {
        const priClass = (todo.priority || '').toLowerCase();
        html += `<div class="todo-item">
          <div class="todo-item__main">
            <span class="todo-item__text">${esc(todo.task)}</span>
            ${todo.when ? `<span class="todo-item__when">${esc(todo.when)}</span>` : ''}
          </div>
          ${todo.priority ? `<span class="badge badge--pri badge--pri--${priClass}">${esc(todo.priority)}</span>` : ''}
        </div>`;
      });
      html += `</div></div>`;
    }

    if (!html) {
      html = `<p class="empty-state">Analysis returned no data.</p>`;
    }

    output.innerHTML = html;

    // Update dashboard stats
    const modeEl = $('#statAnalysisMode');
    const timeEl = $('#statLastAnalysis');
    if (modeEl && data.mode) modeEl.textContent = data.mode;
    if (timeEl && data.generated_at) timeEl.textContent = relativeTime(data.generated_at);
  }

  function populateCategoryFilter(data) {
    const sel = $('#categoryFilter');
    if (!sel || !data || !data.buckets) return;
    // Keep the first (empty / all) option, remove the rest
    const firstOpt = sel.querySelector('option');
    sel.innerHTML = '';
    if (firstOpt) sel.appendChild(firstOpt);
    data.buckets.forEach(b => {
      const opt = document.createElement('option');
      opt.value = b.name;
      opt.textContent = b.name;
      sel.appendChild(opt);
    });
  }

  // --------------------------------------------------------------------------
  // Tasks
  // --------------------------------------------------------------------------

  function initTasks() {
    const filter = $('#taskStatusFilter');
    if (filter) filter.addEventListener('change', () => loadTasks());
  }

  async function loadTasks() {
    const container = $('#tasks');
    const statusEl = $('#taskStatus');
    if (!container) return;

    skeletonCards(container, 3);

    const filter = $('#taskStatusFilter');
    const status = filter ? filter.value : 'open';

    try {
      const tasks = await api('/api/tasks', { params: { status } });
      renderTasks(container, tasks);
      if (statusEl) statusEl.textContent = tasks.length
        ? `${tasks.length} task${tasks.length !== 1 ? 's' : ''}`
        : '';

      // Update dashboard
      const openCount = status === 'open' ? tasks.length : null;
      if (openCount !== null) {
        const statEl = $('#statOpenTasks');
        if (statEl) statEl.textContent = openCount;
      }
    } catch (err) {
      container.innerHTML = `<p class="empty-state">Failed to load tasks.</p>`;
      showToast(err.message, 'error');
    }
  }

  function renderTasks(container, tasks) {
    if (!tasks || tasks.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:.4">
            <path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
          </svg>
          <p>No tasks here.</p>
        </div>`;
      return;
    }

    container.innerHTML = tasks.map(task => taskCardHTML(task)).join('');

    // Attach action listeners
    container.querySelectorAll('[data-task-action]').forEach(btn => {
      btn.addEventListener('click', () => handleTaskAction(btn.dataset.taskAction, btn.dataset.taskId));
    });
  }

  function taskCardHTML(task) {
    const priClass = (task.priority || '').toLowerCase();
    const statusClass = (task.status || '').toLowerCase();

    let actions = '';
    if (task.status === 'open') {
      actions = `
        <button class="btn btn--sm btn--primary" data-task-action="complete" data-task-id="${task.id}">Complete</button>
        <button class="btn btn--sm btn--ghost" data-task-action="dismiss" data-task-id="${task.id}">Dismiss</button>`;
    } else {
      actions = `
        <button class="btn btn--sm btn--ghost" data-task-action="reopen" data-task-id="${task.id}">Reopen</button>`;
    }

    return `
      <div class="task-card task-card--${statusClass}" data-task-id="${task.id}">
        <div class="task-card__body">
          <div class="task-card__header">
            <span class="task-card__text">${esc(task.text)}</span>
            ${task.priority ? `<span class="badge badge--pri badge--pri--${priClass}">${esc(task.priority)}</span>` : ''}
          </div>
          <div class="task-card__meta">
            ${task.timing_text ? `<span class="task-card__timing">${esc(task.timing_text)}</span>` : ''}
            <span class="task-card__status badge badge--status--${statusClass}">${esc(task.status)}</span>
            <span class="task-card__time">${relativeTime(task.created_at)}</span>
          </div>
          ${task.source_item_ids && task.source_item_ids.length ? `<div class="task-card__sources">Sources: ${task.source_item_ids.map(id => `<code>${esc(String(id))}</code>`).join(', ')}</div>` : ''}
        </div>
        <div class="task-card__actions">${actions}</div>
      </div>`;
  }

  async function handleTaskAction(action, taskId) {
    const endpoints = {
      complete: `/api/tasks/${taskId}/complete`,
      dismiss: `/api/tasks/${taskId}/dismiss`,
      reopen: `/api/tasks/${taskId}/reopen`,
    };
    const url = endpoints[action];
    if (!url) return;

    const card = $(`.task-card[data-task-id="${taskId}"]`);
    const btn = card ? card.querySelector(`[data-task-action="${action}"]`) : null;
    setButtonLoading(btn, true);

    try {
      await api(url, { method: 'POST' });
      const labels = { complete: 'completed', dismiss: 'dismissed', reopen: 'reopened' };
      showToast(`Task ${labels[action]}!`, 'success');
      await loadTasks();
    } catch (err) {
      showToast(err.message, 'error');
      setButtonLoading(btn, false);
    }
  }

  // --------------------------------------------------------------------------
  // Dashboard
  // --------------------------------------------------------------------------

  async function refreshDashboard() {
    try {
      // Fetch items count
      const items = await api('/api/items', { params: { limit: 1 } });
      // We'll use a full fetch to get the count (the endpoint returns array)
      const allItems = await api('/api/items', { params: { limit: 9999 } });
      const statTotal = $('#statTotalItems');
      if (statTotal) statTotal.textContent = Array.isArray(allItems) ? allItems.length : 0;

      // Fetch open tasks count
      const openTasks = await api('/api/tasks', { params: { status: 'open' } });
      const statOpen = $('#statOpenTasks');
      if (statOpen) statOpen.textContent = Array.isArray(openTasks) ? openTasks.length : 0;

      // Fetch latest analysis for mode / time
      try {
        const analysis = await api('/api/analyze/latest');
        if (analysis) {
          const modeEl = $('#statAnalysisMode');
          const timeEl = $('#statLastAnalysis');
          if (modeEl) modeEl.textContent = analysis.mode || '—';
          if (timeEl) timeEl.textContent = analysis.generated_at ? relativeTime(analysis.generated_at) : '—';
        }
      } catch { /* no analysis yet */ }
    } catch (err) {
      // Dashboard is best-effort
      console.warn('Dashboard refresh error:', err);
    }
  }

  // --------------------------------------------------------------------------
  // Keyboard shortcuts (global)
  // --------------------------------------------------------------------------

  function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
      // Ctrl+Enter to submit note (handled on textarea too, but also globally)
      if (e.ctrlKey && e.key === 'Enter') {
        const active = document.activeElement;
        const textarea = $('#noteText');
        if (active === textarea) {
          e.preventDefault();
          addNote();
        }
      }
    });
  }

  // --------------------------------------------------------------------------
  // Init
  // --------------------------------------------------------------------------

  function init() {
    initTheme();
    initNavigation();
    initNotes();
    initAnalysis();
    initTasks();
    initKeyboardShortcuts();
    syncFiltersFromUrl();

    // Inject dynamic styles for toasts, skeletons, spinners, and animations
    injectDynamicStyles();
  }

  function injectDynamicStyles() {
    if ($('#life-inbox-dynamic-styles')) return;
    const style = document.createElement('style');
    style.id = 'life-inbox-dynamic-styles';
    style.textContent = `
      /* Spinner */
      .spinner {
        display: inline-block;
        width: 16px; height: 16px;
        border: 2px solid currentColor;
        border-right-color: transparent;
        border-radius: 50%;
        animation: spin .6s linear infinite;
        vertical-align: middle;
        margin-right: 6px;
        opacity: .7;
      }
      .spinner--lg { width: 28px; height: 28px; border-width: 3px; }
      @keyframes spin { to { transform: rotate(360deg); } }

      /* Toast */
      .toast {
        display: flex; align-items: center; gap: 10px;
        padding: 12px 16px;
        border-radius: 10px;
        background: var(--toast-bg, #fff);
        color: var(--toast-fg, #1a1a2e);
        box-shadow: 0 8px 30px rgba(0,0,0,.12);
        margin-bottom: 8px;
        transform: translateX(120%);
        opacity: 0;
        transition: transform .3s cubic-bezier(.4,0,.2,1), opacity .3s ease;
        max-width: 380px;
        font-size: .9rem;
        pointer-events: auto;
      }
      [data-theme="dark"] .toast {
        --toast-bg: #2a2a3e;
        --toast-fg: #e0e0e8;
        box-shadow: 0 8px 30px rgba(0,0,0,.3);
      }
      .toast--visible { transform: translateX(0); opacity: 1; }
      .toast--exit { transform: translateX(120%); opacity: 0; }
      .toast--success { border-left: 4px solid #22c55e; }
      .toast--error { border-left: 4px solid #ef4444; }
      .toast--info { border-left: 4px solid #3b82f6; }
      .toast__icon { flex-shrink: 0; display: flex; }
      .toast--success .toast__icon { color: #22c55e; }
      .toast--error .toast__icon { color: #ef4444; }
      .toast--info .toast__icon { color: #3b82f6; }
      .toast__msg { flex: 1; }
      .toast__close {
        background: none; border: none; cursor: pointer;
        font-size: 1.2rem; color: inherit; opacity: .5;
        padding: 0 0 0 4px; line-height: 1;
      }
      .toast__close:hover { opacity: 1; }

      /* Toast container */
      .toast-container {
        position: fixed; top: 20px; right: 20px;
        z-index: 9999; display: flex; flex-direction: column;
        align-items: flex-end; pointer-events: none;
      }

      /* Skeleton loading */
      .skeleton {
        background: linear-gradient(90deg, var(--skel-base, #e2e8f0) 25%, var(--skel-shine, #f1f5f9) 50%, var(--skel-base, #e2e8f0) 75%);
        background-size: 200% 100%;
        animation: shimmer 1.5s infinite;
        border-radius: 6px;
      }
      [data-theme="dark"] .skeleton {
        --skel-base: #2a2a3e;
        --skel-shine: #3a3a50;
      }
      .skeleton-line { height: 14px; margin-bottom: 10px; }
      .skeleton-line--title { height: 18px; width: 60%; }
      .skeleton-line--short { width: 40%; }
      .skeleton-card { padding: 20px; }
      @keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

      /* Button loading */
      .btn--loading { opacity: .7; cursor: wait; }

      /* Card removal animation */
      .note-card--removing {
        opacity: 0;
        transform: translateX(30px) scale(.96);
        transition: all .3s ease;
      }

      /* Edit textarea */
      .edit-textarea {
        width: 100%; padding: 10px; border-radius: 8px;
        border: 1.5px solid var(--border-color, #d1d5db);
        background: var(--input-bg, #fff);
        color: inherit; font: inherit; resize: vertical;
        margin-bottom: 8px;
      }
      [data-theme="dark"] .edit-textarea {
        --border-color: #444;
        --input-bg: #1e1e2e;
      }
      .edit-actions { display: flex; gap: 8px; }

      /* Analysis sections */
      .analysis-meta { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
      .analysis-meta__time { color: var(--text-muted, #6b7280); font-size: .85rem; }
      .analysis-section { margin-bottom: 24px; }
      .analysis-section__title {
        font-size: 1.05rem; font-weight: 600;
        margin-bottom: 12px; padding-bottom: 6px;
        border-bottom: 1px solid var(--border-color, #e5e7eb);
      }
      .analysis-loading { text-align: center; padding: 40px 20px; }
      .analysis-loading p { margin-top: 12px; color: var(--text-muted, #6b7280); }

      /* Priority view */
      .priority-group { margin-bottom: 14px; }
      .priority-group__label { font-size: .95rem; font-weight: 500; display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
      .priority-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
      .priority-dot--high { background: #ef4444; }
      .priority-dot--medium { background: #f59e0b; }
      .priority-dot--low { background: #22c55e; }
      .priority-list { list-style: disc; padding-left: 28px; margin: 0; }
      .priority-list li { margin-bottom: 4px; font-size: .9rem; }

      /* Buckets grid */
      .buckets-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; }
      .bucket-card {
        border: 1px solid var(--border-color, #e5e7eb);
        border-radius: 10px; padding: 14px;
        background: var(--card-bg, #fff);
      }
      [data-theme="dark"] .bucket-card { --border-color: #333; --card-bg: #23233a; }
      .bucket-card__name { font-size: .95rem; font-weight: 600; margin-bottom: 8px; }
      .bucket-card__list { list-style: none; padding: 0; margin: 0; }
      .bucket-card__list li {
        display: flex; align-items: center; justify-content: space-between;
        padding: 4px 0; font-size: .85rem;
        border-bottom: 1px solid var(--border-color, #f0f0f0);
      }
      .bucket-card__list li:last-child { border-bottom: none; }
      .bucket-card__empty { font-size: .85rem; color: var(--text-muted, #9ca3af); }

      /* Todo list */
      .todo-list { display: flex; flex-direction: column; gap: 8px; }
      .todo-item {
        display: flex; align-items: center; justify-content: space-between;
        padding: 10px 14px; border-radius: 8px;
        border: 1px solid var(--border-color, #e5e7eb);
        background: var(--card-bg, #fff);
        gap: 10px;
      }
      [data-theme="dark"] .todo-item { --border-color: #333; --card-bg: #23233a; }
      .todo-item__main { flex: 1; }
      .todo-item__text { display: block; font-size: .9rem; }
      .todo-item__when { font-size: .8rem; color: var(--text-muted, #6b7280); margin-top: 2px; display: block; }

      /* Badges */
      .badge {
        display: inline-block; font-size: .72rem; font-weight: 600;
        padding: 2px 8px; border-radius: 20px;
        text-transform: uppercase; letter-spacing: .03em;
      }
      .badge--type { background: #e0e7ff; color: #3730a3; }
      [data-theme="dark"] .badge--type { background: #312e81; color: #a5b4fc; }
      .badge--status { background: #f0fdf4; color: #166534; }
      [data-theme="dark"] .badge--status { background: #14532d; color: #86efac; }
      .badge--mode { background: #fef3c7; color: #92400e; }
      [data-theme="dark"] .badge--mode { background: #78350f; color: #fcd34d; }
      .badge--pri { font-size: .7rem; }
      .badge--pri--high { background: #fef2f2; color: #b91c1c; }
      [data-theme="dark"] .badge--pri--high { background: #7f1d1d; color: #fca5a5; }
      .badge--pri--medium { background: #fffbeb; color: #b45309; }
      [data-theme="dark"] .badge--pri--medium { background: #78350f; color: #fcd34d; }
      .badge--pri--low { background: #f0fdf4; color: #166534; }
      [data-theme="dark"] .badge--pri--low { background: #14532d; color: #86efac; }
      .badge--status--open { background: #dbeafe; color: #1e40af; }
      [data-theme="dark"] .badge--status--open { background: #1e3a5f; color: #93c5fd; }
      .badge--status--completed { background: #d1fae5; color: #065f46; }
      [data-theme="dark"] .badge--status--completed { background: #064e3b; color: #6ee7b7; }
      .badge--status--dismissed { background: #f3f4f6; color: #6b7280; }
      [data-theme="dark"] .badge--status--dismissed { background: #374151; color: #d1d5db; }

      /* Task cards */
      .task-card {
        display: flex; align-items: flex-start; justify-content: space-between;
        padding: 14px 16px; border-radius: 10px;
        border: 1px solid var(--border-color, #e5e7eb);
        background: var(--card-bg, #fff);
        margin-bottom: 10px; gap: 12px;
        transition: box-shadow .2s;
      }
      .task-card:hover { box-shadow: 0 2px 12px rgba(0,0,0,.06); }
      [data-theme="dark"] .task-card { --border-color: #333; --card-bg: #23233a; }
      [data-theme="dark"] .task-card:hover { box-shadow: 0 2px 12px rgba(0,0,0,.2); }
      .task-card--completed { opacity: .65; }
      .task-card--dismissed { opacity: .5; }
      .task-card__body { flex: 1; min-width: 0; }
      .task-card__header { display: flex; align-items: flex-start; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
      .task-card__text { font-size: .95rem; font-weight: 500; }
      .task-card__meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: .8rem; color: var(--text-muted, #6b7280); }
      .task-card__timing { font-style: italic; }
      .task-card__sources { font-size: .75rem; color: var(--text-muted, #9ca3af); margin-top: 6px; }
      .task-card__sources code {
        background: var(--code-bg, #f3f4f6); padding: 1px 5px; border-radius: 4px; font-size: .72rem;
      }
      [data-theme="dark"] .task-card__sources code { --code-bg: #374151; }
      .task-card__actions { display: flex; gap: 6px; flex-shrink: 0; align-items: flex-start; flex-wrap: wrap; }

      /* Empty state */
      .empty-state {
        text-align: center; padding: 40px 20px;
        color: var(--text-muted, #6b7280); font-size: .95rem;
      }
      .empty-state svg { margin: 0 auto 12px; display: block; }

      /* Note card */
      .note-card {
        display: flex; align-items: flex-start; justify-content: space-between;
        padding: 14px 16px; border-radius: 10px;
        border: 1px solid var(--border-color, #e5e7eb);
        background: var(--card-bg, #fff);
        margin-bottom: 10px; gap: 12px;
        transition: box-shadow .2s, opacity .3s, transform .3s;
      }
      .note-card:hover { box-shadow: 0 2px 12px rgba(0,0,0,.06); }
      [data-theme="dark"] .note-card:not(.skeleton-card) { --border-color: #333; --card-bg: #23233a; }
      [data-theme="dark"] .note-card:hover { box-shadow: 0 2px 12px rgba(0,0,0,.2); }
      .note-card__body { flex: 1; min-width: 0; }
      .note-card__header { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
      .note-card__title { font-size: .95rem; font-weight: 600; margin: 0; }
      .note-card__time { font-size: .78rem; color: var(--text-muted, #9ca3af); white-space: nowrap; }
      .note-card__text { font-size: .9rem; margin: 0; white-space: pre-wrap; word-break: break-word; color: var(--text-primary, inherit); }
      .note-card__badges { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
      .note-card__actions { display: flex; gap: 4px; flex-shrink: 0; }

      /* Ghost / danger button helpers */
      .btn--ghost { background: transparent; border: 1px solid transparent; }
      .btn--ghost:hover { background: var(--hover-bg, rgba(0,0,0,.05)); }
      [data-theme="dark"] .btn--ghost:hover { --hover-bg: rgba(255,255,255,.08); }
      .btn--danger { color: #ef4444; }
      .btn--danger:hover { background: #fef2f2; }
      [data-theme="dark"] .btn--danger:hover { background: rgba(239,68,68,.15); }

      /* Responsive */
      @media (max-width: 768px) {
        .buckets-grid { grid-template-columns: 1fr; }
        .task-card, .note-card { flex-direction: column; }
        .task-card__actions, .note-card__actions { align-self: flex-end; }
      }
    `;
    document.head.appendChild(style);
  }

  // Start the app
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
