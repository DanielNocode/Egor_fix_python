/* ========== Панель управления Telethon ========== */

let _autoTimer = null;
let _allLogs = [];

const PAGE_SIZE = 20;
let _allChats = [];
let _allFos = [];
let _allFailed = [];
let _shownChats = PAGE_SIZE;
let _shownFos = PAGE_SIZE;
let _shownLogs = PAGE_SIZE;
let _shownFailed = PAGE_SIZE;

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

            const retriesEl = document.getElementById('s-retries');
            retriesEl.textContent = data.pending_retries || 0;
            retriesEl.className = 'summary-value' + ((data.pending_retries || 0) > 0 ? ' val-red' : '');

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

/* ========== SHOW MORE HELPERS ========== */

function showMoreBar(total, shown, showMoreFn, collapseFn) {
    if (total === 0) return '';
    if (total <= PAGE_SIZE) return '';
    if (shown < total) {
        const remaining = total - shown;
        const next = Math.min(PAGE_SIZE, remaining);
        return `<div class="show-more-bar">
            <span class="muted">Показано ${shown} из ${total}</span>
            <button class="btn btn-sm btn-show-more" onclick="${showMoreFn}()">Показать ещё ${next}</button>
            <button class="btn btn-sm" onclick="${showMoreFn}(true)">Показать все</button>
        </div>`;
    }
    return `<div class="show-more-bar">
        <span class="muted">Показаны все ${total}</span>
        <button class="btn btn-sm" onclick="${collapseFn}()">Свернуть</button>
    </div>`;
}

/* ========== CHATS ========== */

function refreshChats() {
    fetch('/api/chats?limit=500')
        .then(r => r.json())
        .then(data => {
            _allChats = data.chats || [];
            _shownChats = PAGE_SIZE;
            renderChats();
        })
        .catch(() => {});
}

function renderChats() {
    const tbody = document.getElementById('chats-tbody');
    const showing = _allChats.slice(0, _shownChats);
    let html = '';
    for (const c of showing) {
        const statusText = c.status === 'active' ? 'Активен' : 'Покинут';
        const cls = c.status === 'active' ? 'status-active' : 'status-left';
        html += `<tr class="clickable-row" onclick="openChatOps('${esc(c.chat_id)}', '${esc(c.title || c.chat_id)}')">
            <td>${esc(c.chat_id)}</td>
            <td>${esc(c.title)}</td>
            <td>${esc(c.account_name)}</td>
            <td>${fmtTime(c.created_at)}</td>
            <td class="${cls}">${statusText}</td>
        </tr>`;
    }
    tbody.innerHTML = html || '<tr><td colspan="5" class="empty-row">Чатов пока нет</td></tr>';
    document.getElementById('chats-more').innerHTML =
        showMoreBar(_allChats.length, _shownChats, 'showMoreChats', 'collapseChats');
}

function showMoreChats(all) {
    _shownChats = all ? _allChats.length : _shownChats + PAGE_SIZE;
    renderChats();
}
function collapseChats() { _shownChats = PAGE_SIZE; renderChats(); }

/* ========== CHAT OPERATIONS MODAL ========== */

let _chatOpsOpen = false;

function openChatOps(chatId, chatTitle) {
    _chatOpsOpen = true;
    document.getElementById('chat-ops-title').textContent =
        'Операции: ' + (chatTitle || chatId);
    document.getElementById('chat-ops-loading').style.display = 'block';
    document.getElementById('chat-ops-table-wrap').style.display = 'none';
    document.getElementById('chat-ops-empty').style.display = 'none';
    document.getElementById('chat-ops-modal').style.display = 'flex';

    fetch('/api/operations_by_chat?chat_id=' + encodeURIComponent(chatId) + '&limit=200')
        .then(r => r.json())
        .then(data => {
            const ops = data.operations || [];
            document.getElementById('chat-ops-loading').style.display = 'none';

            if (ops.length === 0) {
                document.getElementById('chat-ops-empty').style.display = 'block';
                return;
            }

            const tbody = document.getElementById('chat-ops-tbody');
            let html = '';
            for (const op of ops) {
                let cls = '';
                if (op.status === 'ok') cls = 'status-ok';
                else if (op.status === 'error' || op.status === 'banned') cls = 'status-error';
                else if (op.status === 'flood_wait') cls = 'status-flood';

                const detail = op.detail ? translateError(op.detail) : null;
                const detailText = detail ? detail.text : (op.detail || '');

                html += `<tr>
                    <td>${fmtTime(op.ts)}</td>
                    <td>${esc(op.account_name)}</td>
                    <td>${esc(SERVICE_NAMES[op.operation] || op.operation)}</td>
                    <td class="${cls}">${opStatusRu(op.status)}</td>
                    <td class="detail" title="${esc(op.detail || '')}">${esc(detailText.substring(0, 80))}</td>
                </tr>`;
            }
            tbody.innerHTML = html;
            document.getElementById('chat-ops-table-wrap').style.display = 'block';
        })
        .catch(() => {
            document.getElementById('chat-ops-loading').textContent = 'Ошибка загрузки';
        });
}

