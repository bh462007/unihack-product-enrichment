(function () {
  'use strict';

  const PAGINATION_THRESHOLD = 200;
  const PAGE_SIZE = 50;
  const DEBOUNCE_MS = 250;
  const COUNT_UP_MS = 800;
  const STAGGER_MS = 40;
  const ROW_ENTER_MS = 200;
  const SKELETON_MS = 380;
  const TOAST_MS = 3000;

  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const tabLinks = document.querySelectorAll('.tab-link');
  const tabPanels = document.querySelectorAll('.tab-panel');
  const tabNavInner = document.querySelector('.tab-nav-inner');
  const tabIndicator = document.querySelector('.tab-indicator');
  const searchInput = document.getElementById('searchInput');
  const categoryFilter = document.getElementById('categoryFilter');
  const confidenceFilter = document.getElementById('confidenceFilter');
  const catalogList = document.getElementById('catalogList');
  const catalogSkeleton = document.getElementById('catalogSkeleton');
  const catalogEmpty = document.getElementById('catalogEmpty');
  const filterStatus = document.getElementById('filterStatus');
  const pagination = document.getElementById('pagination');
  const pagePrev = document.getElementById('pagePrev');
  const pageNext = document.getElementById('pageNext');
  const pageInfo = document.getElementById('pageInfo');
  const exportBtn = document.getElementById('exportBtn');
  const toastHost = document.getElementById('toastHost');

  const totalRecords = catalogList ? parseInt(catalogList.dataset.total, 10) || 0 : 0;
  const paginationEnabled = totalRecords > PAGINATION_THRESHOLD;
  let currentPage = 1;
  let visibleRecords = [];
  let searchDebounce = null;
  let catalogLoaded = false;
  let overviewAnimated = false;
  let traceTimers = [];

  /* ---- Motion helpers ---- */

  function easeOut(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  function animateCountUp(el) {
    if (el.dataset.counted === 'true') return;

    const target = parseFloat(el.dataset.value);
    if (isNaN(target)) return;

    const decimals = parseInt(el.dataset.decimals || '0', 10);
    const suffix = el.dataset.suffix || '';
    const duration = prefersReducedMotion ? 0 : COUNT_UP_MS;
    const start = performance.now();

    function frame(now) {
      const t = duration === 0 ? 1 : Math.min((now - start) / duration, 1);
      const val = target * easeOut(t);
      el.textContent = val.toFixed(decimals) + suffix;
      if (t < 1) {
        requestAnimationFrame(frame);
      } else {
        el.dataset.counted = 'true';
      }
    }

    requestAnimationFrame(frame);
  }

  function runCountUps(root) {
    (root || document).querySelectorAll('.count-up').forEach(animateCountUp);
  }

  function animateBars(root) {
    (root || document).querySelectorAll('.bar-animate, .bar-animate-h, .seg-pass, .seg-flag').forEach(function (bar) {
      const w = parseFloat(bar.dataset.width);
      if (isNaN(w)) return;
      bar.style.setProperty('--bar-w', String(w));
      bar.classList.remove('bar-animated');
      void bar.offsetWidth;
      if (prefersReducedMotion) {
        bar.classList.add('bar-animated');
        if (bar.classList.contains('seg-pass') || bar.classList.contains('seg-flag')) {
          bar.style.width = w + '%';
        }
      } else {
        requestAnimationFrame(function () {
          bar.classList.add('bar-animated');
          if (bar.classList.contains('seg-pass') || bar.classList.contains('seg-flag')) {
            bar.style.width = w + '%';
          }
        });
      }
    });
  }

  function staggerRowEntrance(rows) {
    if (!rows.length) return;

    if (prefersReducedMotion) {
      rows.forEach(function (row) { row.classList.add('enter-visible'); });
      return;
    }

    rows.forEach(function (row, i) {
      row.style.setProperty('--enter-i', String(i));
      requestAnimationFrame(function () {
        setTimeout(function () {
          row.classList.add('enter-visible');
        }, i * STAGGER_MS);
      });
    });
  }

  function observeRowEntrance(container, selector) {
    if (!container) return;

    const rows = Array.from(container.querySelectorAll(selector));
    if (!rows.length) return;

    if (prefersReducedMotion || !('IntersectionObserver' in window)) {
      staggerRowEntrance(rows);
      return;
    }

    const observer = new IntersectionObserver(function (entries, obs) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        const row = entry.target;
        const siblings = rows.filter(function (r) { return !r.classList.contains('enter-visible'); });
        const idx = rows.indexOf(row);
        row.style.setProperty('--enter-i', String(idx));
        setTimeout(function () {
          row.classList.add('enter-visible');
        }, idx * STAGGER_MS);
        obs.unobserve(row);
      });
    }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });

    rows.forEach(function (row) { observer.observe(row); });
  }

  function moveTabIndicator(activeBtn) {
    if (!tabIndicator || !activeBtn || !tabNavInner) return;
    const navRect = tabNavInner.getBoundingClientRect();
    const btnRect = activeBtn.getBoundingClientRect();
    tabIndicator.style.width = btnRect.width + 'px';
    tabIndicator.style.transform = 'translateX(' + (btnRect.left - navRect.left) + 'px)';
  }

  /* ---- Toast ---- */

  function showToast(message) {
    if (!toastHost) return;

    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    toastHost.appendChild(toast);

    requestAnimationFrame(function () {
      toast.classList.add('show');
    });

    setTimeout(function () {
      toast.classList.remove('show');
      setTimeout(function () { toast.remove(); }, prefersReducedMotion ? 0 : 220);
    }, TOAST_MS);
  }

  /* ---- URL state ---- */

  function readURLState() {
    const params = new URLSearchParams(window.location.search);
    return {
      tab: params.get('tab') || 'index',
      q: params.get('q') || '',
      dept: params.get('dept') || '',
      conf: params.get('conf') || '',
      page: Math.max(1, parseInt(params.get('page') || '1', 10))
    };
  }

  function writeURLState(state) {
    const params = new URLSearchParams();
    if (state.tab && state.tab !== 'index') params.set('tab', state.tab);
    if (state.q) params.set('q', state.q);
    if (state.dept) params.set('dept', state.dept);
    if (state.conf) params.set('conf', state.conf);
    if (paginationEnabled && state.page > 1) params.set('page', String(state.page));
    const qs = params.toString();
    const url = qs ? window.location.pathname + '?' + qs : window.location.pathname;
    history.replaceState(null, '', url);
  }

  function getCurrentFilterState() {
    return {
      tab: document.querySelector('.tab-link.active')?.dataset.tab || 'index',
      q: searchInput ? searchInput.value.trim() : '',
      dept: categoryFilter ? categoryFilter.value : '',
      conf: confidenceFilter ? confidenceFilter.value : '',
      page: currentPage
    };
  }

  /* ---- Overview panel animations ---- */

  function animateOverview() {
    const indexPanel = document.getElementById('index');
    if (!indexPanel) return;

    if (overviewAnimated) {
      animateBars(indexPanel);
      return;
    }
    overviewAnimated = true;

    runCountUps(document);
    animateBars(indexPanel);
    observeRowEntrance(indexPanel, '.enter-row');
  }

  /* ---- Catalog skeleton load ---- */

  function runCatalogLoadSequence(callback) {
    if (!catalogList) {
      if (callback) callback();
      return;
    }

    if (catalogLoaded) {
      if (callback) callback();
      return;
    }

    catalogLoaded = true;

    if (catalogSkeleton) {
      catalogSkeleton.hidden = false;
      catalogSkeleton.classList.remove('fade-out');
    }
    catalogList.classList.add('list-loading');
    catalogList.classList.remove('list-ready');

    const delay = prefersReducedMotion ? 0 : SKELETON_MS;

    setTimeout(function () {
      if (catalogSkeleton) catalogSkeleton.classList.add('fade-out');

      setTimeout(function () {
        if (catalogSkeleton) catalogSkeleton.hidden = true;
        catalogList.classList.remove('list-loading');
        catalogList.classList.add('list-ready');

        const rows = Array.from(catalogList.querySelectorAll('.catalog-record:not(.hidden-record):not(.page-hidden)'));
        staggerRowEntrance(rows);

        if (callback) callback();
      }, prefersReducedMotion ? 0 : ROW_ENTER_MS);
    }, delay);
  }

  /* ---- Tabs ---- */

  function activateTab(tabId, updateURL) {
    let activeBtn = null;

    tabLinks.forEach(function (btn) {
      const isActive = btn.dataset.tab === tabId;
      btn.classList.toggle('active', isActive);
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
      btn.tabIndex = isActive ? 0 : -1;
      if (isActive) activeBtn = btn;
    });

    tabPanels.forEach(function (panel) {
      const isActive = panel.id === tabId;
      panel.classList.toggle('active', isActive);
      panel.hidden = !isActive;
    });

    requestAnimationFrame(function () { moveTabIndicator(activeBtn); });

    if (tabId === 'index') animateOverview();

    if (tabId === 'catalog') {
      runCatalogLoadSequence(function () {
        applyFilters(updateURL === false ? false : undefined);
      });
    } else if (tabId === 'review') {
      observeRowEntrance(document.querySelector('.review-list'), '.catalog-record');
    }

    if (updateURL !== false) {
      const state = getCurrentFilterState();
      state.tab = tabId;
      writeURLState(state);
    }
  }

  tabLinks.forEach(function (btn) {
    btn.addEventListener('click', function () {
      activateTab(btn.dataset.tab);
    });

    btn.addEventListener('keydown', function (e) {
      const tabs = Array.from(tabLinks);
      const idx = tabs.indexOf(btn);
      let next = null;

      if (e.key === 'ArrowRight') next = tabs[(idx + 1) % tabs.length];
      if (e.key === 'ArrowLeft') next = tabs[(idx - 1 + tabs.length) % tabs.length];
      if (e.key === 'Home') next = tabs[0];
      if (e.key === 'End') next = tabs[tabs.length - 1];

      if (next) {
        e.preventDefault();
        next.focus();
        activateTab(next.dataset.tab);
      }
    });
  });

  window.addEventListener('resize', function () {
    const active = document.querySelector('.tab-link.active');
    moveTabIndicator(active);
  });

  /* ---- Reasoning trace reveal ---- */

  function clearTraceTimers() {
    traceTimers.forEach(clearTimeout);
    traceTimers = [];
  }

  function resetReasoningTrace(detail) {
    const notesEl = detail.querySelector('.notes-text');
    if (!notesEl) return;

    clearTraceTimers();
    const fullText = notesEl.dataset.fullText;
    if (fullText !== undefined) {
      notesEl.textContent = fullText;
    }
    notesEl.dataset.revealed = 'false';
    notesEl.querySelectorAll('.trace-cursor').forEach(function (c) { c.remove(); });
  }

  function revealReasoningTrace(detail) {
    const notesEl = detail.querySelector('.notes-text');
    if (!notesEl) return;

    const fullText = notesEl.dataset.fullText || notesEl.textContent.trim();
    notesEl.dataset.fullText = fullText;

    if (notesEl.dataset.revealed === 'true') return;

    clearTraceTimers();
    notesEl.textContent = '';
    notesEl.dataset.revealed = 'in-progress';

    if (prefersReducedMotion || !fullText) {
      notesEl.textContent = fullText || 'No reasoning notes recorded for this entry.';
      notesEl.dataset.revealed = 'true';
      return;
    }

    const sentences = fullText.match(/[^.!?\n]+[.!?\n]?/g) || [fullText];
    let delay = 0;

    sentences.forEach(function (sentence, i) {
      const trimmed = sentence.trim();
      if (!trimmed) return;

      const timer = setTimeout(function () {
        const span = document.createElement('span');
        span.className = 'trace-line';
        span.textContent = trimmed + (i < sentences.length - 1 ? ' ' : '');
        notesEl.appendChild(span);

        requestAnimationFrame(function () {
          span.classList.add('visible');
        });

        notesEl.querySelectorAll('.trace-cursor').forEach(function (c) { c.remove(); });

        if (i < sentences.length - 1) {
          const cursor = document.createElement('span');
          cursor.className = 'trace-cursor';
          cursor.setAttribute('aria-hidden', 'true');
          notesEl.appendChild(cursor);
        } else {
          notesEl.dataset.revealed = 'true';
        }
      }, delay);

      traceTimers.push(timer);
      delay += Math.max(120, trimmed.length * 18);
    });
  }

  function resetSpecAnimation(detail) {
    detail.querySelectorAll('.spec-col').forEach(function (col) {
      col.style.animation = 'none';
      col.style.opacity = '';
      col.style.transform = '';
      void col.offsetWidth;
      col.style.animation = '';
    });
    const notesBox = detail.querySelector('.notes-box');
    if (notesBox) {
      notesBox.style.animation = 'none';
      notesBox.style.opacity = '';
      notesBox.style.transform = '';
      void notesBox.offsetWidth;
      notesBox.style.animation = '';
    }
  }

  /* ---- Expand / collapse entries ---- */

  function closeEntry(entryEl) {
    const detailId = entryEl.getAttribute('aria-controls');
    if (!detailId) return;
    const detail = document.getElementById(detailId);
    if (!detail) return;

    detail.classList.remove('open');
    entryEl.setAttribute('aria-expanded', 'false');
    resetReasoningTrace(detail);
    resetSpecAnimation(detail);
  }

  function toggleEntry(entryEl) {
    const detailId = entryEl.getAttribute('aria-controls');
    if (!detailId) return;
    const detail = document.getElementById(detailId);
    if (!detail) return;

    const isOpen = detail.classList.contains('open');

    document.querySelectorAll('.entry[aria-expanded="true"]').forEach(function (openEntry) {
      if (openEntry !== entryEl) closeEntry(openEntry);
    });

    if (isOpen) {
      closeEntry(entryEl);
    } else {
      resetSpecAnimation(detail);
      detail.classList.add('open');
      entryEl.setAttribute('aria-expanded', 'true');
      revealReasoningTrace(detail);
    }
  }

  function bindExpandableEntries(root) {
    root.querySelectorAll('.entry[role="button"]').forEach(function (entryEl) {
      entryEl.addEventListener('click', function () { toggleEntry(entryEl); });
      entryEl.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          toggleEntry(entryEl);
        }
        if (e.key === 'Escape') {
          closeEntry(entryEl);
          entryEl.blur();
        }
      });
    });
  }

  bindExpandableEntries(document);

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    document.querySelectorAll('.entry[aria-expanded="true"]').forEach(closeEntry);
  });

  /* ---- Filtering & pagination ---- */

  function matchesConfidence(score, level) {
    if (!level) return true;
    if (level === 'high') return score >= 85;
    if (level === 'mid') return score >= 70 && score < 85;
    if (level === 'low') return score < 70;
    return true;
  }

  function applyPagination() {
    if (!paginationEnabled) return;

    const totalVisible = visibleRecords.length;
    const totalPages = Math.max(1, Math.ceil(totalVisible / PAGE_SIZE));

    if (currentPage > totalPages) currentPage = totalPages;

    const start = (currentPage - 1) * PAGE_SIZE;
    const end = start + PAGE_SIZE;

    visibleRecords.forEach(function (record, i) {
      const hide = i < start || i >= end;
      record.classList.toggle('page-hidden', hide);
      if (!hide && !record.classList.contains('enter-visible')) {
        record.classList.add('enter-visible');
      }
    });

    pagination.hidden = totalPages <= 1;
    pagePrev.disabled = currentPage <= 1;
    pageNext.disabled = currentPage >= totalPages;
    pageInfo.textContent = 'Page ' + currentPage + ' of ' + totalPages + ' · ' + totalVisible + ' matching';
  }

  function applyFilters(updateURL) {
    if (!catalogList) return;

    const search = searchInput.value.toLowerCase().trim();
    const category = categoryFilter.value;
    const confidence = confidenceFilter.value;
    const records = catalogList.querySelectorAll('.catalog-record');
    const previouslyVisible = new Set(visibleRecords);

    visibleRecords = [];

    records.forEach(function (record) {
      const matchesSearch = !search || record.dataset.search.includes(search);
      const matchesCategory = !category || record.dataset.category === category;
      const score = parseFloat(record.dataset.confidence) || 0;
      const matchesConf = matchesConfidence(score, confidence);
      const visible = matchesSearch && matchesCategory && matchesConf;
      const wasVisible = !record.classList.contains('hidden-record');

      if (visible) {
        record.classList.remove('hidden-record');
        if (!wasVisible) record.classList.add('filter-in');
        visibleRecords.push(record);
      } else {
        record.classList.remove('filter-in');
        const entry = record.querySelector('.entry[aria-expanded="true"]');
        if (entry) closeEntry(entry);

        if (wasVisible && !prefersReducedMotion) {
          record.classList.add('hidden-record');
        } else {
          record.classList.add('hidden-record');
        }
      }

      record.classList.remove('page-hidden');
    });

    const matchCount = visibleRecords.length;
    const hasFilters = search || category || confidence;

    if (matchCount === 0) {
      catalogEmpty.hidden = false;
      catalogList.hidden = true;
      filterStatus.textContent = hasFilters
        ? '0 entries match the current filters.'
        : 'No catalog entries available.';
    } else {
      catalogEmpty.hidden = true;
      catalogList.hidden = false;
      filterStatus.textContent = hasFilters
        ? matchCount + ' of ' + totalRecords + ' entries shown'
        : totalRecords + ' entries';
    }

    if (paginationEnabled) {
      applyPagination();
    } else if (!prefersReducedMotion) {
      visibleRecords.forEach(function (record, i) {
        if (!previouslyVisible.has(record) && !record.classList.contains('enter-visible')) {
          record.style.setProperty('--enter-i', String(i % 20));
          requestAnimationFrame(function () {
            record.classList.add('enter-visible');
          });
        }
      });
    } else {
      visibleRecords.forEach(function (record) {
        record.classList.add('enter-visible');
      });
    }

    if (updateURL !== false) {
      writeURLState(getCurrentFilterState());
    }
  }

  function debouncedApplyFilters() {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(function () {
      currentPage = 1;
      applyFilters();
    }, DEBOUNCE_MS);
  }

  if (searchInput) {
    searchInput.addEventListener('input', debouncedApplyFilters);
  }
  if (categoryFilter) {
    categoryFilter.addEventListener('change', function () {
      currentPage = 1;
      applyFilters();
    });
  }
  if (confidenceFilter) {
    confidenceFilter.addEventListener('change', function () {
      currentPage = 1;
      applyFilters();
    });
  }

  if (pagePrev) {
    pagePrev.addEventListener('click', function () {
      if (currentPage > 1) {
        currentPage--;
        applyPagination();
        writeURLState(getCurrentFilterState());
        catalogList.scrollIntoView({ behavior: prefersReducedMotion ? 'auto' : 'smooth', block: 'start' });
      }
    });
  }

  if (pageNext) {
    pageNext.addEventListener('click', function () {
      const totalPages = Math.ceil(visibleRecords.length / PAGE_SIZE);
      if (currentPage < totalPages) {
        currentPage++;
        applyPagination();
        writeURLState(getCurrentFilterState());
        catalogList.scrollIntoView({ behavior: prefersReducedMotion ? 'auto' : 'smooth', block: 'start' });
      }
    });
  }

  /* ---- Export toast ---- */

  if (exportBtn) {
    exportBtn.addEventListener('click', function () {
      showToast('Export started — enriched_products.csv downloading');
    });
  }

  /* ---- Init from URL ---- */

  function initFromURL() {
    const state = readURLState();
    const tabId = ['index', 'catalog', 'review'].includes(state.tab) ? state.tab : 'index';

    if (searchInput) searchInput.value = state.q;
    if (categoryFilter) categoryFilter.value = state.dept;
    if (confidenceFilter) confidenceFilter.value = state.conf;
    currentPage = state.page;

    activateTab(tabId, false);
    writeURLState(getCurrentFilterState());

    requestAnimationFrame(function () {
      moveTabIndicator(document.querySelector('.tab-link.active'));
    });
  }

  initFromURL();

  /* ---- Masthead ticker ---- */

  const heroDataEl = document.getElementById('heroData');
  if (heroDataEl) {
    let examples;
    try {
      examples = JSON.parse(heroDataEl.textContent);
    } catch (err) {
      examples = [];
    }

    if (examples.length) {
      const rawEl = document.getElementById('tickerRaw');
      const arrowEl = document.getElementById('tickerArrow');
      const resultEl = document.getElementById('tickerResult');
      let cycleIndex = 0;

      function typeText(el, text, speed, callback) {
        el.textContent = '';
        let idx = 0;
        const cursor = document.createElement('span');
        cursor.className = 'ticker-cursor';
        cursor.setAttribute('aria-hidden', 'true');

        function step() {
          el.textContent = text.slice(0, idx);
          el.appendChild(cursor);
          idx++;
          if (idx <= text.length) {
            setTimeout(step, speed);
          } else if (callback) {
            cursor.remove();
            callback();
          }
        }
        step();
      }

      function runCycle() {
        const ex = examples[cycleIndex % examples.length];
        arrowEl.classList.remove('show');
        resultEl.classList.remove('show');

        const rawText = ex.raw || '—';
        typeText(rawEl, rawText, 28, function () {
          setTimeout(function () {
            arrowEl.classList.add('show');
            const title = ex.title || '—';
            const cat = ex.category || '—';
            const conf = ex.confidence !== undefined && ex.confidence !== null ? ex.confidence : '—';
            resultEl.textContent = title + ' · ' + cat + ' · confidence ' + conf;
            resultEl.classList.add('show');
          }, 350);
        });

        cycleIndex++;
        setTimeout(runCycle, rawText.length * 28 + 4500);
      }

      runCycle();
    }
  }
})();
