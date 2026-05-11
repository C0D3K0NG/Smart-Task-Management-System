/* ================================================================
   dashboard.js — Task Manager frontend logic
   ================================================================ */

'use strict';

// ── State ──────────────────────────────────────────────────────
let tasks        = [];
let editingId    = null;
let activeFilter = '';
let searchQuery  = '';
let deletingId   = null;
let sortMode     = 'created_desc';

// ── DOM refs ───────────────────────────────────────────────────
const taskList    = document.getElementById('task-list');
const modal       = document.getElementById('task-modal');
const modalTitle  = document.getElementById('modal-title');
const titleInput  = document.getElementById('task-title');
const descInput   = document.getElementById('task-desc');
const prioSelect  = document.getElementById('task-priority');
const statSelect  = document.getElementById('task-status');
const dueDateInput= document.getElementById('task-due-date');
const modalErr    = document.getElementById('modal-error');
const toast       = document.getElementById('toast');
const wsDot       = document.getElementById('ws-dot');
const wsLabel     = document.getElementById('ws-label');
const searchInput = document.getElementById('search-input');
const deleteModal = document.getElementById('delete-modal');
const sortSelect  = document.getElementById('sort-select');
const progressFill  = document.getElementById('progress-fill');
const progressLabel = document.getElementById('progress-label');
const progressCount = document.getElementById('progress-count');

// ── Theme Toggle ──────────────────────────────────────────────
const themeToggle = document.getElementById('theme-toggle-sidebar');
const themeIcon   = document.getElementById('theme-icon');

function updateThemeUI() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  if (themeIcon) themeIcon.textContent = isDark ? '☀️' : '🌙';
}
updateThemeUI();

themeToggle?.addEventListener('click', () => {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
  updateThemeUI();
});

// ── WebSocket ──────────────────────────────────────────────────
const socket = io({ transports: ['websocket', 'polling'] });

socket.on('connect', () => {
  wsDot.className  = 'ws-dot connected';
  wsLabel.textContent = 'Live — real-time updates active';
});

socket.on('disconnect', () => {
  wsDot.className  = 'ws-dot disconnected';
  wsLabel.textContent = 'Disconnected';
});

socket.on('connect_error', () => {
  wsDot.className  = 'ws-dot error';
  wsLabel.textContent = 'Connection error';
});

socket.on('task_added', task => {
  if (!tasks.find(t => t.id === task.id)) {
    tasks.unshift(task);
    renderTasks();
    showToast('✦ New task added');
  }
});

socket.on('task_updated', updated => {
  const idx = tasks.findIndex(t => t.id === updated.id);
  if (idx !== -1) {
    tasks[idx] = updated;
    renderTasks();
    showToast('Task updated');
  }
});

socket.on('task_deleted', ({ id }) => {
  tasks = tasks.filter(t => t.id !== id);
  renderTasks();
  showToast('Task removed');
});

// ── Fetch Tasks ────────────────────────────────────────────────
async function fetchTasks(status = '') {
  taskList.innerHTML = '<div class="loading-state">Loading tasks…</div>';
  try {
    const qs  = status ? `?status=${status}` : '';
    const res = await fetch(`/api/tasks${qs}`);
    if (!res.ok) throw new Error('Fetch failed');
    const data = await res.json();
    tasks = data.tasks || [];
    renderTasks();
  } catch {
    taskList.innerHTML = '<div class="loading-state">Failed to load tasks.</div>';
  }
}

// ── Sort Tasks ─────────────────────────────────────────────────
const PRIO_ORDER = { high: 3, medium: 2, low: 1 };

function sortTasks(list) {
  const sorted = [...list];
  switch (sortMode) {
    case 'created_desc':
      sorted.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
      break;
    case 'created_asc':
      sorted.sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
      break;
    case 'priority_desc':
      sorted.sort((a, b) => (PRIO_ORDER[b.priority] || 0) - (PRIO_ORDER[a.priority] || 0));
      break;
    case 'priority_asc':
      sorted.sort((a, b) => (PRIO_ORDER[a.priority] || 0) - (PRIO_ORDER[b.priority] || 0));
      break;
    case 'title_asc':
      sorted.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
      break;
    case 'due_asc':
      sorted.sort((a, b) => {
        if (!a.due_date && !b.due_date) return 0;
        if (!a.due_date) return 1;
        if (!b.due_date) return -1;
        return a.due_date.localeCompare(b.due_date);
      });
      break;
  }
  return sorted;
}

