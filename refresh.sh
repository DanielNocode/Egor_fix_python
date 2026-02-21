#!/bin/bash
# refresh.sh — Обновить код и перезапустить платформу
#
# Запуск:
#   cd /root/Egor_fix_python && bash refresh.sh

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; }
info() { echo -e "${BLUE}[*]${NC} $1"; }

SERVICE_NAME="telethon-platform"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

# 1. Пуллим свежий код
info "git pull..."
cd "${REPO_DIR}"
git pull origin main
ok "Код обновлён"

# 2. Перезапускаем сервис
info "Перезапуск ${SERVICE_NAME}..."
systemctl restart "${SERVICE_NAME}"

# 3. Ждём старта
info "Ожидаем запуска..."
WAIT=0
READY=0
while [ $WAIT -lt 90 ]; do
    sleep 5
    WAIT=$((WAIT + 5))
    LISTENING=$(ss -tlnp 2>/dev/null | grep -cE ':(5021|5022|5023|5024) ' || true)
    echo -ne "\r  ${WAIT}s... порты: ${LISTENING}/4"
    if [ "$LISTENING" -ge 4 ]; then
        READY=1
        break
    fi
done
echo ""

if [ $READY -eq 0 ]; then
    err "Не стартовала за 90с!"
    journalctl -u "${SERVICE_NAME}" --no-pager -n 20
    exit 1
fi

# 4. Быстрый health-check
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

if [ $PASSED -eq 3 ]; then
    ok "Платформа обновлена и работает!"
else
    err "Только ${PASSED}/3 health-check прошли. Проверьте логи: journalctl -u ${SERVICE_NAME} -f"
fi