function closeChatOpsModal() {
    document.getElementById('chat-ops-modal').style.display = 'none';
    _chatOpsOpen = false;
}

/* ========== FAILOVERS ========== */

function refreshFailovers() {
    fetch('/api/failovers?limit=500')
        .then(r => r.json())
        .then(data => {
            _allFos = data.failovers || [];
            _shownFos = PAGE_SIZE;
            renderFos();
        })
        .catch(() => {});
}

function renderFos() {
    const tbody = document.getElementById('fo-tbody');
    const showing = _allFos.slice(0, _shownFos);
    let html = '';
    for (const fo of showing) {
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
    document.getElementById('fo-more').innerHTML =
        showMoreBar(_allFos.length, _shownFos, 'showMoreFos', 'collapseFos');
}

function showMoreFos(all) {
    _shownFos = all ? _allFos.length : _shownFos + PAGE_SIZE;
    renderFos();
}
function collapseFos() { _shownFos = PAGE_SIZE; renderFos(); }

/* ========== FAILED REQUESTS ========== */

const DIRECTION_NAMES = {
    inbound: 'Входящий',
    outbound: 'Исходящий',
};

const FAILED_STATUS_NAMES = {
    pending: 'Ожидает',
    retried: 'Повторён',
    resolved: 'Решён',
};

function refreshFailed() {
    fetch('/api/failed_requests?limit=500')
        .then(r => r.json())
        .then(data => {
            _allFailed = data.failed_requests || [];
            _shownFailed = PAGE_SIZE;
            renderFailed();
        })
        .catch(() => {});
}

function renderFailed() {
    const tbody = document.getElementById('failed-tbody');
    const showing = _allFailed.slice(0, _shownFailed);
    let html = '';
    for (const item of showing) {
        const err = translateError(item.error);
        const errText = err ? err.text : (item.error || '');
        const statusCls = item.status === 'pending' ? 'status-error'
            : item.status === 'retried' ? 'status-ok' : '';
        const retryInfo = item.retry_count > 0
            ? ` (${item.retry_count}x, ${item.last_retry_error ? item.last_retry_error.substring(0, 40) : ''})`
            : '';

        let actions = `<button onclick="openEditModal(${item.id})" class="btn btn-sm">Редактировать</button> `;
        if (item.status === 'pending') {
            actions += `<button onclick="retryRequest(${item.id})" class="btn btn-sm btn-blue">Повторить</button> `;
        }
        actions += `<button onclick="deleteRequest(${item.id})" class="btn btn-sm btn-red">Удалить</button>`;

        html += `<tr>
            <td>${fmtTime(item.ts)}</td>
            <td>${esc(SERVICE_NAMES[item.service] || item.service)}</td>
            <td>${esc(DIRECTION_NAMES[item.direction] || item.direction)}</td>
            <td class="detail" title="${esc(item.error || '')}">${esc(errText.substring(0, 50))}</td>
            <td>${item.retry_count}${esc(retryInfo)}</td>
            <td class="${statusCls}">${esc(FAILED_STATUS_NAMES[item.status] || item.status)}</td>
            <td class="actions-cell">${actions}</td>
        </tr>`;
    }
    tbody.innerHTML = html || '<tr><td colspan="7" class="empty-row">Неудачных запросов нет</td></tr>';
    document.getElementById('failed-more').innerHTML =
        showMoreBar(_allFailed.length, _shownFailed, 'showMoreFailed', 'collapseFailed');
}

function showMoreFailed(all) {
    _shownFailed = all ? _allFailed.length : _shownFailed + PAGE_SIZE;
    renderFailed();
}
function collapseFailed() { _shownFailed = PAGE_SIZE; renderFailed(); }

function retryRequest(id) {
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = 'Повтор...';
    fetch('/api/retry_request', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: id}),
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'ok') {
            btn.textContent = 'Готово';
            btn.className = 'btn btn-sm btn-green';
            setTimeout(refreshFailed, 1000);
        } else {
            alert('Ошибка повтора: ' + (data.error || 'unknown'));
            btn.disabled = false;
            btn.textContent = 'Повторить';
        }
    })
    .catch(e => {
        alert('Ошибка: ' + e);
        btn.disabled = false;
        btn.textContent = 'Повторить';
    });
}

function deleteRequest(id) {
    if (!confirm('Удалить этот запрос?')) return;
    fetch('/api/delete_failed', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: id}),
    })
    .then(() => refreshFailed())
    .catch(e => alert('Ошибка: ' + e));
}

let _editingRequestId = null;