// ── Update Progress Bar ────────────────────────────────────────
function updateProgress() {
  const total     = tasks.length;
  const completed = tasks.filter(t => t.status === 'completed').length;
  const pct       = total ? Math.round((completed / total) * 100) : 0;

  progressFill.style.width = `${pct}%`;
  progressLabel.textContent = `${pct}% complete`;
  progressCount.textContent = `${completed}/${total} tasks`;

  // Celebrate 100%!
  if (total > 0 && pct === 100) {
    progressLabel.textContent = '🎉 All tasks complete!';
  }
}

// ── Update Filter Badge Counts ─────────────────────────────────
function updateBadgeCounts() {
  const counts = { all: tasks.length, pending: 0, in_progress: 0, completed: 0 };
  tasks.forEach(t => { if (counts[t.status] !== undefined) counts[t.status]++; });

  const setCount = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val > 0 ? val : '';
  };
  setCount('count-all', counts.all);
  setCount('count-pending', counts.pending);
  setCount('count-in_progress', counts.in_progress);
  setCount('count-completed', counts.completed);
}

// ── Due Date Helpers ───────────────────────────────────────────
function getDueDateInfo(dueDateStr) {
  if (!dueDateStr) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(dueDateStr + 'T00:00:00');
  const diffMs = due - today;
  const diffDays = Math.round(diffMs / 86400000);

  if (diffDays < 0) return { label: `${Math.abs(diffDays)}d overdue`, cls: 'overdue' };
  if (diffDays === 0) return { label: 'Due today', cls: 'due-soon' };
  if (diffDays === 1) return { label: 'Due tomorrow', cls: 'due-soon' };
  if (diffDays <= 3) return { label: `Due in ${diffDays}d`, cls: 'due-soon' };
  return { label: `Due ${due.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`, cls: '' };
}

// ── Render Tasks ───────────────────────────────────────────────
function renderTasks() {
  updateProgress();
  updateBadgeCounts();

  let filtered = tasks;

  // Apply search filter
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    filtered = filtered.filter(t =>
      t.title.toLowerCase().includes(q) ||
      (t.description && t.description.toLowerCase().includes(q))
    );
  }

  // Apply sort
  filtered = sortTasks(filtered);

  if (!filtered.length) {
    const msg = searchQuery
      ? `No tasks matching "${escHtml(searchQuery)}"`
      : 'No tasks yet. Add one to get started.';
    taskList.innerHTML = `
      <div class="empty-state">
        <span class="empty-icon">◈</span>
        <p>${msg}</p>
      </div>`;
    return;
  }

  taskList.innerHTML = filtered.map(t => {
    const done       = t.status === 'completed';
    const dateStr    = new Date(t.created_at).toLocaleDateString('en-US', { month:'short', day:'numeric' });
    const checkClass = done ? 'task-check done' : 'task-check';
    const dueInfo    = !done ? getDueDateInfo(t.due_date) : null;

    return `
      <div class="task-card" data-id="${t.id}">
        <div class="${checkClass}" onclick="toggleComplete(${t.id}, '${t.status}')"></div>
        <div class="task-body">
          <div class="task-title ${done ? 'done-text' : ''}">${escHtml(t.title)}</div>
          ${t.description ? `<div class="task-desc">${escHtml(t.description)}</div>` : ''}
          <div class="task-meta">
            <span class="badge badge-${t.priority}">${t.priority}</span>
            <span class="badge badge-${t.status}">${t.status.replace('_',' ')}</span>
            ${dueInfo ? `<span class="task-due ${dueInfo.cls}">📅 ${dueInfo.label}</span>` : ''}
            <span class="task-date">${dateStr}</span>
          </div>
        </div>
        <div class="task-actions">
          <button class="icon-btn" onclick="duplicateTask(${t.id})" title="Duplicate">⧉</button>
          <button class="icon-btn" onclick="openEdit(${t.id})" title="Edit">✎</button>
          <button class="icon-btn delete" onclick="confirmDelete(${t.id})" title="Delete">✕</button>
        </div>
      </div>`;
  }).join('');
}

// ── Toggle Complete ────────────────────────────────────────────
async function toggleComplete(id, currentStatus) {
  const newStatus = currentStatus === 'completed' ? 'pending' : 'completed';
  await apiUpdateTask(id, { status: newStatus });
}

// ── Modal helpers ──────────────────────────────────────────────
function openAddModal() {
  editingId = null;
  modalTitle.textContent = 'New Task';
  titleInput.value = descInput.value = '';
  prioSelect.value = 'medium';
  statSelect.value = 'pending';
  dueDateInput.value = '';
  modalErr.classList.add('hidden');
  modal.classList.remove('hidden');
  titleInput.focus();
}

function openEdit(id) {
  const t = tasks.find(t => t.id === id);
  if (!t) return;
  editingId = id;
  modalTitle.textContent = 'Edit Task';
  titleInput.value  = t.title;
  descInput.value   = t.description || '';
  prioSelect.value  = t.priority;
  statSelect.value  = t.status;
  dueDateInput.value = t.due_date || '';
  modalErr.classList.add('hidden');
  modal.classList.remove('hidden');
  titleInput.focus();
}

