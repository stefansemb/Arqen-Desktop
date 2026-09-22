#!/usr/bin/env bash
set -u

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
    logger -t arqen-health "FAIL: ${failures[*]}"
    exit 1
fi

logger -t arqen-health "OK: api ollama disk-${disk_use}%"
