/* ========== Telethon Platform Dashboard ========== */

let _autoTimer = null;

/* ========== HELPERS ========== */

function esc(s) {
    const d = document.createElement('div');
    d.appendChild(document.createTextNode(s || ''));
    return d.innerHTML;
}

function fmtTime(ts) {
    if (!ts) return '-';
    const d = new Date(ts * 1000);
    return d.toLocaleString('ru-RU', {day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit'});
}

function fmtAgo(ts) {
    if (!ts) return '-';
    const secs = Math.floor(Date.now() / 1000 - ts);
    if (secs < 60) return secs + 's ago';
    if (secs < 3600) return Math.floor(secs / 60) + 'm ago';
    if (secs < 86400) return Math.floor(secs / 3600) + 'h ago';
    return Math.floor(secs / 86400) + 'd ago';
}

function statusClass(status) {
    if (status === 'healthy') return 'healthy';
    if (status === 'flood_wait') return 'flood';
    if (status === 'error') return 'error';
    if (status === 'banned') return 'banned';
    return 'offline';
}

function showAlert(msg) {
    const bar = document.getElementById('alerts-bar');
    bar.textContent = msg;
    bar.classList.remove('hidden');
}

function hideAlerts() {
    document.getElementById('alerts-bar').classList.add('hidden');
}

/* ========== SUMMARY ========== */

function refreshSummary() {
    fetch('/api/status')
        .then(r => r.json())
        .then(data => {
            document.getElementById('s-healthy').textContent =
                data.healthy_accounts + '/' + data.total_accounts;
            document.getElementById('s-chats').textContent = data.active_chats;
            document.getElementById('s-ops').textContent = data.total_operations;
            document.getElementById('s-errors').textContent = data.total_errors;
            document.getElementById('s-failovers').textContent = data.total_failovers;

            if (data.healthy_accounts === 0 && data.total_accounts > 0) {
                showAlert('All accounts are unhealthy!');
            }
        })
        .catch(() => {});
}

/* ========== ACCOUNTS ========== */

function refreshAccounts() {
    fetch('/api/accounts')
        .then(r => r.json())
        .then(data => {
            const grid = document.getElementById('accounts-grid');
            let html = '';
            for (const acc of data.accounts) {
                const cls = statusClass(acc.status);
                const floodInfo = acc.flood_remaining > 0
                    ? `<div class="ac-row"><span class="label">Flood ends in</span><span style="color:var(--yellow)">${acc.flood_remaining}s</span></div>`
                    : '';
                const errorInfo = acc.last_error
                    ? `<div class="ac-row"><span class="label">Last error</span><span style="color:var(--red);max-width:180px;overflow:hidden;text-overflow:ellipsis;display:inline-block" title="${esc(acc.last_error)}">${esc(acc.last_error.substring(0, 40))}</span></div>`
                    : '';

                html += `
                <div class="account-card ${cls}">
                    <div class="ac-header">
                        <span class="dot ${cls}"></span>
                        <span class="name">${esc(acc.name)}</span>
                        <span class="badge ${cls}">${esc(acc.status)}</span>
                    </div>
                    <div class="ac-body">
                        <div class="ac-row"><span class="label">Session</span><span>${esc(acc.session)}</span></div>
                        <div class="ac-row"><span class="label">Priority</span><span>${acc.priority}</span></div>
                        <div class="ac-row"><span class="label">User ID</span><span>${acc.self_user_id || '-'}</span></div>
                        <div class="ac-row"><span class="label">Username</span><span>@${esc(acc.self_username || '-')}</span></div>
                        <div class="ac-row"><span class="label">Cache</span><span>${acc.cache_size} entities</span></div>
                        <div class="ac-row"><span class="label">Operations</span><span>${acc.operations_count}</span></div>
                        <div class="ac-row"><span class="label">Errors</span><span>${acc.error_count}</span></div>
                        <div class="ac-row"><span class="label">Last active</span><span>${fmtAgo(acc.last_active)}</span></div>
                        ${floodInfo}
                        ${errorInfo}
                    </div>
                    <div class="ac-controls">
                        <button onclick="ctrlAccount('${esc(acc.name)}','reload_cache')" class="btn btn-sm btn-blue">Reload Cache</button>
                        <button onclick="ctrlAccount('${esc(acc.name)}','reset_errors')" class="btn btn-sm btn-green">Reset Errors</button>
                        <button onclick="ctrlAccount('${esc(acc.name)}','clear_flood')" class="btn btn-sm">Clear Flood</button>
                    </div>
                </div>`;
            }
            grid.innerHTML = html;
        })
        .catch(() => {});
}

function ctrlAccount(name, action) {
    fetch('/api/control', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({account: name, action: action}),
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'ok') {
            setTimeout(refreshAccounts, 1000);
        } else {
            alert('Error: ' + (data.error || JSON.stringify(data)));
        }
    })
    .catch(e => alert('Failed: ' + e));
}