function closeModal() { modal.classList.add('hidden'); }

// ── Delete Confirmation Modal ──────────────────────────────────
function confirmDelete(id) {
  deletingId = id;
  deleteModal.classList.remove('hidden');
}

function closeDeleteModal() {
  deletingId = null;
  deleteModal.classList.add('hidden');
}

document.getElementById('cancel-delete').addEventListener('click', closeDeleteModal);
document.getElementById('confirm-delete').addEventListener('click', async () => {
  if (deletingId !== null) {
    closeDeleteModal();
    await deleteTask(deletingId);
  }
});

deleteModal.addEventListener('click', e => {
  if (e.target === deleteModal) closeDeleteModal();
});

// ── Save Task ──────────────────────────────────────────────────
document.getElementById('save-task-btn').addEventListener('click', async () => {
  const title    = titleInput.value.trim();
  const desc     = descInput.value.trim();
  const priority = prioSelect.value;
  const status   = statSelect.value;
  const due_date = dueDateInput.value || null;

  if (!title) {
    modalErr.textContent = 'Title is required.';
    modalErr.classList.remove('hidden');
    return;
  }
  modalErr.classList.add('hidden');

  if (editingId) {
    await apiUpdateTask(editingId, { title, description: desc, priority, status, due_date });
  } else {
    await apiAddTask({ title, description: desc, priority, status, due_date });
  }
  closeModal();
});

// ── API Calls ──────────────────────────────────────────────────
async function apiAddTask(payload) {
  const res  = await fetch('/api/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (res.ok) {
    tasks.unshift(data.task);
    renderTasks();
    showToast('Task added ✓');
  } else {
    showToast(data.error || 'Error adding task');
  }
}

