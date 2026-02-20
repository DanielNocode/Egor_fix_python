/* ========== Telethon Monitor - Frontend ========== */

let _logData = [];
let _autoRefreshTimer = null;

/* ========== STATUS ========== */

function refreshStatus() {
    fetch('/api/status')
        .then(r => r.json())
        .then(data => {
            for (const key of ['send_text', 'send_media']) {
                const svc = data[key];
                if (!svc) continue;

                const dot = document.getElementById('dot-' + key);
                const state = (svc.systemd && svc.systemd.state) || 'unknown';
                dot.className = 'status-dot';
                if (state === 'active') dot.classList.add('running');
                else if (state === 'inactive' || state === 'failed') dot.classList.add('stopped');
                else if (state === 'activating' || state === 'restarting') dot.classList.add('restarting');

                setText('state-' + key, state);
                setText('uptime-' + key, (svc.systemd && svc.systemd.uptime) || '-');
                setText('mem-' + key, (svc.systemd && svc.systemd.memory) || '-');
                setText('cpu-' + key, (svc.systemd && svc.systemd.cpu) || '-');

                if (svc.stats) {
                    setText('cache-' + key, svc.stats.cache_size + ' entities');
                    setText('errors-' + key, svc.stats.error_count);
                } else {
                    setText('cache-' + key, '-');
                    setText('errors-' + key, '-');
                }

                // Alert
                if (svc.alert) {
                    showAlert(key + ' health check failed ' + svc.fail_streak + ' times in a row!');
                }
            }
            document.getElementById('last-update').textContent = 'Updated: ' + new Date().toLocaleTimeString();
        })
        .catch(err => {
            console.error('Status fetch error:', err);
        });
}

function showAlert(msg) {
    const bar = document.getElementById('alerts-bar');
    bar.textContent = 'ALERT: ' + msg;
    bar.classList.remove('hidden');
}

function hideAlerts() {
    document.getElementById('alerts-bar').classList.add('hidden');
}

function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val !== null && val !== undefined ? val : '-';
}

/* ========== SERVICE CONTROL ========== */

function controlService(service, action) {
    if (action === 'stop' && !confirm('Stop ' + service + '?')) return;

    fetch('/api/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ service: service, action: action })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'ok') {
            setTimeout(refreshStatus, 2000);
        } else {
            alert('Error: ' + (data.error || JSON.stringify(data)));
        }
    })
    .catch(err => alert('Request failed: ' + err));
}

/* ========== CLEAR FLOOD WAIT ========== */

function clearFloodWait() {
    if (!confirm(
        'This will STOP both services for 5 minutes, then restart them.\n' +
        'Continue?'
    )) return;

    fetch('/api/clear_flood_wait', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
    })
    .then(r => r.json())
    .then(data => {
        alert(data.message || 'Started');
        setTimeout(refreshStatus, 3000);
    })
    .catch(err => alert('Failed: ' + err));
}

/* ========== DIAGNOSTICS ========== */

function runDiagnostics() {
    const section = document.getElementById('diagnostics-section');
    const output = document.getElementById('diagnostics-output');
    section.classList.remove('hidden');
    output.innerHTML = '<span class="muted">Running diagnostics...</span>';

    fetch('/api/diagnostics', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            let html = '';
            for (const item of data.report) {
                const cls = item.ok ? 'ok' : 'fail';
                const icon = item.ok ? '&#10004;' : '&#10008;';
                html += '<div class="diag-item ' + cls + '">';
                html += '<div class="diag-title">' + icon + ' ' + escapeHtml(item.check) + '</div>';
                html += '<div class="diag-output">' + escapeHtml(item.output) + '</div>';
                html += '</div>';
            }
            output.innerHTML = html;
        })
        .catch(err => {
            output.innerHTML = '<span class="log-line error">Diagnostics failed: ' + escapeHtml(String(err)) + '</span>';
        });
}

/* ========== LOGS ========== */

