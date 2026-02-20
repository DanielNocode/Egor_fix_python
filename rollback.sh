#!/bin/bash
# rollback.sh — Откат к старым standalone-скриптам
#
# Запуск: bash rollback.sh
#
# Что делает:
#   1. Останавливает новую платформу
#   2. Восстанавливает старые systemd-сервисы (send_text, send_media)
#   3. Запускает leave_chat через gunicorn
#   4. Проверяет что всё работает

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; }

echo -e "${YELLOW}=== ОТКАТ к старым скриптам ===${NC}"
echo ""

# Находим последний бэкап
BACKUP_DIR=$(ls -d /root/backup_* 2>/dev/null | sort | tail -1)
if [ -z "$BACKUP_DIR" ]; then
    err "Бэкап не найден в /root/backup_*"
    exit 1
fi
echo "Бэкап: ${BACKUP_DIR}"

# Находим venv
VENV=""
for candidate in "/root/venv/bin" "/root/telethon_env/bin"; do
    [ -f "${candidate}/python3" ] && VENV="$candidate" && break
done
[ -z "$VENV" ] && { err "Python venv не найден"; exit 1; }

# 1. Останавливаем новую платформу
echo ""
echo "[1/4] Останавливаем новую платформу..."
systemctl stop telethon-platform 2>/dev/null || true
systemctl disable telethon-platform 2>/dev/null || true
ok "telethon-platform остановлен"

# 2. Восстанавливаем systemd-сервисы
echo ""
echo "[2/4] Восстанавливаем старые systemd-сервисы..."
for svc in "send-text-rumyantsev.service" "send-media-rumyantsev.service"; do
    if [ -f "${BACKUP_DIR}/${svc}" ]; then
        cp "${BACKUP_DIR}/${svc}" /etc/systemd/system/
        ok "Восстановлен: ${svc}"
    else
        warn "Файл ${svc} не найден в бэкапе"
    fi
done
systemctl daemon-reload
systemctl enable send-text-rumyantsev.service 2>/dev/null || true
systemctl enable send-media-rumyantsev.service 2>/dev/null || true
systemctl start send-text-rumyantsev.service 2>/dev/null || true
systemctl start send-media-rumyantsev.service 2>/dev/null || true

# 3. Запускаем leave_chat через gunicorn
echo ""
echo "[3/4] Запускаем leave_chat (gunicorn)..."
cd /root
nohup ${VENV}/gunicorn --bind 0.0.0.0:5024 -k gevent leave_chat_rumyantsev_webhook:app > /dev/null 2>&1 &
sleep 2

# 4. Проверяем
echo ""
echo "[4/4] Проверяем..."
sleep 3
for port in 5022 5023 5024; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${port}/health" 2>/dev/null || echo "000")
    if [ "$CODE" = "200" ]; then
        ok "localhost:${port}/health -> 200"
    else
        warn "localhost:${port}/health -> ${CODE}"
    fi
done

echo ""
echo -e "${GREEN}Откат завершён. Старые скрипты восстановлены.${NC}"