async function apiUpdateTask(id, payload) {
  const res  = await fetch(`/api/tasks/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (res.ok) {
    const idx = tasks.findIndex(t => t.id === id);
    if (idx !== -1) tasks[idx] = data.task;
    renderTasks();
    showToast('Task updated ✓');
  } else {
    showToast(data.error || 'Error updating task');
  }
}

async function deleteTask(id) {
  // Animate removal
  const card = document.querySelector(`.task-card[data-id="${id}"]`);
  if (card) {
    card.classList.add('removing');
    await new Promise(r => setTimeout(r, 350));
  }

  const res = await fetch(`/api/tasks/${id}`, { method: 'DELETE' });
  if (res.ok) {
    tasks = tasks.filter(t => t.id !== id);
    renderTasks();
    showToast('Task deleted');
  } else {
    showToast('Error deleting task');
    if (card) card.classList.remove('removing');
  }
}

// ── Duplicate Task ─────────────────────────────────────────────
async function duplicateTask(id) {
  const res = await fetch(`/api/tasks/${id}/duplicate`, { method: 'POST' });
  const data = await res.json();
  if (res.ok) {
    tasks.unshift(data.task);
    renderTasks();
    showToast('Task duplicated ✓');
  } else {
    showToast(data.error || 'Error duplicating task');
  }
}

// ── Export Tasks ───────────────────────────────────────────────
document.getElementById('export-btn')?.addEventListener('click', () => {
  window.location.href = '/api/tasks/export';
});

// ── Analytics ──────────────────────────────────────────────────
async function loadAnalytics() {
  const content = document.getElementById('analytics-content');
  content.innerHTML = '<div class="loading-state">Computing analytics…</div>';
  try {
    const res  = await fetch('/api/analytics');
    const data = await res.json();
    renderAnalytics(data, content);
  } catch {
    content.innerHTML = '<div class="loading-state">Failed to load analytics.</div>';
  }
}

function renderAnalytics(data, el) {
  const s   = data.summary;
  const prio = data.priority_breakdown;
  const maxP = Math.max(prio.low, prio.medium, prio.high, 1);
  const trend = data.daily_trend || {};
  const vals  = Object.values(trend);
  const maxV  = Math.max(...vals, 1);
  const today = new Date().toISOString().slice(0, 10);

  const sparkBars = Object.entries(trend).map(([day, count]) => {
    const h   = Math.max(4, Math.round((count / maxV) * 56));
    const cls = day === today ? 'spark-bar today' : 'spark-bar';
    return `<div class="${cls}" style="height:${h}px" title="${day}: ${count} task(s)"></div>`;
  }).join('');

  const ageStat = (label, val) =>
    `<div class="age-stat"><span>${label}</span><span>${val} day${val !== 1 ? 's' : ''}</span></div>`;

  el.innerHTML = `
    <div class="stats-grid">
      ${statCard('Total Tasks', s.total_tasks, '')}
      ${statCard('Completed',   s.completed_tasks, `${s.completion_pct}%`)}
      ${statCard('Pending',     s.pending_tasks, '')}
      ${statCard('In Progress', s.in_progress_tasks, '')}
    </div>

    <div class="analytics-grid">
      <div class="analytics-card">
        <h4>Priority Breakdown</h4>
        ${prioBar('high',   prio.high,   maxP)}
        ${prioBar('medium', prio.medium, maxP)}
        ${prioBar('low',    prio.low,    maxP)}
      </div>

      <div class="analytics-card">
        <h4>14-Day Creation Trend</h4>
        <div class="sparkline-wrap">
          <div class="sparkline">${sparkBars}</div>
        </div>
        <p style="font-size:.75rem;color:var(--muted);margin-top:8px;">
          Avg ${data.avg_tasks_per_day}/day · Peak ${data.peak_day_count}
        </p>
      </div>

      <div class="analytics-card">
        <h4>Completion Rate by Priority</h4>
        ${['high','medium','low'].map(p => prioBar(p, data.completion_by_priority[p], 100, true)).join('')}
      </div>

      <div class="analytics-card">
        <h4>Open Task Age</h4>
        ${ageStat('Average', data.open_task_age.mean_days)}
        ${ageStat('Median',  data.open_task_age.median_days)}
        ${ageStat('Oldest',  data.open_task_age.max_days)}
      </div>
    </div>

    <p style="font-size:.72rem;color:var(--muted);margin-top:16px;">
      Generated at ${new Date(data.generated_at).toLocaleTimeString()} — powered by Pandas &amp; NumPy
    </p>
  `;
}

function statCard(label, value, sub) {
  return `
    <div class="stat-card">
      <div class="stat-label">${label}</div>
      <div class="stat-value">${value}</div>
      ${sub ? `<div class="stat-sub">${sub}</div>` : ''}
    </div>`;
}

function prioBar(name, value, max, isPct = false) {
  const pct   = Math.round((value / max) * 100);
  const label = isPct ? `${value}%` : value;
  return `
    <div class="priority-bar-row">
      <span>${name}</span>
      <div class="bar-track">
        <div class="bar-fill ${name}" style="width:${pct}%"></div>
      </div>
      <span class="bar-count">${label}</span>
    </div>`;
}

// ── Toast ──────────────────────────────────────────────────────
let toastTimer;
function showToast(msg) {
  toast.textContent = msg;
  toast.classList.remove('hidden');
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.add('hidden'), 2800);
}

// ── Util ───────────────────────────────────────────────────────
function escHtml(str) {
  return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Nav ────────────────────────────────────────────────────────
document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const view = btn.dataset.view;
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.getElementById(`view-${view}`).classList.add('active');
    if (view === 'analytics') loadAnalytics();
  });
});

// ── Filter buttons ─────────────────────────────────────────────
document.querySelectorAll('.filter-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeFilter = btn.dataset.status;
    fetchTasks(activeFilter);
  });
});

// ── Sort ───────────────────────────────────────────────────────
sortSelect?.addEventListener('change', () => {
  sortMode = sortSelect.value;
  renderTasks();
});

// ── Search ─────────────────────────────────────────────────────
let searchDebounce;
searchInput.addEventListener('input', () => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => {
    searchQuery = searchInput.value.trim();
    renderTasks();
  }, 200);
});

// ── Keyboard Shortcuts ─────────────────────────────────────────
document.addEventListener('keydown', e => {
  // Don't trigger shortcuts when typing in inputs
  const tag = e.target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

  if (e.key === 'n' || e.key === 'N') {
    e.preventDefault();
    openAddModal();
  }

  if (e.key === 'Escape') {
    if (!modal.classList.contains('hidden')) closeModal();
    if (!deleteModal.classList.contains('hidden')) closeDeleteModal();
  }

  // Ctrl+K / Cmd+K to focus search
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault();
    searchInput.focus();
  }
});

// ── Modal buttons ──────────────────────────────────────────────
document.getElementById('open-modal-btn').addEventListener('click', openAddModal);
document.getElementById('close-modal').addEventListener('click',   closeModal);
document.getElementById('cancel-modal').addEventListener('click',  closeModal);
modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });

// ── Logout ─────────────────────────────────────────────────────
document.getElementById('logout-btn').addEventListener('click', async () => {
  await fetch('/api/auth/logout', { method: 'POST' });
  window.location.href = '/login';
});

// ── Refresh analytics ──────────────────────────────────────────
document.getElementById('refresh-analytics')?.addEventListener('click', loadAnalytics);

// ── Init ───────────────────────────────────────────────────────
fetchTasks();