function fetchLogs() {
    const service = document.getElementById('log-service').value;
    const mode = document.getElementById('log-mode').value;
    const search = document.getElementById('log-search').value;
    const dateFrom = document.getElementById('log-date-from').value;
    const dateTo = document.getElementById('log-date-to').value;
    const errorType = document.getElementById('log-error-type').value;

    const params = new URLSearchParams();
    params.set('service', service);
    params.set('lines', '200');
    params.set('errors_only', mode === 'errors' ? 'true' : 'false');
    if (search) params.set('search', search);
    if (dateFrom) params.set('since', dateFrom);
    if (dateTo) params.set('until', dateTo + ' 23:59:59');

    fetch('/api/logs?' + params.toString())
        .then(r => r.json())
        .then(data => {
            let logs = data.logs || [];

            // Client-side filter by error type
            if (errorType) {
                logs = logs.filter(l => l.line.includes(errorType));
            }

            _logData = logs;
            renderLogs(logs);
        })
        .catch(err => {
            document.getElementById('log-viewer').innerHTML =
                '<span class="log-line error">Failed to fetch logs: ' + escapeHtml(String(err)) + '</span>';
        });
}

function renderLogs(logs) {
    const viewer = document.getElementById('log-viewer');
    if (!logs.length) {
        viewer.innerHTML = '<span class="muted">No logs found</span>';
        return;
    }
    let html = '';
    for (const entry of logs) {
        let cls = '';
        const line = entry.line;
        if (/\bERROR\b/i.test(line) || /\bfailed\b/i.test(line)) cls = 'error';
        else if (/\bWARNING\b/i.test(line) || /\bFloodWait\b/i.test(line)) cls = 'warning';

        const tag = entry.service === 'send_media' ? 'media' : 'text';
        html += '<div class="log-line ' + cls + '">';
        html += '<span class="svc-tag">' + tag + '</span>';
        html += escapeHtml(line);
        html += '</div>';
    }
    viewer.innerHTML = html;
    viewer.scrollTop = viewer.scrollHeight;
}

function copyLogs() {
    const text = _logData.map(l => '[' + l.service + '] ' + l.line).join('\n');
    navigator.clipboard.writeText(text).then(() => {
        alert('Logs copied to clipboard');
    }).catch(() => {
        // Fallback
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        alert('Logs copied');
    });
}

function downloadLogs() {
    const text = _logData.map(l => '[' + l.service + '] ' + l.line).join('\n');
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'telethon_logs_' + new Date().toISOString().slice(0, 10) + '.txt';
    a.click();
    URL.revokeObjectURL(url);
}

/* ========== HEALTH HISTORY ========== */

function refreshHealthHistory() {
    fetch('/api/health_history')
        .then(r => r.json())
        .then(data => {
            const container = document.getElementById('health-history');
            let html = '';
            for (const key of ['send_text', 'send_media']) {
                const checks = data[key] || [];
                const label = key === 'send_media' ? 'send_media' : 'send_text';
                html += '<div class="health-row">';
                html += '<span class="svc-label">' + label + '</span>';
                html += '<div class="health-dots">';

                // Show last 120 checks (2 hours at 1/min) or all
                const recent = checks.slice(-120);
                for (const c of recent) {
                    const cls = c.ok ? '' : 'fail';
                    const time = new Date(c.ts * 1000).toLocaleTimeString();
                    html += '<div class="health-dot ' + cls + '" title="' + time + ' — ' + (c.ok ? 'OK' : 'FAIL') + '"></div>';
                }
                if (recent.length === 0) {
                    html += '<span class="muted" style="font-size:0.75rem">No data yet</span>';
                }
                html += '</div></div>';

                // Alert indicator
                if (data.alerts && data.alerts[key]) {
                    showAlert(label + ' health check failing!');
                }
            }
            container.innerHTML = html;
        })
        .catch(() => {});
}

/* ========== AUTO REFRESH ========== */

function startAutoRefresh() {
    if (_autoRefreshTimer) clearInterval(_autoRefreshTimer);
    _autoRefreshTimer = setInterval(() => {
        refreshStatus();
        if (document.getElementById('log-auto-refresh').checked) {
            fetchLogs();
        }
        refreshHealthHistory();
    }, 30000);
}

/* ========== UTIL ========== */

function escapeHtml(str) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

/* ========== REFRESH ALL ========== */

function refreshAll() {
    hideAlerts();
    refreshStatus();
    fetchLogs();
    refreshHealthHistory();
}

/* ========== INIT ========== */
document.addEventListener('DOMContentLoaded', () => {
    refreshAll();
    startAutoRefresh();

    // Enter key in search triggers refresh
    document.getElementById('log-search').addEventListener('keydown', e => {
        if (e.key === 'Enter') fetchLogs();
    });
});
