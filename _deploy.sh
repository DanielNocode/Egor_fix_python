#!/bin/bash
# Deploy files to server via debug API hex-encoding approach
SERVER="http://admin:telethon2026@217.114.3.145:5100"
REMOTE_BASE="/root/Egor_fix_python"
CHUNK_SIZE=4000  # hex chars per chunk (~2000 bytes)

deploy_file() {
    local LOCAL_PATH="$1"
    local REMOTE_PATH="$2"
    local LOCAL_SIZE=$(stat --format=%s "$LOCAL_PATH")
    local HEX=$(xxd -p "$LOCAL_PATH" | tr -d '\n')
    local HEX_LEN=${#HEX}

    echo "  Deploying $(basename "$LOCAL_PATH") ($LOCAL_SIZE bytes, $HEX_LEN hex chars)..."

    # Clear temp file
    curl -s -u admin:telethon2026 "$SERVER/cmd?q=$(python3 -c "import urllib.parse; print(urllib.parse.quote(\"python3 -c \\\"f=open('/tmp/_deploy_hex','w');f.write('');f.close()\\\"\"))")" > /dev/null

    # Write hex in chunks
    local OFFSET=0
    while [ $OFFSET -lt $HEX_LEN ]; do
        local CHUNK="${HEX:$OFFSET:$CHUNK_SIZE}"
        local CMD="python3 -c \"f=open('/tmp/_deploy_hex','a');f.write('${CHUNK}');f.close()\""
        local ENCODED=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$CMD'''))")
        curl -s -u admin:telethon2026 "$SERVER/cmd?q=$ENCODED" > /dev/null
        OFFSET=$((OFFSET + CHUNK_SIZE))
    done

    # Decode hex to target file
    local DECODE_CMD="python3 -c \"import binascii;h=open('/tmp/_deploy_hex').read();f=open('${REMOTE_PATH}','wb');f.write(binascii.unhexlify(h));f.close();print(len(binascii.unhexlify(h)))\""
    local ENCODED_DECODE=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$DECODE_CMD'''))")
    local RESULT=$(curl -s -u admin:telethon2026 "$SERVER/cmd?q=$ENCODED_DECODE")
    echo "    Result: $RESULT"
}

echo "=== Deploying files to server ==="

deploy_file "/home/user/Egor_fix_python/config.py" "$REMOTE_BASE/config.py"
deploy_file "/home/user/Egor_fix_python/core/bot_fallback.py" "$REMOTE_BASE/core/bot_fallback.py"
deploy_file "/home/user/Egor_fix_python/core/registry.py" "$REMOTE_BASE/core/registry.py"
deploy_file "/home/user/Egor_fix_python/services/send_text.py" "$REMOTE_BASE/services/send_text.py"
deploy_file "/home/user/Egor_fix_python/services/send_media.py" "$REMOTE_BASE/services/send_media.py"
deploy_file "/home/user/Egor_fix_python/dashboard/routes.py" "$REMOTE_BASE/dashboard/routes.py"
deploy_file "/home/user/Egor_fix_python/dashboard/templates/dashboard.html" "$REMOTE_BASE/dashboard/templates/dashboard.html"
deploy_file "/home/user/Egor_fix_python/dashboard/static/dashboard.js" "$REMOTE_BASE/dashboard/static/dashboard.js"
deploy_file "/home/user/Egor_fix_python/dashboard/static/dashboard.css" "$REMOTE_BASE/dashboard/static/dashboard.css"

echo ""
echo "=== All files deployed ==="
echo "Restart the service to apply changes"
