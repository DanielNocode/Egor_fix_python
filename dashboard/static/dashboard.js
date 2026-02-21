/* ========== Панель управления Telethon ========== */

let _autoTimer = null;
let _allLogs = [];

/* ========== ПЕРЕВОД ОШИБОК ========== */

const ERROR_TRANSLATIONS = [
    { pattern: /database is locked/i,
      text: 'Файл сессии заблокирован другим процессом',
      action: 'Нажмите "Перезапустить" или убейте старый процесс на сервере' },
    { pattern: /FloodWait.*?(\d+)/i,
      text: 'Telegram ограничил запросы',
      action: 'Подождите — аккаунт восстановится автоматически через указанное время' },
    { pattern: /banned|deactivat/i,
      text: 'Аккаунт заблокирован Telegram',
      action: 'Обратитесь в поддержку Telegram (support.telegram.org) для разблокировки' },
    { pattern: /AuthKeyUnregistered|auth.*key/i,
      text: 'Сессия аккаунта слетела',
      action: 'Нужна повторная авторизация — запустите auth_sessions.py на сервере' },
    { pattern: /PeerFlood/i,
      text: 'Telegram ограничил отправку новым пользователям',
      action: 'Подождите несколько часов, ограничение снимется автоматически' },
    { pattern: /UserBannedInChannel/i,
      text: 'Аккаунту запрещено писать в группы',
      action: 'Подождите или используйте другой аккаунт' },
    { pattern: /ChatWriteForbidden/i,
      text: 'Нет прав на отправку сообщений в этот чат',
      action: 'Проверьте, что аккаунт является участником чата и имеет права' },
    { pattern: /Cannot resolve entity|Could not find/i,
      text: 'Не удалось найти чат или пользователя',
      action: 'Проверьте правильность ID чата или username' },
    { pattern: /Connection.*reset|Network.*unreachable|Connection.*refused/i,
      text: 'Потеря связи с Telegram',
      action: 'Обычно восстанавливается автоматически через несколько секунд' },
    { pattern: /timeout|timed?\s*out/i,
      text: 'Превышено время ожидания',
      action: 'Попробуйте повторить операцию или перезапустите платформу' },
    { pattern: /too many errors/i,
      text: 'Слишком много ошибок подряд — аккаунт отключён',
      action: 'Нажмите "Сбросить ошибки" на карточке аккаунта' },
    { pattern: /PersistentTimestamp/i,
      text: 'Ошибка синхронизации сессии',
      action: 'Перезапустите платформу — обычно помогает' },
];

function translateError(rawError) {
    if (!rawError) return null;
    for (const rule of ERROR_TRANSLATIONS) {
        if (rule.pattern.test(rawError)) {
            return { text: rule.text, action: rule.action, raw: rawError };
        }
    }
    return { text: rawError, action: 'Обратитесь к администратору', raw: rawError };
}

const STATUS_NAMES = {
    healthy: 'Работает',
    flood_wait: 'Ожидание',
    error: 'Ошибка',
    banned: 'Заблокирован',
    offline: 'Отключён',
    starting: 'Запускается',
};

const SERVICE_NAMES = {
    create_chat: 'Создание чатов',
    send_text: 'Отправка текста',
    send_media: 'Отправка медиа',
    leave_chat: 'Выход из чатов',
};

const SERVICE_PORTS = {
    create_chat: 5021,
    send_text: 5022,
    send_media: 5023,
    leave_chat: 5024,
};

/* ========== HELPERS ========== */

function esc(s) {
    const d = document.createElement('div');
    d.appendChild(document.createTextNode(s || ''));
    return d.innerHTML;
}

