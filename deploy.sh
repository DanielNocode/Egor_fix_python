#!/bin/bash
# deploy.sh — Полный деплой платформы Rumyantsev Telethon
#
# Запуск на сервере:
#   cd /root/Egor_fix_python
#   bash deploy.sh
#
# Этапы:
#   0. Проверка окружения
#   1. Бэкап
#   2. Создание сессий (если есть недостающие — ИНТЕРАКТИВНО)
#   3. Остановка старых процессов на портах 5021-5024, 5099
#   4. Создание systemd-сервиса
#   5. Запуск платформы
#   6. Health-check
#   7. Включение автозапуска

set -e

# ===== НАСТРОЙКИ ==============================================================

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK_DIR="/root"
BACKUP_DIR="/root/backup_$(date +%Y%m%d_%H%M%S)"
SERVICE_NAME="telethon-platform"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

PORTS=(5021 5022 5023 5024 5099)

OLD_SERVICES=("send-text-rumyantsev.service" "send-media-rumyantsev.service" "telethon-monitor.service")

# ===== ЦВЕТА ==================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; }
info() { echo -e "${BLUE}[*]${NC} $1"; }
step() { echo -e "\n${BLUE}========== $1 ==========${NC}"; }

# ===== ШАГ 0: ПРОВЕРКА ОКРУЖЕНИЯ =============================================

step "ШАГ 0: Проверка окружения"

# Находим Python venv
VENV=""
for candidate in "/root/venv/bin" "/root/telethon_env/bin"; do
    if [ -f "${candidate}/python3" ]; then
        VENV="$candidate"
        break
    fi
done

if [ -z "$VENV" ]; then
    err "Python venv не найден ни в /root/venv, ни в /root/telethon_env"
    err "Создайте: python3 -m venv /root/venv && /root/venv/bin/pip install telethon flask werkzeug"
    exit 1
fi

PYTHON="${VENV}/python3"
ok "Python: ${PYTHON} ($($PYTHON --version 2>&1))"

# Проверяем зависимости
$PYTHON -c "import telethon" 2>/dev/null || { err "telethon не установлен"; exit 1; }
$PYTHON -c "import flask" 2>/dev/null || { err "flask не установлен"; exit 1; }
$PYTHON -c "import werkzeug" 2>/dev/null || { err "werkzeug не установлен"; exit 1; }
ok "Зависимости: telethon, flask, werkzeug"

# Проверяем app.py
if [ ! -f "${REPO_DIR}/app.py" ]; then
    err "app.py не найден в ${REPO_DIR}. Запускайте из папки репо."
    exit 1
fi
ok "Репо: ${REPO_DIR}"

# Сессии основного аккаунта (критичны)
MAIN_SESSIONS=("rumyantsev_create_chat" "rumyantsev_send_text" "rumuantsev_media" "rumyantsev_leave")
for s in "${MAIN_SESSIONS[@]}"; do
    if [ ! -f "${WORK_DIR}/${s}.session" ]; then
        err "Сессия основного аккаунта не найдена: ${WORK_DIR}/${s}.session"
        err "Без неё деплой невозможен."
        exit 1
    fi
done
ok "Сессии основного аккаунта: все 4 на месте"

# ===== ШАГ 1: БЭКАП ===========================================================

step "ШАГ 1: Бэкап"