function openEditModal(id) {
    const item = _allFailed.find(f => f.id === id);
    if (!item) return;
    _editingRequestId = id;

    document.getElementById('modal-service').textContent =
        SERVICE_NAMES[item.service] || item.service;
    document.getElementById('modal-direction').textContent =
        DIRECTION_NAMES[item.direction] || item.direction;
    document.getElementById('modal-endpoint').textContent =
        item.endpoint || '';
    document.getElementById('modal-title').textContent =
        'Редактирование запроса #' + id;

    const textarea = document.getElementById('modal-payload');
    try {
        const parsed = JSON.parse(item.request_payload);
        textarea.value = JSON.stringify(parsed, null, 2);
    } catch (e) {
        textarea.value = item.request_payload;
    }

    document.getElementById('modal-error').style.display = 'none';
    document.getElementById('edit-modal').style.display = 'flex';
    textarea.focus();
}

function closeEditModal() {
    document.getElementById('edit-modal').style.display = 'none';
    _editingRequestId = null;
}

function _getEditedPayload() {
    const raw = document.getElementById('modal-payload').value.trim();
    const errEl = document.getElementById('modal-error');
    try {
        JSON.parse(raw);
        errEl.style.display = 'none';
        return raw;
    } catch (e) {
        errEl.textContent = 'Невалидный JSON: ' + e.message;
        errEl.style.display = 'block';
        return null;
    }
}

function savePayload() {
    const payload = _getEditedPayload();
    if (payload === null) return;

    fetch('/api/update_failed_payload', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: _editingRequestId, payload: payload}),
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'ok') {
            closeEditModal();
            refreshFailed();
        } else {
            const errEl = document.getElementById('modal-error');
            errEl.textContent = 'Ошибка сохранения: ' + (data.error || 'unknown');
            errEl.style.display = 'block';
        }
    })
    .catch(e => {
        const errEl = document.getElementById('modal-error');
        errEl.textContent = 'Ошибка: ' + e;
        errEl.style.display = 'block';
    });
}

function saveAndRetry() {
    const payload = _getEditedPayload();
    if (payload === null) return;

    const errEl = document.getElementById('modal-error');
    errEl.style.display = 'none';

    fetch('/api/retry_request', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: _editingRequestId, payload: payload}),
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'ok') {
            closeEditModal();
            refreshFailed();
            refreshSummary();
        } else {
            errEl.textContent = 'Ошибка повтора: ' + (data.error || 'unknown');
            errEl.style.display = 'block';
        }
    })
    .catch(e => {
        errEl.textContent = 'Ошибка: ' + e;
        errEl.style.display = 'block';
    });
}

/* ========== LOGS ========== */

function refreshLogs() {
    fetch('/api/logs?n=200')
        .then(r => r.json())
        .then(data => {
            _allLogs = data.logs || [];
            _shownLogs = PAGE_SIZE;
            renderLogs();
        })
        .catch(() => {});
}

function renderLogs(filteredLines) {
    const lines = filteredLines || _allLogs;
    const wrap = document.getElementById('logs-wrap');
    if (lines.length === 0) {
        wrap.innerHTML = '<div class="empty-row">Логов пока нет</div>';
        document.getElementById('logs-more').innerHTML = '';
        return;
    }
    const showing = lines.slice(0, filteredLines ? lines.length : _shownLogs);
    let html = '';
    for (const line of showing) {
        let cls = '';
        if (/ERROR/i.test(line)) cls = 'log-error';
        else if (/WARNING/i.test(line)) cls = 'log-warn';
        else if (/INFO/i.test(line)) cls = 'log-info';
        html += `<div class="log-line ${cls}">${esc(line)}</div>`;
    }
    wrap.innerHTML = html;
    if (!filteredLines) {
        document.getElementById('logs-more').innerHTML =
            showMoreBar(_allLogs.length, _shownLogs, 'showMoreLogs', 'collapseLogs');
    } else {
        document.getElementById('logs-more').innerHTML = '';
    }
}

function showMoreLogs(all) {
    _shownLogs = all ? _allLogs.length : _shownLogs + PAGE_SIZE;
    renderLogs();
}
function collapseLogs() { _shownLogs = PAGE_SIZE; renderLogs(); }

function filterLogs(query) {
    if (!query) {
        renderLogs();
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
            // load data on first tab click
            if (btn.dataset.tab === 'logs' && _allLogs.length === 0) {
                refreshLogs();
            }
            if (btn.dataset.tab === 'failed' && _allFailed.length === 0) {
                refreshFailed();
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
    refreshFailovers();
    // Обновляем failed requests если вкладка уже загружалась
    if (_allFailed.length > 0 || document.querySelector('.tab-btn[data-tab="failed"].active')) {
        refreshFailed();
    }
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

    // Закрытие модалок по Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (_editingRequestId !== null) closeEditModal();
            if (_chatOpsOpen) closeChatOpsModal();
        }
    });
    // Закрытие по клику на оверлей
    document.getElementById('edit-modal').addEventListener('click', (e) => {
        if (e.target.id === 'edit-modal') closeEditModal();
    });
    document.getElementById('chat-ops-modal').addEventListener('click', (e) => {
        if (e.target.id === 'chat-ops-modal') closeChatOpsModal();
    });
});
