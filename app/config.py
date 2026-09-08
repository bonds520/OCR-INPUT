"""設定值。實際部署時 XLSX_PATH 指向 SMB 掛載點。
可用環境變數覆蓋：GPO_XLSX_PATH / GPO_BACKUP_DIR / GPO_VLLM_URL / GPO_VLLM_MODEL。"""
import os
from pathlib import Path

# 主檔（唯一真實來源）
XLSX_PATH = Path(os.environ.get("GPO_XLSX_PATH", "/opt/ai/OCR-INPUT/金紙秤重表.xlsx"))

# 備份目錄，保留最近 N 份
BACKUP_DIR = Path(os.environ.get("GPO_BACKUP_DIR", str(XLSX_PATH.parent / "backups")))
BACKUP_KEEP = 30

# 本機 vLLM（VLM）
VLLM_BASE_URL = os.environ.get("GPO_VLLM_URL", "http://localhost:8000/v1")
VLLM_MODEL = os.environ.get("GPO_VLLM_MODEL", "/models/Qwen3.6-27B-FP8")

# 每頁格數：3 直欄 x 每欄 30 列
ROWS_PER_COL = 30
COLS_PER_PAGE = 3
CELLS_PER_PAGE = ROWS_PER_COL * COLS_PER_PAGE  # 90

# 重量合理範圍（超出者於複核畫面標紅）
WEIGHT_MIN = 0.1
WEIGHT_MAX = 30.0

CATEGORIES = ("神明", "先靈")