mkdir -p "${BACKUP_DIR}"
cp ${WORK_DIR}/*rumyantsev*.py "${BACKUP_DIR}/" 2>/dev/null || true
cp ${WORK_DIR}/*rumyantsev*.session "${BACKUP_DIR}/" 2>/dev/null || true
cp ${WORK_DIR}/rum_*.session "${BACKUP_DIR}/" 2>/dev/null || true
cp ${WORK_DIR}/rumuantsev_media*.session "${BACKUP_DIR}/" 2>/dev/null || true
for svc in "${OLD_SERVICES[@]}"; do
    cp "/etc/systemd/system/${svc}" "${BACKUP_DIR}/" 2>/dev/null || true
done

BACKUP_COUNT=$(ls "${BACKUP_DIR}/" 2>/dev/null | wc -l)
ok "Бэкап: ${BACKUP_DIR} (${BACKUP_COUNT} файлов)"

# ===== ШАГ 2: СОЗДАНИЕ НЕДОСТАЮЩИХ СЕССИЙ =====================================

step "ШАГ 2: Проверка backup-сессий"

BACKUP_SESSIONS=("rum_send_text_2" "rum_media_2" "rum_leave_2"
                  "rum_send_text_3" "rum_media_3" "rum_leave_3"
                  "rum_send_text_4" "rum_media_4" "rum_leave_4")
MISSING=()
for s in "${BACKUP_SESSIONS[@]}"; do
    if [ ! -f "${WORK_DIR}/${s}.session" ]; then
        MISSING+=("$s")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    warn "Недостаёт ${#MISSING[@]} backup-сессий:"
    for s in "${MISSING[@]}"; do
        echo "  - ${s}.session"
    done
    echo ""
    echo -e "${YELLOW}Без них failover работать НЕ БУДЕТ (только основной аккаунт).${NC}"
    echo ""
    read -p "Создать сейчас? Понадобятся коды из Telegram. (y/n): " CREATE
    if [ "$CREATE" = "y" ]; then
        cd "${WORK_DIR}"
        $PYTHON "${REPO_DIR}/auth_sessions.py"
        cd "${REPO_DIR}"
    else
        warn "Пропускаем. Failover будет ограничен."
    fi
else
    ok "Все backup-сессии на месте"
fi

# ===== ШАГ 3: ОСТАНОВКА СТАРЫХ ПРОЦЕССОВ =====================================

step "ШАГ 3: Остановка старых процессов"

# systemd-сервисы
for svc in "${OLD_SERVICES[@]}"; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        systemctl stop "$svc" && systemctl disable "$svc"
        ok "Остановлен: ${svc}"
    else
        info "Уже не запущен: ${svc}"
    fi
done

# Orphaned процессы на наших портах
for port in "${PORTS[@]}"; do
    PIDS=$(ss -tlnp 2>/dev/null | grep ":${port} " | grep -oP 'pid=\K[0-9]+' | sort -u | tr '\n' ' ')
    if [ -n "$PIDS" ]; then
        warn "Порт ${port} занят PID: ${PIDS}"
        for pid in $PIDS; do
            kill "$pid" 2>/dev/null || true
        done
        sleep 2
        # Если ещё занят — kill -9
        PIDS2=$(ss -tlnp 2>/dev/null | grep ":${port} " | grep -oP 'pid=\K[0-9]+' | sort -u | tr '\n' ' ')
        if [ -n "$PIDS2" ]; then
            for pid in $PIDS2; do
                kill -9 "$pid" 2>/dev/null || true
            done
            sleep 1
        fi
    fi
done

# Проверяем
echo ""
ALL_FREE=1
for port in "${PORTS[@]}"; do
    if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
        err "Порт ${port} ВСЁ ЕЩЁ ЗАНЯТ!"
        ALL_FREE=0
    else
        ok "Порт ${port} свободен"
    fi
done

if [ $ALL_FREE -eq 0 ]; then
    read -p "Не все порты свободны. Продолжить? (y/n): " CONT
    [ "$CONT" != "y" ] && exit 1
fi

# ===== ШАГ 4: SYSTEMD-СЕРВИС =================================================

step "ШАГ 4: Создание systemd-сервиса"

cat > "${SERVICE_FILE}" << UNITEOF
[Unit]
Description=Telethon Unified Platform (Rumyantsev)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${WORK_DIR}
ExecStart=${PYTHON} ${REPO_DIR}/app.py
Restart=always
RestartSec=10
KillMode=mixed
TimeoutStopSec=30

Environment=REGISTRY_DB=${WORK_DIR}/chat_registry.db
Environment=MONITOR_USER=admin
Environment=MONITOR_PASS=telethon2026
Environment=LOG_LEVEL=INFO

StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
UNITEOF

systemctl daemon-reload
ok "Сервис создан: ${SERVICE_FILE}"

# ===== ШАГ 5: ЗАПУСК ==========================================================

step "ШАГ 5: Запуск платформы"

systemctl start "${SERVICE_NAME}"
info "Ожидаем запуска (прогрев кэша ~30-60 сек)..."

WAIT=0
READY=0
while [ $WAIT -lt 90 ]; do
    sleep 5
    WAIT=$((WAIT + 5))
    LISTENING=$(ss -tlnp 2>/dev/null | grep -cE ':(5021|5022|5023|5024) ')
    echo -ne "\r  ${WAIT}s... порты: ${LISTENING}/4"
    if [ "$LISTENING" -ge 4 ]; then
        READY=1
        break
    fi
done
echo ""

if [ $READY -eq 0 ]; then
    err "Платформа не стартовала за 90 секунд!"
    echo ""
    journalctl -u "${SERVICE_NAME}" --no-pager -n 40
    echo ""
    err "Логи: journalctl -u ${SERVICE_NAME} -f"
    exit 1
fi

ok "Платформа запущена!"

# ===== ШАГ 6: ПРОВЕРКА ========================================================

step "ШАГ 6: Health-check"

echo ""
PASSED=0

for port in 5022 5023 5024; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${port}/health" 2>/dev/null || echo "000")
    if [ "$CODE" = "200" ]; then
        ok "localhost:${port}/health -> 200"
        PASSED=$((PASSED + 1))
    else
        err "localhost:${port}/health -> ${CODE}"
    fi
done

# Dashboard
DASH=$(curl -s -o /dev/null -w "%{http_code}" -u admin:telethon2026 "http://localhost:5099/" 2>/dev/null || echo "000")
if [ "$DASH" = "200" ] || [ "$DASH" = "302" ]; then
    ok "localhost:5099 (dashboard) -> ${DASH}"
    PASSED=$((PASSED + 1))
else
    warn "localhost:5099 (dashboard) -> ${DASH}"
fi

# create_chat
if ss -tlnp 2>/dev/null | grep -q ":5021 "; then
    ok "localhost:5021 (create_chat) -> порт слушает"
    PASSED=$((PASSED + 1))
else
    err "localhost:5021 (create_chat) -> порт не слушает"
fi

echo ""

# ===== ШАГ 7: АВТОЗАПУСК =====================================================

if [ $PASSED -ge 3 ]; then
    step "ШАГ 7: Автозапуск"
    systemctl enable "${SERVICE_NAME}"
    ok "Автозапуск включён"
else
    warn "Только ${PASSED}/5 проверок прошли. Автозапуск НЕ включён."
    warn "Исправьте и запустите: systemctl enable ${SERVICE_NAME}"
fi

# ===== ИТОГО ==================================================================

step "ГОТОВО"

echo ""
echo -e "${GREEN}Платформа развёрнута!${NC}"
echo ""
echo "  Сервис:    systemctl status ${SERVICE_NAME}"
echo "  Логи:      journalctl -u ${SERVICE_NAME} -f"
echo "  Дашборд:   http://localhost:5099 (admin/telethon2026)"
echo "  Бэкап:     ${BACKUP_DIR}"
echo ""
echo "  Порты: 5021 (create_chat) | 5022 (send_text) | 5023 (send_media)"
echo "         5024 (leave_chat)  | 5099 (dashboard)"
echo ""

# Предупреждение о параллельных старых скриптах
for port in 5025 5028 5029 5030; do
    if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
        warn "Старый скрипт на порту ${port} продолжает работать (не трогаем до перенастройки n8n)"
    fi
done

echo ""
echo "Откат:"
echo "  bash ${REPO_DIR}/rollback.sh"
echo ""
