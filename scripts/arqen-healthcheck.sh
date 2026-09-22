#!/usr/bin/env bash
set -u

STATE_DIR=/var/lib/arqen-health
STATE_FILE="$STATE_DIR/status"
mkdir -p "$STATE_DIR"
failures=()

if ! curl -fsS --max-time 5 http://127.0.0.1:8765/api/v1/health >/dev/null; then
    failures+=("arqen-api")
fi

if ! curl -fsS --max-time 5 http://127.0.0.1:11434/api/tags >/dev/null; then
    failures+=("ollama")
fi

disk_use=$(df --output=pcent / | tail -n 1 | tr -dc '0-9')
if [ "${disk_use:-0}" -ge 85 ]; then
    failures+=("disk-${disk_use}%")
fi

if [ "${#failures[@]}" -gt 0 ]; then
    status="FAIL: ${failures[*]}"
    logger -t arqen-health "$status"
    if [ "${TELEGRAM_BOT_TOKEN:-}" ] && [ "${TELEGRAM_CHAT_ID:-}" ] && [ "$(cat "$STATE_FILE" 2>/dev/null || true)" != "$status" ]; then
        message="🔴 Arqen VPS-larm%0A$status"
        curl -fsS --max-time 10 -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${TELEGRAM_CHAT_ID}" -d "text=${message}" >/dev/null || true
    fi
    printf '%s' "$status" > "$STATE_FILE"
    exit 1
fi

status="OK: api ollama disk-${disk_use}%"
logger -t arqen-health "$status"
previous=$(cat "$STATE_FILE" 2>/dev/null || true)
if [ "$previous" != "" ] && [ "$previous" != "$status" ] && [ "${TELEGRAM_BOT_TOKEN:-}" ] && [ "${TELEGRAM_CHAT_ID:-}" ]; then
    curl -fsS --max-time 10 -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" -d "text=🟢 Arqen VPS återställd%0A$status" >/dev/null || true
fi
printf '%s' "$status" > "$STATE_FILE"