function fmtTime(ts) {
    if (!ts) return '-';
    const d = new Date(ts * 1000);
    return d.toLocaleString('ru-RU', {
        day: '2-digit', month: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
}

function fmtAgo(ts) {
    if (!ts) return 'никогда';
    const secs = Math.floor(Date.now() / 1000 - ts);
    if (secs < 0) return 'только что';
    if (secs < 60) return secs + ' сек назад';
    if (secs < 3600) return Math.floor(secs / 60) + ' мин назад';
    if (secs < 86400) return Math.floor(secs / 3600) + ' ч назад';
    return Math.floor(secs / 86400) + ' дн назад';
}

function statusClass(status) {
    if (status === 'healthy') return 'healthy';
    if (status === 'flood_wait') return 'flood';
    if (status === 'error') return 'error';
    if (status === 'banned') return 'banned';
    return 'offline';
}

function statusRu(status) {
    return STATUS_NAMES[status] || status;
}

function opStatusRu(status) {
    if (status === 'ok') return 'Успешно';
    if (status === 'error') return 'Ошибка';
    if (status === 'flood_wait') return 'Ожидание';
    if (status === 'banned') return 'Блокировка';
    return status;
}

/* ========== NOTIFICATIONS ========== */

let _prevNotifications = '';

function updateNotifications(accounts) {
    const problems = [];
    for (const acc of accounts) {
        if (acc.status === 'banned') {
            const err = translateError(acc.last_error);
            problems.push({
                level: 'critical',
                title: `Аккаунт ${acc.account_name} заблокирован!`,
                detail: err ? err.action : '',
                bridgeName: acc.name,
            });
        } else if (acc.status === 'error') {
            const err = translateError(acc.last_error);
            problems.push({
                level: 'error',
                title: `Ошибка аккаунта ${acc.account_name} (${acc.service})`,
                detail: err ? `${err.text}. ${err.action}` : acc.last_error,
                bridgeName: acc.name,
            });
        } else if (acc.status === 'flood_wait' && acc.flood_remaining > 60) {
            problems.push({
                level: 'warning',
                title: `Аккаунт ${acc.account_name} (${acc.service}) — ожидание ${acc.flood_remaining} сек`,
                detail: 'Telegram ограничил запросы. Аккаунт восстановится автоматически.',
                bridgeName: acc.name,
            });
        }
    }

    const container = document.getElementById('notifications');
    if (problems.length === 0) {
        container.innerHTML = '';
        _prevNotifications = '';
        return;
    }

    let html = '';
    for (const p of problems) {
        const btnHtml = p.level === 'error'
            ? `<button onclick="ctrlAccount('${esc(p.bridgeName)}','reset_errors')" class="btn btn-sm btn-green">Сбросить ошибки</button>`
            : '';
        html += `
        <div class="notification notification-${p.level}">
            <div class="notification-content">
                <strong>${esc(p.title)}</strong>
                <span class="notification-detail">${esc(p.detail)}</span>
            </div>
            ${btnHtml}
        </div>`;
    }

    if (html !== _prevNotifications) {
        container.innerHTML = html;
        _prevNotifications = html;
    }
}

/* ========== SERVICES ========== */

function refreshServices() {
    fetch('/api/services')
        .then(r => r.json())
        .then(data => {
            const row = document.getElementById('services-row');
            let html = '';
            for (const [key, svc] of Object.entries(data.services)) {
                const ok = svc.status === 'ok';
                const cls = ok ? 'service-ok' : 'service-down';
                const icon = ok ? '&#10003;' : '&#10007;';
                const statusText = ok
                    ? `${svc.healthy}/${svc.total} аккаунтов`
                    : 'Не работает!';
                html += `
                <div class="service-card ${cls}">
                    <div class="service-icon">${icon}</div>
                    <div class="service-name">${esc(SERVICE_NAMES[key] || key)}</div>
                    <div class="service-port">порт ${SERVICE_PORTS[key] || '?'}</div>
                    <div class="service-status">${statusText}</div>
                </div>`;
            }
            row.innerHTML = html;
        })
        .catch(() => {});
}

/* ========== SUMMARY ========== */

function refreshSummary() {
    fetch('/api/status')
        .then(r => r.json())
        .then(data => {
            document.getElementById('s-healthy').textContent =
                data.healthy_bridges + '/' + data.total_bridges;
            document.getElementById('s-chats').textContent = data.active_chats;
            document.getElementById('s-ops').textContent = data.total_operations;
            document.getElementById('s-errors').textContent = data.total_errors;
            document.getElementById('s-failovers').textContent = data.total_failovers;

            const errEl = document.getElementById('s-errors');
            errEl.className = 'summary-value' + (data.total_errors > 0 ? ' val-red' : '');
        })
        .catch(() => {});
}

/* ========== LOAD DISTRIBUTION ========== */

function refreshLoad() {
    fetch('/api/load')
        .then(r => r.json())
        .then(data => {
            const section = document.getElementById('load-section');
            const load = data.load;
            const values = Object.values(load);
            const maxVal = Math.max(...values, 1);
            const total = values.reduce((a, b) => a + b, 0);

            let html = '<div class="load-total">Всего активных чатов: <strong>' + total + '</strong></div>';
            html += '<div class="load-bars">';
            for (const [acc, count] of Object.entries(load)) {
                const pct = Math.round((count / maxVal) * 100);
                const sharePct = total > 0 ? Math.round((count / total) * 100) : 0;
                html += `
                <div class="load-row">
                    <span class="load-name">${esc(acc)}</span>
                    <div class="load-bar-bg">
                        <div class="load-bar-fill" style="width:${pct}%"></div>
                    </div>
                    <span class="load-count">${count} чатов (${sharePct}%)</span>
                </div>`;
            }
            html += '</div>';
            section.innerHTML = html;
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

            updateNotifications(data.accounts);

            for (const acc of data.accounts) {
                const cls = statusClass(acc.status);
                let errorHtml = '';

                if (acc.last_error) {
                    const err = translateError(acc.last_error);
                    errorHtml = `
                    <div class="ac-error">
                        <div class="ac-error-text">${esc(err.text)}</div>
                        <div class="ac-error-action">${esc(err.action)}</div>
                        <div class="ac-error-raw" title="${esc(err.raw)}">${esc(err.raw.substring(0, 80))}</div>
                    </div>`;
                }

                const floodHtml = acc.flood_remaining > 0
                    ? `<div class="ac-row ac-row-warn"><span class="label">Ожидание</span><span>${acc.flood_remaining} сек</span></div>`
                    : '';

                html += `
                <div class="account-card ${cls}">
                    <div class="ac-header">
                        <span class="dot ${cls}"></span>
                        <span class="name">${esc(acc.account_name)}<span class="muted"> : ${esc(acc.service)}</span></span>
                        <span class="badge ${cls}">${esc(statusRu(acc.status))}</span>
                    </div>
                    <div class="ac-body">
                        <div class="ac-row"><span class="label">Username</span><span>@${esc(acc.self_username || '-')}</span></div>
                        <div class="ac-row"><span class="label">Приоритет</span><span>${acc.priority}</span></div>
                        <div class="ac-row"><span class="label">Кэш</span><span>${acc.cache_size} записей</span></div>
                        <div class="ac-row"><span class="label">Операций</span><span>${acc.operations_count}</span></div>
                        <div class="ac-row"><span class="label">Ошибок</span><span>${acc.error_count}</span></div>
                        <div class="ac-row"><span class="label">Последняя активность</span><span>${fmtAgo(acc.last_active)}</span></div>
                        ${floodHtml}
                    </div>
                    ${errorHtml}
                    <div class="ac-controls">
                        <button onclick="ctrlAccount('${esc(acc.name)}','reload_cache')" class="btn btn-sm btn-blue" title="Перезагрузить кэш диалогов">Обновить кэш</button>
                        <button onclick="ctrlAccount('${esc(acc.name)}','reset_errors')" class="btn btn-sm btn-green" title="Сбросить счётчик ошибок и вернуть статус">Сбросить ошибки</button>
                        <button onclick="ctrlAccount('${esc(acc.name)}','clear_flood')" class="btn btn-sm" title="Принудительно снять ожидание FloodWait">Снять ожидание</button>
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
            const err = translateError(data.error);
            alert('Ошибка: ' + (err ? err.text : data.error));
        }
    })
    .catch(e => alert('Не удалось выполнить: ' + e));
}

/* ========== RESTART ========== */

function restartPlatform() {
    if (!confirm('Вы уверены? Платформа будет перезапущена.\nВсе сервисы будут недоступны ~30 секунд.')) {
        return;
    }
    fetch('/api/control', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: 'restart'}),
    })
    .then(() => {
        document.body.innerHTML = '<div style="text-align:center;padding:100px;color:#c9d1d9;font-size:1.2rem;">' +
            '<h2>Платформа перезапускается...</h2>' +
            '<p>Страница обновится автоматически через 40 секунд</p>' +
            '<p style="color:#8b949e;margin-top:20px;">Если страница не загрузится — обновите вручную</p></div>';
        setTimeout(() => location.reload(), 40000);
    })
    .catch(e => alert('Ошибка перезапуска: ' + e));
}

/* ========== CHATS ========== */

function refreshChats() {
    fetch('/api/chats?limit=200')
        .then(r => r.json())
        .then(data => {
            const tbody = document.getElementById('chats-tbody');
            let html = '';
            for (const c of data.chats) {
                const statusText = c.status === 'active' ? 'Активен' : 'Покинут';
                const cls = c.status === 'active' ? 'status-active' : 'status-left';
                html += `<tr>
                    <td>${esc(c.chat_id)}</td>
                    <td>${esc(c.title)}</td>
                    <td>${esc(c.account_name)}</td>
                    <td>${fmtTime(c.created_at)}</td>
                    <td class="${cls}">${statusText}</td>
                </tr>`;
            }
            tbody.innerHTML = html || '<tr><td colspan="5" class="empty-row">Чатов пока нет</td></tr>';
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

                const detail = op.detail ? translateError(op.detail) : null;
                const detailText = detail ? detail.text : (op.detail || '');

                html += `<tr>
                    <td>${fmtTime(op.ts)}</td>
                    <td>${esc(op.account_name)}</td>
                    <td>${esc(op.chat_id)}</td>
                    <td>${esc(SERVICE_NAMES[op.operation] || op.operation)}</td>
                    <td class="${cls}">${opStatusRu(op.status)}</td>
                    <td class="detail" title="${esc(op.detail || '')}">${esc(detailText.substring(0, 60))}</td>
                </tr>`;
            }
            tbody.innerHTML = html || '<tr><td colspan="6" class="empty-row">Операций пока нет</td></tr>';
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
                const reason = fo.reason ? translateError(fo.reason) : null;
                const reasonText = reason ? reason.text : (fo.reason || '');
                html += `<tr>
                    <td>${fmtTime(fo.ts)}</td>
                    <td>${esc(fo.chat_id)}</td>
                    <td>${esc(fo.from_account)}</td>
                    <td>${esc(fo.to_account)}</td>
                    <td class="detail" title="${esc(fo.reason || '')}">${esc(reasonText.substring(0, 60))}</td>
                </tr>`;
            }
            tbody.innerHTML = html || '<tr><td colspan="5" class="empty-row">Переключений пока не было</td></tr>';
        })
        .catch(() => {});
}

/* ========== LOGS ========== */

function refreshLogs() {
    fetch('/api/logs?n=80')
        .then(r => r.json())
        .then(data => {
            _allLogs = data.logs || [];
            renderLogs(_allLogs);
        })
        .catch(() => {});
}

function renderLogs(lines) {
    const wrap = document.getElementById('logs-wrap');
    if (lines.length === 0) {
        wrap.innerHTML = '<div class="empty-row">Логов пока нет</div>';
        return;
    }
    let html = '';
    for (const line of lines) {
        let cls = '';
        if (/ERROR/i.test(line)) cls = 'log-error';
        else if (/WARNING/i.test(line)) cls = 'log-warn';
        else if (/INFO/i.test(line)) cls = 'log-info';
        html += `<div class="log-line ${cls}">${esc(line)}</div>`;
    }
    wrap.innerHTML = html;
    wrap.scrollTop = wrap.scrollHeight;
}

function filterLogs(query) {
    if (!query) {
        renderLogs(_allLogs);
        return;
    }
    const q = query.toLowerCase();
    renderLogs(_allLogs.filter(line => line.toLowerCase().includes(q)));
}

/* ========== SEARCH / FILTER ========== */

function filterTable(tbodyId, query) {
    const tbody = document.getElementById(tbodyId);
    const rows = tbody.querySelectorAll('tr');
    const q = query.toLowerCase();
    for (const row of rows) {
        if (!q) {
            row.style.display = '';
            continue;
        }
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(q) ? '' : 'none';
    }
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
            // load logs on first tab click
            if (btn.dataset.tab === 'logs' && _allLogs.length === 0) {
                refreshLogs();
            }
        });
    });
}

/* ========== REFRESH ALL ========== */

function refreshAll() {
    refreshServices();
    refreshSummary();
    refreshLoad();
    refreshAccounts();
    refreshChats();
    refreshOperations();
    refreshFailovers();
    document.getElementById('last-update').textContent =
        'Обновлено: ' + new Date().toLocaleTimeString('ru-RU');
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
