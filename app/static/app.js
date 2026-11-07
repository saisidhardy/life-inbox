// ============================================================================
// Life Inbox — Main Application JavaScript
// A personal AI-powered inbox organizer
// ============================================================================

(() => {
  'use strict';

  let currentLoadedItems = [];
  let currentTasks = [];

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

  /** Sanitize a string for safe insertion as HTML text content or attribute values. */
  function esc(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  const AUTH_STORAGE_KEY = 'life_inbox_token';

  function getStoredAuthToken() {
    try {
      return localStorage.getItem(AUTH_STORAGE_KEY) || '';
    } catch {
      return '';
    }
  }

  function setStoredAuthToken(token) {
    try {
      if (token) {
        localStorage.setItem(AUTH_STORAGE_KEY, token.trim());
      } else {
        localStorage.removeItem(AUTH_STORAGE_KEY);
      }
    } catch { /* ignore */ }
  }

  function promptForAuthToken(message) {
    const current = getStoredAuthToken();
    const promptMsg = message || 'Enter your Life Inbox Access Token (APP_TOKEN):';
    const entered = window.prompt(promptMsg, current);
    if (entered !== null) {
      setStoredAuthToken(entered);
      showToast(entered ? 'Access token saved.' : 'Access token cleared.', 'info');
      return entered.trim();
    }
    return null;
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
    requestAnimationFrame(() => toast.classList.add('toast--visible'));

    const dismiss = () => {
      toast.classList.remove('toast--visible');
      toast.classList.add('toast--exit');
      toast.addEventListener('transitionend', () => toast.remove(), { once: true });
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
    const fetchOpts = { method, headers: opts.headers ? { ...opts.headers } : {} };
    if (body !== undefined) {
      fetchOpts.headers['Content-Type'] = 'application/json';
      fetchOpts.body = JSON.stringify(body);
    }

    const token = getStoredAuthToken();
    if (token) {
      fetchOpts.headers['Authorization'] = `Bearer ${token}`;
      fetchOpts.headers['X-App-Token'] = token;
    }

    let res = await fetch(url, fetchOpts);

    // If unauthorized on an API call, prompt user for token and retry once
    if (res.status === 401 && path.startsWith('/api/') && path !== '/api/health') {
      const enteredToken = promptForAuthToken('Life Inbox requires an access token (APP_TOKEN):');
      if (enteredToken) {
        fetchOpts.headers['Authorization'] = `Bearer ${enteredToken}`;
        fetchOpts.headers['X-App-Token'] = enteredToken;
        res = await fetch(url, fetchOpts);
      }
    }

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
    document.documentElement.setAttribute('data-theme', theme);
    const btn = $('#themeToggle');
    if (!btn) return;
    const sunIcon = btn.querySelector('.icon-sun');
    const moonIcon = btn.querySelector('.icon-moon');
    if (sunIcon) sunIcon.classList.toggle('hidden', theme === 'light');
    if (moonIcon) moonIcon.classList.toggle('hidden', theme === 'dark');
  }

  // --------------------------------------------------------------------------
  // Section navigation
  // --------------------------------------------------------------------------

  const SECTIONS = ['dashboard', 'inbox', 'analysis', 'tasks', 'integrations'];

  function initNavigation() {
    const navItems = $$('.nav-item[data-section]');

    navItems.forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const section = item.dataset.section;
        navigateTo(section);
        const sidebar = $('.sidebar');
        if (sidebar) sidebar.classList.remove('open');
      });
    });

    const menuToggle = $('.menu-toggle');
    if (menuToggle) {
      menuToggle.addEventListener('click', () => {
        const sidebar = $('.sidebar');
        if (sidebar) sidebar.classList.toggle('open');
      });
    }

    const hash = location.hash.replace('#', '');
    navigateTo(SECTIONS.includes(hash) ? hash : 'dashboard');

    window.addEventListener('hashchange', () => {
      const h = location.hash.replace('#', '');
      if (SECTIONS.includes(h)) navigateTo(h, false);
    });
  }

  function navigateTo(section, pushHash = true) {
    if (!SECTIONS.includes(section)) section = 'dashboard';

    SECTIONS.forEach(s => {
      const el = $(`#${s}-section`);
      if (el) el.classList.toggle('hidden', s !== section);
    });

    $$('.nav-item[data-section]').forEach(item => {
      item.classList.toggle('active', item.dataset.section === section);
    });

    if (pushHash) history.replaceState(null, '', `#${section}`);

    if (section === 'inbox') loadNotes();
    if (section === 'tasks') loadTasks();
    if (section === 'dashboard') {
      refreshDashboard();
      loadBriefing();
    }
    if (section === 'analysis') loadLatestAnalysis();
    if (section === 'integrations') initIntegrationsHub();
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
      if (btn.dataset.origText) delete btn.dataset.origText;
    }
  }

  // --------------------------------------------------------------------------
  // Smart Content Formatter (Markdown, Checklists, URLs, #Tags)
  // --------------------------------------------------------------------------

  function formatInlineMarkup(text) {
    if (!text) return '';
    // Escape all HTML characters first (XSS prevention)
    let s = esc(text);

    // Clickable URLs (must strictly start with http:// or https:// and contain only valid safe URL characters)
    s = s.replace(
      /(https?:\/\/[a-zA-Z0-9\-._~:/?#[\]@!$&*+,;=%]+[a-zA-Z0-9/])/g,
      match => {
        if (!/^https?:\/\//i.test(match)) return match;
        return `<a href="${match}" target="_blank" rel="noopener noreferrer" class="note-link">${match} <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg></a>`;
      }
    );

    // Hashtags (strictly safe characters)
    s = s.replace(
      /(^|\s)(#[a-zA-Z0-9_\-]+)/g,
      '$1<span class="note-tag" data-tag="$2" title="Filter by $2">$2</span>'
    );

    // Inline code (escaped content)
    s = s.replace(/`([^`]+)`/g, '<code class="note-inline-code">$1</code>');
    return s;
  }

  function renderSmartContent(rawText, itemId) {
    if (!rawText) return '';
    const safeId = parseInt(itemId, 10) || 0;
    const lines = rawText.split('\n');
    let checkboxCounter = 0;
    const formatted = lines.map(line => {
      const checkMatch = line.match(/^(\s*[-*]\s*)\[([ xX])\]\s*(.*)$/);
      if (checkMatch) {
        const prefix = checkMatch[1];
        const isChecked = checkMatch[2].toLowerCase() === 'x';
        const rest = formatInlineMarkup(checkMatch[3]);
        const idx = checkboxCounter++;
        return `${esc(prefix)}<label class="note-checklist-item" style="cursor:pointer;display:inline-flex;align-items:baseline;"><input type="checkbox" class="note-checkbox" data-item-id="${safeId}" data-check-idx="${idx}" ${isChecked ? 'checked' : ''}><span class="${isChecked ? 'checked-item' : ''}">${rest}</span></label>`;
      }
      return formatInlineMarkup(line);
    });
    return formatted.join('<br>');
  }

  async function toggleNoteCheckbox(itemId, lineIdx) {
    const item = currentLoadedItems.find(it => it.id === itemId);
    if (!item || !item.raw_text) return;

    const lines = item.raw_text.split('\n');
    let currentCheckIdx = 0;
    for (let i = 0; i < lines.length; i++) {
      if (/^\s*[-*]\s*\[([ xX])\]/.test(lines[i])) {
        if (currentCheckIdx === lineIdx) {
          if (/^\s*[-*]\s*\[ \]/.test(lines[i])) {
            lines[i] = lines[i].replace(/^(\s*[-*]\s*)\[ \]/, '$1[x]');
          } else {
            lines[i] = lines[i].replace(/^(\s*[-*]\s*)\[[xX]\]/, '$1[ ]');
          }
          break;
        }
        currentCheckIdx++;
      }
    }
    const updatedText = lines.join('\n');
    try {
      await api(`/api/items/${itemId}`, { method: 'PUT', body: { raw_text: updatedText } });
      showToast('Checklist updated!', 'success');
      await loadNotes();
    } catch (err) {
      showToast('Could not update checklist: ' + err.message, 'error');
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

    // Quick template buttons
    const templateMap = {
      meeting: "#meeting with [Name]\n- Discussed: \n- Decisions: \n- Next steps: \n  - [ ] ",
      idea: "💡 #idea [Title]\n- Problem: \n- Potential Solution: \n- First step: \n  - [ ] ",
      checklist: "#checklist To Do / Buy:\n- [ ] Item 1\n- [ ] Item 2\n- [ ] Item 3",
      resource: "📚 #learning [Title/Topic]\n- Link/Source: \n- Key Takeaways: ",
      clear: "",
    };

    $$('.btn-template').forEach(btn => {
      btn.addEventListener('click', () => {
        const type = btn.dataset.template;
        const t = templateMap[type];
        if (!textarea) return;
        if (type === 'clear') {
          textarea.value = '';
          textarea.focus();
          return;
        }
        if (textarea.value.trim()) {
          textarea.value += '\n\n' + t;
        } else {
          textarea.value = t;
        }
        textarea.focus();
      });
    });

    // Export buttons
    const exportMdBtn = $('#exportMdBtn');
    if (exportMdBtn) {
      exportMdBtn.addEventListener('click', () => {
        window.location.href = '/api/export?format=markdown';
        showToast('Exporting notes to Markdown…', 'info');
      });
    }
    const exportJsonBtn = $('#exportJsonBtn');
    if (exportJsonBtn) {
      exportJsonBtn.addEventListener('click', () => {
        window.location.href = '/api/export?format=json';
        showToast('Exporting JSON backup…', 'info');
      });
    }

    // Import modal & handler
    const importBtn = $('#importBtn');
    const importModal = $('#importModal');
    const cancelImportBtn = $('#cancelImportBtn');
    const confirmImportBtn = $('#confirmImportBtn');
    const importText = $('#importText');

    if (importBtn && importModal) {
      importBtn.addEventListener('click', () => {
        importModal.style.display = 'flex';
        if (importText) { importText.value = ''; importText.focus(); }
      });
    }
    if (cancelImportBtn && importModal) {
      cancelImportBtn.addEventListener('click', () => {
        importModal.style.display = 'none';
      });
    }
    if (confirmImportBtn && importModal && importText) {
      confirmImportBtn.addEventListener('click', async () => {
        const val = importText.value.trim();
        if (!val) { showToast('Please enter some notes to import.', 'error'); return; }
        const notes = val.split(/\n\s*---\s*\n/).map(s => s.trim()).filter(Boolean);
        if (!notes.length) { showToast('No valid notes found.', 'error'); return; }
        setButtonLoading(confirmImportBtn, true);
        try {
          const res = await api('/api/import', { method: 'POST', body: { notes } });
          showToast(`Imported ${res.imported_count} note(s)!`, 'success');
          importModal.style.display = 'none';
          await loadNotes();
          refreshDashboard();
        } catch (err) {
          showToast(err.message, 'error');
        } finally {
          setButtonLoading(confirmImportBtn, false);
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
        setTimeout(() => {
          syncFiltersToUrl();
          loadNotes();
        }, 0);
      });
    }

    // File upload attachment & drag-and-drop
    const fileInput = $('#fileUploadInput');
    const attachBtn = $('#attachFileBtn');
    const preview = $('#fileUploadPreview');
    const previewName = $('#filePreviewName');
    const previewSize = $('#filePreviewSize');
    const previewIcon = $('#filePreviewIcon');
    const removeFileBtn = $('#removeFileBtn');

    if (attachBtn && fileInput) {
      attachBtn.addEventListener('click', () => fileInput.click());
    }

    if (fileInput) {
      fileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files[0]) {
          setPendingFile(e.target.files[0]);
        }
      });
    }

    function setPendingFile(file) {
      window._pendingUploadFile = file;
      if (!file) {
        if (preview) preview.style.display = 'none';
        if (fileInput) fileInput.value = '';
        return;
      }
      if (preview) preview.style.display = 'flex';
      if (previewName) previewName.textContent = file.name;
      if (previewSize) previewSize.textContent = `${(file.size / 1024).toFixed(1)} KB`;
      if (previewIcon) {
        const isImg = file.type.startsWith('image/');
        const isPdf = file.name.toLowerCase().endsWith('.pdf');
        const isAudio = file.type.startsWith('audio/');
        previewIcon.textContent = isImg ? '🖼️' : (isPdf ? '📄' : (isAudio ? '🎙️' : '📎'));
      }
    }

    if (removeFileBtn) {
      removeFileBtn.addEventListener('click', () => setPendingFile(null));
    }

    if (textarea) {
      ['dragenter', 'dragover'].forEach(eventName => {
        textarea.addEventListener(eventName, (e) => {
          e.preventDefault();
          textarea.style.borderColor = 'var(--color-primary, #0284c7)';
        });
      });
      ['dragleave', 'drop'].forEach(eventName => {
        textarea.addEventListener(eventName, (e) => {
          e.preventDefault();
          textarea.style.borderColor = '';
        });
      });
      textarea.addEventListener('drop', (e) => {
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
          setPendingFile(e.dataTransfer.files[0]);
          showToast(`Attached ${e.dataTransfer.files[0].name}`, 'info');
        }
      });
    }
  }

  async function addNote() {
    const textarea = $('#noteText');
    const addBtn = $('#addNoteBtn');
    const status = $('#noteStatus');
    const text = textarea ? textarea.value.trim() : '';
    const pendingFile = window._pendingUploadFile;

    if (!text && !pendingFile) {
      if (status) status.textContent = 'Please enter some text or attach a file.';
      showToast('Please enter some text or attach a file.', 'error');
      return;
    }

    setButtonLoading(addBtn, true);

    if (pendingFile) {
      if (status) status.textContent = 'Uploading and analyzing document with AI…';
      try {
        const formData = new FormData();
        formData.append('file', pendingFile);

        const token = getStoredAuthToken();
        const headers = {};
        if (token) {
          headers['Authorization'] = `Bearer ${token}`;
          headers['X-App-Token'] = token;
        }

        const res = await fetch('/api/upload?auto_process=true', {
          method: 'POST',
          headers,
          body: formData,
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || 'Upload failed');
        }

        const data = await res.json();
        const cat = data.auto_analysis ? data.auto_analysis.category : 'Document';
        const taskCount = data.auto_analysis && data.auto_analysis.extracted_tasks ? data.auto_analysis.extracted_tasks.length : 0;
        const taskMsg = taskCount > 0 ? ` (${taskCount} task${taskCount > 1 ? 's' : ''} extracted)` : '';
        showToast(`Document processed! AI categorized as [${cat}]${taskMsg}`, 'success');

        window._pendingUploadFile = null;
        const preview = $('#fileUploadPreview');
        const fileInput = $('#fileUploadInput');
        if (preview) preview.style.display = 'none';
        if (fileInput) fileInput.value = '';
        if (textarea) textarea.value = '';
        if (status) status.textContent = '';
        await loadNotes();
        await loadTasks();
        refreshDashboard();
      } catch (err) {
        showToast(err.message, 'error');
        if (status) status.textContent = err.message;
      } finally {
        setButtonLoading(addBtn, false);
      }
      return;
    }

    if (status) status.textContent = 'Adding…';

    try {
      const saved = await api('/api/items?auto_process=true', { method: 'POST', body: { raw_text: text } });
      if (saved && saved.auto_analysis) {
        const cat = saved.auto_analysis.category || 'General';
        const taskCount = (saved.auto_analysis.extracted_tasks || []).length;
        const taskMsg = taskCount > 0 ? ` (${taskCount} task${taskCount > 1 ? 's' : ''} extracted)` : '';
        showToast(`Note captured! AI categorized as [${cat}]${taskMsg}`, 'success');
      } else {
        showToast('Note added!', 'success');
      }
      if (textarea) textarea.value = '';
      if (status) status.textContent = '';
      await loadNotes();
      await loadTasks();
      refreshDashboard();
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
      currentLoadedItems = items;
      renderNotes(container, items);
      if (statusEl) {
        statusEl.textContent = items.length
          ? `${items.length} item${items.length !== 1 ? 's' : ''} found`
          : '';
      }
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

    // Attach edit / delete / copy listeners
    container.querySelectorAll('[data-action="enhance"]').forEach(btn => {
      btn.addEventListener('click', () => openEnhanceModal(btn.dataset.id));
    });
    container.querySelectorAll('[data-action="edit"]').forEach(btn => {
      btn.addEventListener('click', () => startEditNote(btn.closest('.note-card'), btn.dataset.id));
    });
    container.querySelectorAll('[data-action="delete"]').forEach(btn => {
      btn.addEventListener('click', () => deleteNote(btn.dataset.id));
    });
    container.querySelectorAll('[data-action="copy"]').forEach(btn => {
      btn.addEventListener('click', () => {
        const item = items.find(it => String(it.id) === String(btn.dataset.id));
        if (item && item.raw_text) {
          navigator.clipboard.writeText(item.raw_text).then(() => {
            showToast('Note copied to clipboard!', 'success');
          });
        }
      });
    });

    // Checkbox toggles
    container.querySelectorAll('.note-checkbox').forEach(cb => {
      cb.addEventListener('change', async (e) => {
        e.stopPropagation();
        const id = parseInt(cb.dataset.itemId, 10);
        const idx = parseInt(cb.dataset.checkIdx, 10);
        await toggleNoteCheckbox(id, idx);
      });
    });

    // Hashtag clicks
    container.querySelectorAll('.note-tag').forEach(tagEl => {
      tagEl.addEventListener('click', (e) => {
        e.stopPropagation();
        const searchInput = $('#itemSearch');
        if (searchInput) {
          searchInput.value = tagEl.dataset.tag;
          syncFiltersToUrl();
          loadNotes();
        }
      });
    });
  }

  function noteCardHTML(item) {
    const badges = [];
    if (item.item_type) badges.push(`<span class="badge badge--type">${esc(item.item_type)}</span>`);
    if (item.processing_status) badges.push(`<span class="badge badge--status">${esc(item.processing_status)}</span>`);
    if (item.source_url) {
      const isImg = item.item_type === 'image' || /\.(png|jpe?g|gif|webp)$/i.test(item.source_url);
      badges.push(`<a href="${esc(item.source_url)}" target="_blank" rel="noopener noreferrer" class="badge badge--type" style="text-decoration:none;display:inline-flex;align-items:center;gap:4px;">${isImg ? '🖼️' : '📎'} View Attachment</a>`);
    }

    return `
      <div class="note-card" data-id="${item.id}">
        <div class="note-card__body">
          <div class="note-card__header">
            ${item.title ? `<h4 class="note-card__title">${esc(item.title)}</h4>` : ''}
            <span class="note-card__time" title="${esc(item.created_at)}">${relativeTime(item.created_at)}</span>
          </div>
          <div class="note-card__text">${renderSmartContent(item.raw_text, item.id)}</div>
          ${badges.length ? `<div class="note-card__badges">${badges.join('')}</div>` : ''}
        </div>
        <div class="note-card__actions">
          <button class="btn btn--sm btn--ghost" data-action="enhance" data-id="${item.id}" title="AI Enhance & Action Plan">
            <span style="font-size:0.95rem;">✨</span>
          </button>
          <button class="btn btn--sm btn--ghost" data-action="copy" data-id="${item.id}" title="Copy Note">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
          </button>
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
    const bodyEl = card.querySelector('.note-card__body');
    const actionsEl = card.querySelector('.note-card__actions');
    const item = currentLoadedItems.find(it => String(it.id) === String(id));
    if (!bodyEl || !item) return;

    const originalText = item.raw_text;

    bodyEl.innerHTML = `
      <textarea class="edit-textarea" rows="4">${esc(originalText)}</textarea>
      <div class="edit-actions">
        <button class="btn btn--sm btn--primary save-edit-btn">Save</button>
        <button class="btn btn--sm btn--ghost cancel-edit-btn">Cancel</button>
      </div>`;
    if (actionsEl) actionsEl.classList.add('hidden');

    const textarea = bodyEl.querySelector('.edit-textarea');
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);

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
    if (card) card.classList.add('note-card--removing');

    try {
      await api(`/api/items/${id}`, { method: 'DELETE' });
      showToast('Note deleted.', 'success');
      setTimeout(() => {
        loadNotes();
        refreshDashboard();
      }, 300);
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
      loadTasks();
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

    if (data.mode || data.generated_at) {
      html += `<div class="analysis-meta">`;
      if (data.mode) html += `<span class="badge badge--mode">${esc(data.mode)} mode</span>`;
      if (data.generated_at) html += `<span class="analysis-meta__time">${relativeTime(data.generated_at)}</span>`;
      html += `</div>`;
    }

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

    output.innerHTML = html || `<p class="empty-state">Analysis returned no data.</p>`;
  }

  function populateCategoryFilter(data) {
    const sel = $('#categoryFilter');
    if (!sel || !data || !data.buckets) return;
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

    const priFilter = $('#taskPriorityFilter');
    if (priFilter) priFilter.addEventListener('change', () => loadTasks());

    // Task status tabs (Open, Completed, Dismissed, All)
    $$('.task-tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const targetStatus = btn.dataset.taskStatus || 'open';
        if (filter) filter.value = targetStatus;
        $$('.task-tab-btn').forEach(b => {
          b.classList.remove('active', 'btn-primary');
          b.classList.add('btn-ghost');
        });
        btn.classList.add('active', 'btn-primary');
        btn.classList.remove('btn-ghost');
        loadTasks();
      });
    });

    const copyBtn = $('#copyTasksBtn');
    if (copyBtn) {
      copyBtn.addEventListener('click', () => {
        if (!currentTasks || !currentTasks.length) {
          showToast('No tasks to copy.', 'info');
          return;
        }
        const md = currentTasks.map(t => {
          const check = t.status === 'completed' ? 'x' : ' ';
          const when = t.timing_text ? ` · ${t.timing_text}` : '';
          return `- [${check}] **${t.text}** (${t.priority}${when})`;
        }).join('\n');
        navigator.clipboard.writeText(md).then(() => {
          showToast('Copied tasks to clipboard as Markdown!', 'success');
        }).catch(() => {
          showToast('Failed to copy to clipboard.', 'error');
        });
      });
    }
  }

  async function loadTasks() {
    const container = $('#tasks');
    const statusEl = $('#taskStatus');
    if (!container) return;

    skeletonCards(container, 3);

    const filter = $('#taskStatusFilter');
    const priFilter = $('#taskPriorityFilter');
    const activeStatus = filter ? filter.value : 'open';
    const priValue = priFilter ? priFilter.value : '';

    try {
      // Fetch all tasks to update counts across all tabs accurately
      const allTasks = await api('/api/tasks', { params: { status: 'all' } });
      window._allTasks = allTasks;
      const openTasks = allTasks.filter(t => t.status === 'open');
      const completedTasks = allTasks.filter(t => t.status === 'completed');
      const dismissedTasks = allTasks.filter(t => t.status === 'dismissed');

      // Update badge counts on tabs
      const countOpen = $('#taskCountOpen');
      if (countOpen) countOpen.textContent = openTasks.length;
      const countCompleted = $('#taskCountCompleted');
      if (countCompleted) countCompleted.textContent = completedTasks.length;
      const countDismissed = $('#taskCountDismissed');
      if (countDismissed) countDismissed.textContent = dismissedTasks.length;
      const countAll = $('#taskCountAll');
      if (countAll) countAll.textContent = allTasks.length;

      // Update stat cards on dashboard
      const statEl = $('#statOpenTasks');
      if (statEl) statEl.textContent = openTasks.length;
      const statCompleted = $('#statCompletedTasks');
      if (statCompleted) statCompleted.textContent = completedTasks.length;
      const statDismissed = $('#statDismissedTasks');
      if (statDismissed) statDismissed.textContent = dismissedTasks.length;

      // Filter tasks for active tab view
      let visibleTasks = allTasks;
      if (activeStatus && activeStatus !== 'all') {
        visibleTasks = allTasks.filter(t => t.status === activeStatus);
      }

      if (priValue) {
        visibleTasks = visibleTasks.filter(t => (t.priority || '').toLowerCase() === priValue.toLowerCase());
      }

      currentTasks = visibleTasks;
      renderTasks(container, visibleTasks);
      if (statusEl) {
        statusEl.textContent = visibleTasks.length
          ? `${visibleTasks.length} task${visibleTasks.length !== 1 ? 's' : ''}`
          : '';
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
          <p>No tasks found in this view.</p>
        </div>`;
      return;
    }

    container.innerHTML = tasks.map(task => taskCardHTML(task)).join('');

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
        <button class="btn btn--sm btn--primary" data-task-action="complete" data-task-id="${task.id}" title="Mark completed">✓ Complete</button>
        <button class="btn btn--sm btn--ghost" data-task-action="dismiss" data-task-id="${task.id}" title="Dismiss task">✕ Dismiss</button>
        <button class="btn btn--sm btn--ghost" data-task-action="decompose" data-task-id="${task.id}" title="AI Subtask Breakdown">🤖 Break Down</button>
        <button class="btn btn--sm btn--ghost" data-task-action="export" data-task-id="${task.id}" title="Sync Calendar or Issue Bridge">⚡ Actions</button>`;
    } else if (task.status === 'completed') {
      actions = `
        <span class="badge" style="background:var(--color-success, #10b981);color:#fff;margin-right:6px;">✓ Completed</span>
        <button class="btn btn--sm btn--ghost" data-task-action="reopen" data-task-id="${task.id}" title="Reopen task">↩ Reopen</button>
        <button class="btn btn--sm btn--ghost" data-task-action="export" data-task-id="${task.id}" title="Sync Calendar or Issue Bridge">⚡ Actions</button>`;
    } else if (task.status === 'dismissed') {
      actions = `
        <span class="badge" style="background:var(--text-muted);color:#fff;margin-right:6px;">✕ Dismissed</span>
        <button class="btn btn--sm btn--ghost" data-task-action="reopen" data-task-id="${task.id}" title="Reopen task">↩ Reopen</button>
        <button class="btn btn--sm btn--ghost" data-task-action="export" data-task-id="${task.id}" title="Sync Calendar or Issue Bridge">⚡ Actions</button>`;
    } else {
      actions = `
        <button class="btn btn--sm btn--ghost" data-task-action="reopen" data-task-id="${task.id}">Reopen</button>
        <button class="btn btn--sm btn--ghost" data-task-action="export" data-task-id="${task.id}">⚡ Actions</button>`;
    }

    return `
      <div class="task-card task-card--${statusClass}" data-task-id="${task.id}">
        <div class="task-card__body">
          <div class="task-card__header">
            <span class="task-card__text" style="${task.status === 'completed' ? 'text-decoration:line-through;opacity:0.75;' : ''}">${esc(task.text)}</span>
            ${task.priority ? `<span class="badge badge--pri badge--pri--${priClass}">${esc(task.priority)}</span>` : ''}
          </div>
          <div class="task-card__meta">
            ${task.timing_text ? `<span class="task-card__timing">🕒 ${esc(task.timing_text)}</span>` : ''}
            <span class="task-card__status badge badge--status--${statusClass}">${esc(task.status)}</span>
            <span class="task-card__time">${relativeTime(task.created_at)}</span>
          </div>
          ${task.source_item_ids && task.source_item_ids.length ? `<div class="task-card__sources">Sources: ${task.source_item_ids.map(id => `<code>#${esc(String(id))}</code>`).join(', ')}</div>` : ''}
        </div>
        <div class="task-card__actions">${actions}</div>
      </div>`;
  }

  async function handleTaskAction(action, taskId) {
    if (action === 'decompose') {
      openBreakdownModal(taskId);
      return;
    }
    if (action === 'export') {
      openTaskExportModal(taskId);
      return;
    }

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
      refreshDashboard();
    } catch (err) {
      showToast(err.message, 'error');
      setButtonLoading(btn, false);
    }
  }

  // --------------------------------------------------------------------------
  // AI Note Enhancement Modal
  // --------------------------------------------------------------------------

  async function openEnhanceModal(itemId) {
    const modal = $('#enhanceModal');
    const content = $('#enhanceContent');
    const closeBtn = $('#closeEnhanceBtn');
    const doneBtn = $('#doneEnhanceBtn');
    const copyBtn = $('#copyEnhanceBtn');
    if (!modal || !content) return;

    modal.style.display = 'flex';
    content.innerHTML = `
      <div style="text-align:center;padding:32px 16px;">
        <span class="spinner spinner--lg"></span>
        <p style="margin-top:12px;color:var(--text-secondary);font-size:0.9rem;">Generating AI insights, action plan & identifying related notes…</p>
      </div>`;

    const closeModal = () => { modal.style.display = 'none'; };
    if (closeBtn) closeBtn.onclick = closeModal;
    if (doneBtn) doneBtn.onclick = closeModal;

    try {
      const [enhancement, related] = await Promise.all([
        api(`/api/items/${itemId}/enhance`, { method: 'POST' }),
        api(`/api/items/${itemId}/related`, { method: 'GET' }).catch(() => ({ related_items: [] })),
      ]);

      let html = '';
      html += `<div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap;">`;
      if (enhancement.category) {
        html += `<span class="badge badge--type" style="font-weight:600;">${esc(enhancement.category)}</span>`;
      }
      if (enhancement.suggested_priority) {
        const pClass = enhancement.suggested_priority.toLowerCase();
        html += `<span class="badge badge--pri badge--pri--${pClass}">Priority: ${esc(enhancement.suggested_priority)}</span>`;
      }
      html += `</div>`;

      html += `<div style="background:var(--bg-primary);padding:14px;border-radius:var(--radius-md);border:1px solid var(--border);margin-bottom:14px;">
        <div style="font-size:0.8rem;text-transform:uppercase;letter-spacing:0.05em;color:var(--text-muted);font-weight:600;margin-bottom:4px;">Executive TL;DR</div>
        <div style="font-size:0.95rem;font-weight:500;">${esc(enhancement.tldr)}</div>
      </div>`;

      if (enhancement.key_takeaways && enhancement.key_takeaways.length) {
        html += `<div style="margin-bottom:14px;">
          <div style="font-size:0.85rem;font-weight:600;color:var(--text-secondary);margin-bottom:6px;">📌 Key Takeaways</div>
          <ul style="padding-left:18px;margin:0;font-size:0.88rem;line-height:1.5;">
            ${enhancement.key_takeaways.map(t => `<li>${esc(t)}</li>`).join('')}
          </ul>
        </div>`;
      }

      if (enhancement.action_items && enhancement.action_items.length) {
        html += `<div style="margin-bottom:14px;">
          <div style="font-size:0.85rem;font-weight:600;color:var(--text-secondary);margin-bottom:6px;">🎯 Action Items</div>
          <div style="display:flex;flex-direction:column;gap:6px;">
            ${enhancement.action_items.map(a => `
              <div style="display:flex;justify-content:space-between;align-items:center;background:var(--bg-subtle, #f8fafc);padding:6px 12px;border-radius:var(--radius-sm);border:1px solid var(--border);font-size:0.85rem;">
                <span><strong>${esc(a.task)}</strong>${a.due_date ? ` <span style="color:var(--text-muted);font-size:0.8rem;">(Due: ${esc(a.due_date)})</span>` : ''}</span>
                <span class="badge badge--pri badge--pri--${(a.priority || 'medium').toLowerCase()}">${esc(a.priority || 'Medium')}</span>
              </div>
            `).join('')}
          </div>
        </div>`;
      }

      if (enhancement.risks_or_blockers && enhancement.risks_or_blockers.length) {
        html += `<div style="margin-bottom:14px;background:#fff1f2;padding:10px 14px;border-radius:var(--radius-sm);border:1px solid #fecdd3;color:#9f1239;">
          <div style="font-size:0.85rem;font-weight:600;margin-bottom:4px;">⚠️ Risks & Blockers</div>
          <ul style="padding-left:18px;margin:0;font-size:0.85rem;line-height:1.4;">
            ${enhancement.risks_or_blockers.map(r => `<li>${esc(r)}</li>`).join('')}
          </ul>
        </div>`;
      }

      if (related && related.related_items && related.related_items.length) {
        html += `<div>
          <div style="font-size:0.85rem;font-weight:600;color:var(--text-secondary);margin-bottom:6px;">🔗 Related Inbox Notes</div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;">
            ${related.related_items.map(r => `
              <button type="button" class="btn btn-sm btn-ghost related-note-pill" data-related-id="${r.id}" title="${esc(r.snippet)}" style="padding:4px 8px;font-size:0.8rem;border:1px solid var(--border);border-radius:var(--radius-full);">
                #${r.id}: ${esc((r.snippet || '').slice(0, 30))}…
              </button>
            `).join('')}
          </div>
        </div>`;
      }

      content.innerHTML = html;

      content.querySelectorAll('.related-note-pill').forEach(pill => {
        pill.addEventListener('click', () => {
          modal.style.display = 'none';
          const searchInput = $('#itemSearch');
          if (searchInput) searchInput.value = pill.dataset.relatedId;
          navigateTo('inbox');
          syncFiltersToUrl();
          loadNotes();
        });
      });

      if (copyBtn) {
        copyBtn.onclick = () => {
          const lines = [
            `# AI Action Plan: Note #${itemId}`,
            `**TL;DR**: ${enhancement.tldr}`,
            '',
            '## Key Takeaways',
            ...enhancement.key_takeaways.map(t => `- ${t}`),
            '',
            '## Action Items',
            ...enhancement.action_items.map(a => `- [ ] **${a.task}** (${a.priority}${a.due_date ? ` · Due: ${a.due_date}` : ''})`),
          ];
          if (enhancement.risks_or_blockers && enhancement.risks_or_blockers.length) {
            lines.push('', '## Risks & Blockers', ...enhancement.risks_or_blockers.map(r => `- ${r}`));
          }
          navigator.clipboard.writeText(lines.join('\n')).then(() => {
            showToast('Action plan copied to clipboard!', 'success');
          });
        };
      }
    } catch (err) {
      content.innerHTML = `<p class="empty-state">Failed to enhance note: ${esc(err.message)}</p>`;
    }
  }

  // --------------------------------------------------------------------------
  // AI Task Breakdown Modal
  // --------------------------------------------------------------------------

  let activeDecomposition = null;

  async function openBreakdownModal(taskId) {
    const modal = $('#breakdownModal');
    const titleEl = $('#breakdownParentTitle');
    const listEl = $('#breakdownSubtasksList');
    const applyBtn = $('#applyBreakdownBtn');
    const closeBtn = $('#closeBreakdownBtn');
    const cancelBtn = $('#cancelBreakdownBtn');
    if (!modal || !listEl) return;

    modal.style.display = 'flex';
    if (titleEl) titleEl.textContent = `Analyzing task #${taskId}…`;
    listEl.innerHTML = `
      <div style="text-align:center;padding:28px 16px;">
        <span class="spinner spinner--lg"></span>
        <p style="margin-top:12px;color:var(--text-secondary);font-size:0.9rem;">Decomposing task into actionable subtasks with AI…</p>
      </div>`;

    const closeModal = () => { modal.style.display = 'none'; activeDecomposition = null; };
    if (closeBtn) closeBtn.onclick = closeModal;
    if (cancelBtn) cancelBtn.onclick = closeModal;

    try {
      const data = await api(`/api/tasks/${taskId}/decompose`, { method: 'POST' });
      activeDecomposition = data;

      if (titleEl) {
        titleEl.textContent = `Original: "${data.parent_task_text}"`;
      }

      if (!data.subtasks || !data.subtasks.length) {
        listEl.innerHTML = `<p class="empty-state">No subtasks generated for this task.</p>`;
        return;
      }

      listEl.innerHTML = `
        <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:10px;">Select subtasks to convert into real inbox tasks:</p>
        <div style="display:flex;flex-direction:column;gap:8px;">
          ${data.subtasks.map((st, i) => `
            <label style="display:flex;align-items:flex-start;gap:10px;padding:10px 12px;background:var(--bg-subtle, #f8fafc);border:1px solid var(--border);border-radius:var(--radius-md);cursor:pointer;">
              <input type="checkbox" class="subtask-checkbox" data-idx="${i}" checked style="margin-top:3px;">
              <div style="flex:1;">
                <div style="font-size:0.9rem;font-weight:600;color:var(--text-primary);">${esc(st.title)}</div>
                <div style="display:flex;gap:6px;align-items:center;margin-top:4px;flex-wrap:wrap;">
                  <span class="badge badge--pri badge--pri--${(st.priority || 'medium').toLowerCase()}">${esc(st.priority || 'Medium')}</span>
                  ${st.estimated_hours ? `<span style="font-size:0.78rem;color:var(--text-muted);">⏱️ ~${st.estimated_hours} hr</span>` : ''}
                  ${st.timing_text ? `<span style="font-size:0.78rem;color:var(--text-muted);">🕒 ${esc(st.timing_text)}</span>` : ''}
                </div>
              </div>
            </label>
          `).join('')}
        </div>
      `;

      if (applyBtn) {
        applyBtn.onclick = async () => {
          if (!activeDecomposition) return;
          const checkedIndices = Array.from(listEl.querySelectorAll('.subtask-checkbox:checked')).map(cb => parseInt(cb.dataset.idx, 10));
          const selectedSubtasks = activeDecomposition.subtasks.filter((_, i) => checkedIndices.includes(i));
          if (!selectedSubtasks.length) {
            showToast('Please select at least one subtask to apply.', 'error');
            return;
          }

          setButtonLoading(applyBtn, true);
          try {
            const res = await api(`/api/tasks/${taskId}/apply-subtasks`, {
              method: 'POST',
              body: { subtasks: selectedSubtasks },
            });
            showToast(`Added ${res.length} subtasks to your tasks!`, 'success');
            modal.style.display = 'none';
            await loadTasks();
            refreshDashboard();
          } catch (err) {
            showToast(err.message, 'error');
          } finally {
            setButtonLoading(applyBtn, false);
          }
        };
      }
    } catch (err) {
      listEl.innerHTML = `<p class="empty-state">Failed to decompose task: ${esc(err.message)}</p>`;
    }
  }

  // --------------------------------------------------------------------------
  // Dashboard
  // --------------------------------------------------------------------------

  async function refreshDashboard() {
    try {
      const stats = await api('/api/stats');
      const statTotal = $('#statTotalItems');
      if (statTotal) statTotal.textContent = stats.total_items ?? 0;
      const statOpen = $('#statOpenTasks');
      if (statOpen) statOpen.textContent = stats.open_tasks ?? 0;
      const statCompleted = $('#statCompletedTasks');
      if (statCompleted) statCompleted.textContent = stats.completed_tasks ?? 0;
      const statDismissed = $('#statDismissedTasks');
      if (statDismissed) statDismissed.textContent = stats.dismissed_tasks ?? 0;
      const modeEl = $('#statAnalysisMode');
      if (modeEl && stats.analysis_mode) modeEl.textContent = stats.analysis_mode;
      const timeEl = $('#statLastAnalysis');
      if (timeEl && stats.last_analysis_at) timeEl.textContent = relativeTime(stats.last_analysis_at);

      // AI Metrics Telemetry
      if (stats.ai_metrics) {
        const m = stats.ai_metrics;
        const totalCallsEl = $('#metricTotalCalls');
        if (totalCallsEl) totalCallsEl.textContent = m.total_calls;
        const totalTokensEl = $('#metricTotalTokens');
        if (totalTokensEl) totalTokensEl.textContent = (m.total_tokens || 0).toLocaleString();
        const avgLatencyEl = $('#metricAvgLatency');
        if (avgLatencyEl) avgLatencyEl.textContent = `${Math.round(m.avg_latency_ms || 0)} ms`;
        const totalCostEl = $('#metricTotalCost');
        if (totalCostEl) totalCostEl.textContent = `$${(m.total_cost_usd || 0).toFixed(6)}`;

        const badge = $('#telemetryProviderBadge');
        if (badge) {
          badge.textContent = `${m.total_calls} calls · $${(m.total_cost_usd || 0).toFixed(4)}`;
        }
      }

      // Render tags cloud
      const tagsWrapper = $('#dashboard-tags-wrapper');
      const tagsContainer = $('#dashboard-tags');
      if (tagsWrapper && tagsContainer) {
        if (stats.top_tags && stats.top_tags.length) {
          tagsWrapper.style.display = 'block';
          tagsContainer.innerHTML = stats.top_tags.map(t => `
            <button type="button" class="btn btn-sm btn-ghost note-tag-pill" data-tag-search="${esc(t.tag)}" style="padding:4px 8px;font-size:0.8rem;border:1px solid var(--border);border-radius:var(--radius-full);">
              #${esc(t.tag)} <span style="opacity:0.6;font-size:0.75rem;">(${t.count})</span>
            </button>
          `).join('');

          tagsContainer.querySelectorAll('[data-tag-search]').forEach(b => {
            b.addEventListener('click', () => {
              const searchInput = $('#itemSearch');
              if (searchInput) searchInput.value = '#' + b.dataset.tagSearch;
              navigateTo('inbox');
              syncFiltersToUrl();
              loadNotes();
            });
          });
        } else {
          tagsWrapper.style.display = 'none';
        }
      }
    } catch (err) {
      console.warn('Dashboard stats error:', err);
    }
  }

  // --------------------------------------------------------------------------
  // Keyboard shortcuts (global)
  // --------------------------------------------------------------------------

  function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
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

  function initAuthUI() {
    const btn = $('#tokenConfigBtn');
    if (btn) {
      btn.addEventListener('click', () => {
        promptForAuthToken('Configure Life Inbox Access Token (APP_TOKEN):');
      });
    }
  }

  // --------------------------------------------------------------------------
  // Ask Your Inbox & Weekly Digest (Phase 3 AI features)
  // --------------------------------------------------------------------------

  function initAskInbox() {
    const form = $('#askInboxForm');
    const input = $('#askInboxInput');
    const resultBox = $('#askInboxResult');
    const answerEl = $('#askInboxAnswer');
    const citationsList = $('#askInboxCitationsList');
    const btn = $('#askInboxBtn');

    if (!form || !input) return;

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const question = input.value.trim();
      if (!question) return;

      setButtonLoading(btn, true);
      try {
        const data = await api('/api/ask', {
          method: 'POST',
          body: { question, top_k: 5 },
        });

        resultBox.style.display = 'block';
        answerEl.innerHTML = esc(data.answer).replace(/\n/g, '<br>');

        if (data.citations && data.citations.length) {
          citationsList.innerHTML = data.citations.map(c => `
            <button type="button" class="btn btn-sm btn-ghost citation-pill" data-cite-id="${c.id}" title="${esc(c.snippet)}" style="padding:2px 8px;font-size:0.78rem;border:1px solid var(--border);border-radius:var(--radius-full);cursor:pointer;">
              📌 Note #${c.id} (${(c.relevance_score || 0).toFixed(2)})
            </button>
          `).join('');

          citationsList.querySelectorAll('.citation-pill').forEach(pill => {
            pill.addEventListener('click', () => {
              const citeId = pill.dataset.citeId;
              const searchInput = $('#itemSearch');
              if (searchInput) searchInput.value = citeId;
              navigateTo('inbox');
              syncFiltersToUrl();
              loadNotes();
            });
          });
        } else {
          citationsList.innerHTML = '<span style="font-size:0.75rem;color:var(--text-muted);">None cited</span>';
        }
        showToast('Answer synthesized from inbox notes', 'success');
        refreshDashboard();
      } catch (err) {
        showToast(`Failed to query inbox: ${err.message}`, 'error');
      } finally {
        setButtonLoading(btn, false);
      }
    });
  }

  function initWeeklyDigest() {
    const btn = $('#refreshDigestBtn');
    const content = $('#weeklyDigestContent');
    if (!btn || !content) return;

    btn.addEventListener('click', async () => {
      setButtonLoading(btn, true);
      try {
        const digest = await api('/api/digest/weekly');
        let html = `
          <div style="font-size:0.8rem;color:var(--text-muted);margin-bottom:8px;">${esc(digest.period)} · ${digest.total_notes_in_scope} notes evaluated (${digest.latency_ms} ms)</div>
          <div style="font-size:0.92rem;line-height:1.5;margin-bottom:12px;">${esc(digest.executive_summary)}</div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">
            <span class="badge badge--status" style="background:#fef3c7;color:#92400e;">⏳ ${digest.open_tasks_count} Open Tasks</span>
            <span class="badge badge--status" style="background:#fee2e2;color:#991b1b;">⚠️ ${digest.stale_items_count} Stale Notes (&gt;7d)</span>
          </div>
        `;
        if (digest.suggested_focus && digest.suggested_focus.length) {
          html += `<div style="font-size:0.85rem;font-weight:600;margin-bottom:4px;">Actionable Focus Points:</div><ul style="padding-left:18px;font-size:0.85rem;line-height:1.4;">`;
          html += digest.suggested_focus.map(f => `<li>${esc(f)}</li>`).join('');
          html += `</ul>`;
        }
        content.innerHTML = html;
        showToast('Weekly digest generated', 'success');
        refreshDashboard();
      } catch (err) {
        showToast(`Failed to generate digest: ${err.message}`, 'error');
      } finally {
        setButtonLoading(btn, false);
      }
    });
  }

  // --------------------------------------------------------------------------
  // Task External Sync Modal (Google Calendar, iCal, GitHub, Linear)
  // --------------------------------------------------------------------------

  async function openTaskExportModal(taskId) {
    const modal = $('#taskExportModal');
    const titleEl = $('#taskExportTitle');
    const descEl = $('#taskExportDesc');
    const googleCalBtn = $('#taskGoogleCalBtn');
    const icsBtn = $('#taskIcsBtn');
    const githubBtn = $('#taskGithubBtn');
    const linearBtn = $('#taskLinearBtn');
    const closeBtn = $('#closeTaskExportBtn');
    const doneBtn = $('#doneTaskExportBtn');

    if (!modal) return;

    modal.style.display = 'flex';
    const closeModal = () => { modal.style.display = 'none'; };
    if (closeBtn) closeBtn.onclick = closeModal;
    if (doneBtn) doneBtn.onclick = closeModal;

    if (titleEl) titleEl.textContent = `⚡ Sync: Task #${taskId}`;
    if (descEl) descEl.textContent = 'Loading calendar and issue tracking links...';

    try {
      const [cal, links] = await Promise.all([
        api(`/api/tasks/${taskId}/calendar`),
        api(`/api/tasks/${taskId}/external-links`),
      ]);

      if (descEl) descEl.textContent = cal.title || 'Export task to calendar or external project trackers.';

      if (googleCalBtn) {
        googleCalBtn.href = cal.google_calendar_url || '#';
        googleCalBtn.onclick = () => {
          showToast('Opening Google Calendar...', 'info');
        };
      }

      if (icsBtn) {
        icsBtn.href = `/api/tasks/${taskId}/calendar?format=ics`;
        icsBtn.setAttribute('download', `task_${taskId}.ics`);
        icsBtn.onclick = () => {
          showToast('Downloading .ics calendar event...', 'info');
        };
      }

      if (githubBtn) {
        githubBtn.href = links.github_issue_url || '#';
      }

      if (linearBtn) {
        linearBtn.href = links.linear_issue_url || '#';
      }
    } catch (err) {
      if (descEl) descEl.textContent = `Failed to load links: ${err.message}`;
      showToast(err.message, 'error');
    }
  }

  // --------------------------------------------------------------------------
  // Executive Daily Morning Briefing
  // --------------------------------------------------------------------------

  let cachedBriefing = null;

  async function loadBriefing() {
    const card = $('#executiveBriefingCard');
    if (!card) return;
    try {
      const b = await api('/api/briefing/today');
      cachedBriefing = b;
      const greetingEl = $('#briefingGreeting');
      if (greetingEl) greetingEl.textContent = b.greeting || 'Good day, Chief';

      const dateEl = $('#briefingDate');
      if (dateEl) {
        const pCount = (b.actionable_priorities || []).length;
        dateEl.textContent = `${b.date || 'Today'} · ${pCount} priority focus item${pCount !== 1 ? 's' : ''}`;
      }

      const scoreEl = $('#briefingHealthScore');
      if (scoreEl) scoreEl.textContent = `Inbox ${b.inbox_health_score || 95}% Healthy`;

      const summaryEl = $('#briefingSummaryText');
      if (summaryEl) summaryEl.textContent = b.executive_summary || '';

      const recList = $('#briefingRecommendationsList');
      if (recList && b.top_recommendations && b.top_recommendations.length) {
        recList.innerHTML = b.top_recommendations.map(r => `
          <div style="font-size:0.85rem;color:var(--text-secondary);display:flex;align-items:flex-start;gap:6px;">
            <span style="color:var(--accent);">⚡</span>
            <span>${esc(r)}</span>
          </div>
        `).join('');
      } else if (recList) {
        recList.innerHTML = '';
      }
    } catch (err) {
      console.warn('Failed to load briefing:', err);
    }
  }

  function initBriefing() {
    const refreshBtn = $('#refreshBriefingBtn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', async () => {
        setButtonLoading(refreshBtn, true);
        await loadBriefing();
        setButtonLoading(refreshBtn, false);
        showToast('Executive standup briefing refreshed!', 'success');
      });
    }

    const openMatrixBtn = $('#briefingOpenMatrixBtn');
    if (openMatrixBtn) {
      openMatrixBtn.addEventListener('click', () => {
        navigateTo('tasks');
        switchToMatrixView();
      });
    }

    const syncCalBtn = $('#briefingSyncCalendarBtn');
    if (syncCalBtn) {
      syncCalBtn.addEventListener('click', async () => {
        if (!cachedBriefing || !cachedBriefing.actionable_priorities || !cachedBriefing.actionable_priorities.length) {
          showToast('No priorities available to sync to calendar.', 'info');
          return;
        }
        const topItem = cachedBriefing.actionable_priorities[0];
        try {
          const calData = await api(`/api/tasks/${topItem.id}/calendar`);
          if (calData && calData.google_calendar_url) {
            window.open(calData.google_calendar_url, '_blank');
            showToast('Opening Google Calendar for top focus priority!', 'success');
          }
        } catch (err) {
          showToast(`Calendar sync error: ${err.message}`, 'error');
        }
      });
    }

    const shareSlackBtn = $('#briefingShareSlackBtn');
    if (shareSlackBtn) {
      shareSlackBtn.addEventListener('click', async () => {
        const storedUrl = localStorage.getItem('life_inbox_slack_webhook');
        if (!storedUrl) {
          navigateTo('integrations');
          showToast('Please configure a Slack/Discord webhook URL first.', 'info');
          const input = $('#slackWebhookInput');
          if (input) input.focus();
          return;
        }
        if (!cachedBriefing) await loadBriefing();
        setButtonLoading(shareSlackBtn, true);
        try {
          await api('/api/integrations/dispatch', {
            method: 'POST',
            body: {
              webhook_url: storedUrl,
              target_type: 'slack',
              text: `*${cachedBriefing.greeting}* - Daily Executive Briefing\n${cachedBriefing.executive_summary}`
            }
          });
          showToast('Dispatched morning briefing to your channel!', 'success');
        } catch (err) {
          showToast(`Dispatch failed: ${err.message}`, 'error');
        } finally {
          setButtonLoading(shareSlackBtn, false);
        }
      });
    }
  }

  // --------------------------------------------------------------------------
  // Live Voice Recorder
  // --------------------------------------------------------------------------

  let mediaRecorder = null;
  let audioChunks = [];
  let recordTimerInterval = null;
  let recordingSeconds = 0;

  function initVoiceRecorder() {
    const recordBtn = $('#recordVoiceBtn');
    const recordingBar = $('#voiceRecordingBar');
    const timerEl = $('#recordingTimer');
    const stopBtn = $('#stopVoiceBtn');
    const cancelBtn = $('#cancelVoiceBtn');

    if (!recordBtn || !recordingBar) return;

    recordBtn.addEventListener('click', async () => {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        showToast('Audio recording is not supported in this browser.', 'error');
        return;
      }

      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioChunks = [];
        mediaRecorder = new MediaRecorder(stream);

        mediaRecorder.ondataavailable = (e) => {
          if (e.data && e.data.size > 0) audioChunks.push(e.data);
        };

        mediaRecorder.start(250);
        recordingSeconds = 0;
        if (timerEl) timerEl.textContent = '00:00';
        recordTimerInterval = setInterval(() => {
          recordingSeconds++;
          const mins = String(Math.floor(recordingSeconds / 60)).padStart(2, '0');
          const secs = String(recordingSeconds % 60).padStart(2, '0');
          if (timerEl) timerEl.textContent = `${mins}:${secs}`;
        }, 1000);

        recordingBar.style.display = 'flex';
        recordBtn.style.display = 'none';
        showToast('Listening... Speak your thought or tasks.', 'info');
      } catch (err) {
        showToast(`Microphone access error: ${err.message}`, 'error');
      }
    });

    const cleanupRecorder = () => {
      if (recordTimerInterval) clearInterval(recordTimerInterval);
      recordTimerInterval = null;
      if (mediaRecorder && mediaRecorder.stream) {
        mediaRecorder.stream.getTracks().forEach(t => t.stop());
      }
      mediaRecorder = null;
      recordingBar.style.display = 'none';
      recordBtn.style.display = 'inline-flex';
    };

    if (cancelBtn) {
      cancelBtn.addEventListener('click', () => {
        cleanupRecorder();
        audioChunks = [];
        showToast('Voice recording cancelled.', 'info');
      });
    }

    if (stopBtn) {
      stopBtn.addEventListener('click', () => {
        if (!mediaRecorder) return;
        setButtonLoading(stopBtn, true);

        mediaRecorder.onstop = async () => {
          try {
            const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
            const formData = new FormData();
            formData.append('file', audioBlob, 'voice_memo.webm');

            const token = getStoredAuthToken();
            const headers = {};
            if (token) {
              headers['Authorization'] = `Bearer ${token}`;
              headers['X-App-Token'] = token;
            }

            showToast('Processing & transcribing voice memo with AI...', 'info');
            const res = await fetch('/api/upload?auto_process=true', {
              method: 'POST',
              headers,
              body: formData,
            });

            if (!res.ok) {
              const err = await res.json().catch(() => ({}));
              throw new Error(err.detail || 'Voice upload failed');
            }

            const data = await res.json();
            const taskCount = data.auto_analysis && data.auto_analysis.extracted_tasks ? data.auto_analysis.extracted_tasks.length : 0;
            showToast(`Voice memo transcribed! Extracted ${taskCount} task${taskCount !== 1 ? 's' : ''}`, 'success');

            await loadNotes();
            await loadTasks();
            refreshDashboard();
            loadBriefing();
          } catch (err) {
            showToast(err.message, 'error');
          } finally {
            setButtonLoading(stopBtn, false);
            cleanupRecorder();
          }
        };

        mediaRecorder.stop();
      });
    }
  }

  // --------------------------------------------------------------------------
  // Eisenhower 4-Quadrant Focus Matrix
  // --------------------------------------------------------------------------

  function switchToMatrixView() {
    const listBtn = $('#taskViewListBtn');
    const matrixBtn = $('#taskViewMatrixBtn');
    const listView = $('#tasksListView');
    const matrixView = $('#tasksMatrixView');

    if (listBtn) {
      listBtn.classList.remove('btn-primary');
      listBtn.classList.add('btn-ghost');
    }
    if (matrixBtn) {
      matrixBtn.classList.add('btn-primary');
      matrixBtn.classList.remove('btn-ghost');
    }
    if (listView) listView.style.display = 'none';
    if (matrixView) matrixView.style.display = 'block';
    loadEisenhowerMatrix();
  }

  function switchToListView() {
    const listBtn = $('#taskViewListBtn');
    const matrixBtn = $('#taskViewMatrixBtn');
    const listView = $('#tasksListView');
    const matrixView = $('#tasksMatrixView');

    if (matrixBtn) {
      matrixBtn.classList.remove('btn-primary');
      matrixBtn.classList.add('btn-ghost');
    }
    if (listBtn) {
      listBtn.classList.add('btn-primary');
      listBtn.classList.remove('btn-ghost');
    }
    if (matrixView) matrixView.style.display = 'none';
    if (listView) listView.style.display = 'block';
    loadTasks();
  }

  async function loadEisenhowerMatrix() {
    try {
      const data = await api('/api/tasks/matrix');
      const q = data.quadrants;

      const renderQuadrant = (containerId, countId, tasks) => {
        const container = $(`#${containerId}`);
        const count = $(`#${countId}`);
        if (count) count.textContent = tasks.length;
        if (!container) return;
        if (!tasks.length) {
          container.innerHTML = '<div style="font-size:0.8rem;color:var(--text-muted);font-style:italic;padding:8px 0;">No tasks in this quadrant</div>';
          return;
        }
        container.innerHTML = tasks.map(t => `
          <div class="matrix-task-item" style="display:flex;align-items:center;justify-content:space-between;padding:8px 10px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:var(--radius-sm);margin-bottom:6px;gap:8px;">
            <div style="flex:1;min-width:0;">
              <div style="font-size:0.85rem;font-weight:500;color:var(--text-primary);word-break:break-word;">${esc(t.text)}</div>
              ${t.timing_text ? `<div style="font-size:0.75rem;color:var(--text-muted);">🕒 ${esc(t.timing_text)}</div>` : ''}
            </div>
            <div style="display:flex;gap:4px;flex-shrink:0;">
              <button class="btn btn-sm btn-ghost" data-matrix-action="complete" data-task-id="${t.id}" title="Complete" style="padding:2px 6px;font-size:0.75rem;">✓</button>
              <button class="btn btn-sm btn-ghost" data-matrix-action="export" data-task-id="${t.id}" title="Actions" style="padding:2px 6px;font-size:0.75rem;">⚡</button>
            </div>
          </div>
        `).join('');

        container.querySelectorAll('[data-matrix-action]').forEach(btn => {
          btn.addEventListener('click', async () => {
            const act = btn.dataset.matrixAction;
            const tid = btn.dataset.taskId;
            if (act === 'complete') {
              await api(`/api/tasks/${tid}/complete`, { method: 'POST' });
              showToast('Task marked complete!', 'success');
              loadEisenhowerMatrix();
              refreshDashboard();
            } else if (act === 'export') {
              openTaskExportModal(tid);
            }
          });
        });
      };

      renderQuadrant('matrixQ1', 'countQ1', q.q1_do_first || []);
      renderQuadrant('matrixQ2', 'countQ2', q.q2_schedule || []);
      renderQuadrant('matrixQ3', 'countQ3', q.q3_delegate || []);
      renderQuadrant('matrixQ4', 'countQ4', q.q4_someday || []);
    } catch (err) {
      showToast(`Matrix loading failed: ${err.message}`, 'error');
    }
  }

  function initEisenhowerMatrix() {
    const listBtn = $('#taskViewListBtn');
    const matrixBtn = $('#taskViewMatrixBtn');
    if (listBtn) listBtn.addEventListener('click', switchToListView);
    if (matrixBtn) matrixBtn.addEventListener('click', switchToMatrixView);

    const dispatchBtn = $('#taskDispatchAllBtn');
    if (dispatchBtn) {
      dispatchBtn.addEventListener('click', async () => {
        const storedUrl = localStorage.getItem('life_inbox_slack_webhook');
        if (!storedUrl) {
          navigateTo('integrations');
          showToast('Configure a Slack/Discord webhook URL to dispatch tasks.', 'info');
          return;
        }
        setButtonLoading(dispatchBtn, true);
        try {
          const matrix = await api('/api/tasks/matrix');
          const q1 = (matrix.quadrants.q1_do_first || []).map(t => `• 🔥 ${t.text}`).join('\n');
          const q2 = (matrix.quadrants.q2_schedule || []).map(t => `• 📅 ${t.text}`).join('\n');
          const msg = `*Life Inbox Focus Matrix Priorities*\n*Do First:*\n${q1 || 'None'}\n\n*Schedule:*\n${q2 || 'None'}`;
          await api('/api/integrations/dispatch', {
            method: 'POST',
            body: { webhook_url: storedUrl, target_type: 'slack', text: msg }
          });
          showToast('Focus matrix dispatched to channel!', 'success');
        } catch (err) {
          showToast(`Dispatch failed: ${err.message}`, 'error');
        } finally {
          setButtonLoading(dispatchBtn, false);
        }
      });
    }
  }

  // --------------------------------------------------------------------------
  // Universal Command Palette (Ctrl+K / Cmd+K)
  // --------------------------------------------------------------------------

  function initCommandPalette() {
    const modal = $('#cmdPaletteModal');
    const input = $('#cmdPaletteInput');
    const list = $('#cmdResultsList');
    const openBtn = $('#cmdPaletteBtn');

    if (!modal || !input || !list) return;

    let selectedIndex = 0;
    let currentResults = [];

    const defaultCommands = [
      { type: 'action', title: 'Create New Note', desc: 'Jump to capture textarea', icon: '📝', handler: () => { navigateTo('inbox'); $('#noteText')?.focus(); } },
      { type: 'action', title: 'Record Voice Memo', desc: 'Capture spoken thought via mic', icon: '🎙️', handler: () => { navigateTo('inbox'); $('#recordVoiceBtn')?.click(); } },
      { type: 'action', title: 'Open Eisenhower Focus Matrix', desc: 'View 4-quadrant triage', icon: '🎯', handler: () => { navigateTo('tasks'); switchToMatrixView(); } },
      { type: 'action', title: 'View Integrations & Webhooks', desc: 'Apple Shortcuts, Slack, Calendar', icon: '🔗', handler: () => { navigateTo('integrations'); } },
      { type: 'action', title: 'Batch Import Notes', desc: 'Paste multiple notes with ---', icon: '📥', handler: () => { $('#batchImportBtn')?.click(); } },
      { type: 'action', title: 'Run Weekly AI Digest', desc: 'Generate executive summary', icon: '✨', handler: () => { navigateTo('analysis'); $('#refreshDigestBtn')?.click(); } },
      { type: 'nav', title: 'Go to Dashboard', desc: 'Executive overview & standup', icon: '📊', handler: () => navigateTo('dashboard') },
      { type: 'nav', title: 'Go to All Notes', desc: 'Search and filter captured items', icon: '📄', handler: () => navigateTo('inbox') },
      { type: 'nav', title: 'Go to Tasks', desc: 'Manage open & completed tasks', icon: '✅', handler: () => { navigateTo('tasks'); switchToListView(); } },
    ];

    const openPalette = () => {
      modal.style.display = 'flex';
      input.value = '';
      selectedIndex = 0;
      renderCommands(defaultCommands);
      setTimeout(() => input.focus(), 50);
    };

    const closePalette = () => {
      modal.style.display = 'none';
      input.value = '';
    };

    modal.addEventListener('click', (e) => {
      if (e.target === modal) closePalette();
    });

    if (openBtn) openBtn.addEventListener('click', openPalette);

    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        if (modal.style.display === 'flex') closePalette();
        else openPalette();
      } else if (e.key === 'Escape' && modal.style.display === 'flex') {
        e.preventDefault();
        closePalette();
      }
    });

    function renderCommands(items) {
      currentResults = items;
      selectedIndex = 0;
      if (!items.length) {
        list.innerHTML = `<div style="padding:16px;text-align:center;color:var(--text-muted);font-size:0.88rem;">No matching commands, notes, or tasks found.</div>`;
        return;
      }
      list.innerHTML = items.map((cmd, idx) => `
        <div class="cmd-item ${idx === 0 ? 'selected' : ''}" data-cmd-idx="${idx}">
          <div class="cmd-item-left">
            <span style="font-size:1.1rem;">${cmd.icon}</span>
            <div>
              <div style="font-weight:500;">${esc(cmd.title)}</div>
              ${cmd.desc ? `<div style="font-size:0.75rem;color:var(--text-muted);">${esc(cmd.desc)}</div>` : ''}
            </div>
          </div>
          <span class="cmd-shortcut">${cmd.type === 'nav' ? 'Navigate' : 'Action'}</span>
        </div>
      `).join('');

      list.querySelectorAll('.cmd-item').forEach(el => {
        el.addEventListener('click', () => {
          const idx = parseInt(el.dataset.cmdIdx, 10);
          if (currentResults[idx]) {
            closePalette();
            currentResults[idx].handler();
          }
        });
      });
    }

    input.addEventListener('input', () => {
      const q = input.value.trim().toLowerCase();
      if (!q) {
        renderCommands(defaultCommands);
        return;
      }

      const matchingDefaults = defaultCommands.filter(c =>
        c.title.toLowerCase().includes(q) || (c.desc && c.desc.toLowerCase().includes(q))
      );

      const matchingNotes = (currentLoadedItems || [])
        .filter(n => (n.raw_text || '').toLowerCase().includes(q))
        .slice(0, 4)
        .map(n => ({
          type: 'note',
          title: n.raw_text.slice(0, 48) + (n.raw_text.length > 48 ? '...' : ''),
          desc: `Note #${n.id} · ${n.item_type || 'Note'}`,
          icon: '📄',
          handler: () => {
            const searchInput = $('#itemSearch');
            if (searchInput) searchInput.value = n.id;
            navigateTo('inbox');
            syncFiltersToUrl();
            loadNotes();
          }
        }));

      const allTasksList = window._allTasks || currentTasks || [];
      const matchingTasks = allTasksList
        .filter(t => (t.text || '').toLowerCase().includes(q))
        .slice(0, 4)
        .map(t => ({
          type: 'task',
          title: t.text,
          desc: `Task #${t.id} · ${t.priority || 'Normal'} (${t.status})`,
          icon: '⚡',
          handler: () => {
            navigateTo('tasks');
            loadTasks();
          }
        }));

      renderCommands([...matchingDefaults, ...matchingTasks, ...matchingNotes]);
    });

    input.addEventListener('keydown', (e) => {
      const items = list.querySelectorAll('.cmd-item');
      if (!items.length) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        selectedIndex = (selectedIndex + 1) % items.length;
        updateSelection(items);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        selectedIndex = (selectedIndex - 1 + items.length) % items.length;
        updateSelection(items);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (currentResults[selectedIndex]) {
          closePalette();
          currentResults[selectedIndex].handler();
        }
      }
    });

    function updateSelection(items) {
      items.forEach((it, i) => it.classList.toggle('selected', i === selectedIndex));
      if (items[selectedIndex]) items[selectedIndex].scrollIntoView({ block: 'nearest' });
    }
  }

  // --------------------------------------------------------------------------
  // Integrations Hub
  // --------------------------------------------------------------------------

  function initIntegrationsHub() {
    const origin = window.location.origin;
    const webhookUrl = `${origin}/api/webhooks/inbound`;

    const displayEl = $('#inboundWebhookUrlDisplay');
    if (displayEl) displayEl.textContent = webhookUrl;

    const copyCurlBtn = $('#copyWebhookCurlBtn');
    if (copyCurlBtn) {
      copyCurlBtn.onclick = () => {
        const curlSnippet = `curl -X POST "${webhookUrl}" \\\n  -H "Content-Type: application/json" \\\n  -H "X-Webhook-Secret: default_secret" \\\n  -d '{"text": "Call investor at 3pm #urgent", "source": "ios_shortcut", "auto_process": true}'`;
        navigator.clipboard.writeText(curlSnippet).then(() => {
          showToast('Copied cURL snippet to clipboard!', 'success');
        });
      };
    }

    const testPingBtn = $('#testInboundWebhookBtn');
    if (testPingBtn) {
      testPingBtn.onclick = async () => {
        setButtonLoading(testPingBtn, true);
        try {
          const res = await api('/api/webhooks/inbound', {
            method: 'POST',
            body: {
              text: 'Review quarterly architecture roadmap with team tomorrow at 10am #urgent #tech',
              source: 'shortcuts_simulator',
              auto_process: true,
            }
          });
          showToast(`Inbound ping verified! Created note #${res.item_id} with ${res.tasks_created} tasks extracted.`, 'success');
          await loadNotes();
          await loadTasks();
          refreshDashboard();
        } catch (err) {
          showToast(`Inbound webhook error: ${err.message}`, 'error');
        } finally {
          setButtonLoading(testPingBtn, false);
        }
      };
    }

    const slackInput = $('#slackWebhookInput');
    const savePrefBtn = $('#saveWebhookPrefBtn');
    if (slackInput) {
      slackInput.value = localStorage.getItem('life_inbox_slack_webhook') || '';
    }
    if (savePrefBtn && slackInput) {
      savePrefBtn.onclick = () => {
        const val = slackInput.value.trim();
        if (val) {
          localStorage.setItem('life_inbox_slack_webhook', val);
          showToast('Webhook URL saved in browser storage.', 'success');
        } else {
          localStorage.removeItem('life_inbox_slack_webhook');
          showToast('Webhook URL cleared.', 'info');
        }
      };
    }

    const sendBriefingBtn = $('#sendBriefingWebhookBtn');
    if (sendBriefingBtn && slackInput) {
      sendBriefingBtn.onclick = async () => {
        const val = slackInput.value.trim() || localStorage.getItem('life_inbox_slack_webhook');
        if (!val) {
          showToast('Please enter an incoming webhook URL first.', 'error');
          slackInput.focus();
          return;
        }
        setButtonLoading(sendBriefingBtn, true);
        try {
          const briefing = cachedBriefing || await api('/api/briefing/today');
          await api('/api/integrations/dispatch', {
            method: 'POST',
            body: {
              webhook_url: val,
              target_type: 'slack',
              text: `*${briefing.greeting}* - Daily Executive Standup Briefing\n${briefing.executive_summary}`
            }
          });
          showToast('Daily briefing dispatched successfully!', 'success');
        } catch (err) {
          showToast(`Dispatch failed: ${err.message}`, 'error');
        } finally {
          setButtonLoading(sendBriefingBtn, false);
        }
      };
    }
  }

  function init() {
    initTheme();
    initAuthUI();
    initNavigation();
    initNotes();
    initVoiceRecorder();
    initAnalysis();
    initTasks();
    initEisenhowerMatrix();
    initBriefing();
    initCommandPalette();
    initIntegrationsHub();
    initAskInbox();
    initWeeklyDigest();
    initKeyboardShortcuts();
    syncFiltersFromUrl();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