/* ========== CHATS ========== */

function refreshChats() {
    fetch('/api/chats?limit=200')
        .then(r => r.json())
        .then(data => {
            const tbody = document.getElementById('chats-tbody');
            let html = '';
            for (const c of data.chats) {
                const cls = c.status === 'active' ? 'status-active' : 'status-left';
                html += `<tr>
                    <td>${esc(c.chat_id)}</td>
                    <td>${esc(c.title)}</td>
                    <td>${esc(c.account_name)}</td>
                    <td>${fmtTime(c.created_at)}</td>
                    <td class="${cls}">${esc(c.status)}</td>
                </tr>`;
            }
            tbody.innerHTML = html || '<tr><td colspan="5" class="muted" style="text-align:center;padding:20px">No chats yet</td></tr>';
        })
        .catch(() => {});
}

/* ========== OPERATIONS ========== */

function refreshOperations() {
    fetch('/api/operations?limit=100')
        .then(r => r.json())
        .then(data => {
            const tbody = document.getElementById('ops-tbody');
            let html = '';
            for (const op of data.operations) {
                let cls = '';
                if (op.status === 'ok') cls = 'status-ok';
                else if (op.status === 'error' || op.status === 'banned') cls = 'status-error';
                else if (op.status === 'flood_wait') cls = 'status-flood';

                html += `<tr>
                    <td>${fmtTime(op.ts)}</td>
                    <td>${esc(op.account_name)}</td>
                    <td>${esc(op.chat_id)}</td>
                    <td>${esc(op.operation)}</td>
                    <td class="${cls}">${esc(op.status)}</td>
                    <td class="detail" title="${esc(op.detail)}">${esc((op.detail || '').substring(0, 60))}</td>
                </tr>`;
            }
            tbody.innerHTML = html || '<tr><td colspan="6" class="muted" style="text-align:center;padding:20px">No operations yet</td></tr>';
        })
        .catch(() => {});
}

/* ========== FAILOVERS ========== */

function refreshFailovers() {
    fetch('/api/failovers?limit=50')
        .then(r => r.json())
        .then(data => {
            const tbody = document.getElementById('fo-tbody');
            let html = '';
            for (const fo of data.failovers) {
                html += `<tr>
                    <td>${fmtTime(fo.ts)}</td>
                    <td>${esc(fo.chat_id)}</td>
                    <td>${esc(fo.from_account)}</td>
                    <td>${esc(fo.to_account)}</td>
                    <td class="detail" title="${esc(fo.reason)}">${esc((fo.reason || '').substring(0, 60))}</td>
                </tr>`;
            }
            tbody.innerHTML = html || '<tr><td colspan="5" class="muted" style="text-align:center;padding:20px">No failovers yet</td></tr>';
        })
        .catch(() => {});
}

/* ========== TABS ========== */

function initTabs() {
    const buttons = document.querySelectorAll('.tab-btn');
    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            buttons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
            document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
        });
    });
}

/* ========== REFRESH ========== */

function refreshAll() {
    hideAlerts();
    refreshSummary();
    refreshAccounts();
    refreshChats();
    refreshOperations();
    refreshFailovers();
    document.getElementById('last-update').textContent = 'Updated: ' + new Date().toLocaleTimeString();
}

function startAutoRefresh() {
    if (_autoTimer) clearInterval(_autoTimer);
    _autoTimer = setInterval(refreshAll, 30000);
}

/* ========== INIT ========== */

document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    refreshAll();
    startAutoRefresh();
});
