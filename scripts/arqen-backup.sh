#!/usr/bin/env bash
set -euo pipefail
backup_dir=/var/backups/arqen
export RCLONE_CONFIG=/home/ubuntu/.config/rclone/rclone.conf
mkdir -p "$backup_dir"
stamp=$(date -u +%Y%m%d-%H%M%S)
tar -czf "$backup_dir/arqen-$stamp.tar.gz" -C /home/ubuntu/Arqen-Desktop config data/sessions
rclone copy "$backup_dir/arqen-$stamp.tar.gz" gdrive-crypt:daily
find "$backup_dir" -type f -name 'arqen-*.tar.gz' -printf '%T@ %p\n' | sort -nr | tail -n +8 | cut -d' ' -f2- | xargs -r rm -f
logger -t arqen-backup "OK: $backup_dir/arqen-$stamp.tar.gz"
