#!/usr/bin/env bash
# 首次安裝：建立 venv、安裝套件。
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
echo "完成。手動啟動：./run.sh    正式：見 README.md"
