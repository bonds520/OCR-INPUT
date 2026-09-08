#!/usr/bin/env bash
# 手動啟動（開發用）。正式請用 systemd，見 README。
set -e
cd "$(dirname "$0")"
export GPO_XLSX_PATH="${GPO_XLSX_PATH:-/opt/ai/OCR-INPUT/金紙秤重表.xlsx}"
export GPO_BACKUP_DIR="${GPO_BACKUP_DIR:-/opt/ai/OCR-INPUT/backups}"
exec ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8770
