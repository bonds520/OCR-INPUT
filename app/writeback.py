"""把複核後的重量寫回指定分頁。

分頁重量格永遠在 B3:B32 / D3:D32 / F3:F32（3 直欄各 30 列）。
續頁（-2、-3…）表頭印的編號是 91-180、181-270…，寫入前先換算成本頁 1-90。
"""
from __future__ import annotations

import re

from .config import ROWS_PER_COL
from .xlsxpkg import XlsxError, XlsxPackage

_COL_FOR_BLOCK = ("B", "D", "F")   # 第 0/1/2 直欄
WEIGHT_REFS = [f"{c}{r}" for c in _COL_FOR_BLOCK for r in range(3, 3 + ROWS_PER_COL)]


def page_of(sheet_name: str) -> int:
    """先靈-YYYYMMDD -> 1；先靈-YYYYMMDD-N -> N。"""
    m = re.search(r"-\d{8}-(\d+)$", sheet_name)
    return int(m.group(1)) if m else 1


def cell_ref(printed_no: int, page: int) -> str:
    """表頭印的編號 -> 本頁儲存格參照。"""
    local = printed_no - (page - 1) * ROWS_PER_COL * 3   # 1..90
    if not (1 <= local <= ROWS_PER_COL * 3):
        raise XlsxError(f"編號 {printed_no} 不屬於第 {page} 頁")
    block, idx = divmod(local - 1, ROWS_PER_COL)          # block 0..2, idx 0..29
    return f"{_COL_FOR_BLOCK[block]}{3 + idx}"


def write_weights(pkg: XlsxPackage, sheet_name: str,
                  weights: dict[int, float | None],
                  overwrite: bool = False) -> dict:
    """weights：{表頭編號: 重量}。回傳寫入摘要。呼叫端負責 backup + save。"""
    if sheet_name not in pkg.sheet_names():
        raise XlsxError(f"分頁不存在：{sheet_name}")
    page = page_of(sheet_name)

    if not overwrite:
        filled = pkg.count_filled(sheet_name, WEIGHT_REFS)
        if filled:
            raise XlsxError(f"分頁 {sheet_name} 已有 {filled} 格資料；"
                            f"如要覆蓋請勾選「覆蓋」。")

    values: dict[str, float | None] = {}
    if overwrite:                       # 覆蓋模式：先整頁清空
        values.update({ref: None for ref in WEIGHT_REFS})
    for no, w in weights.items():
        values[cell_ref(int(no), page)] = None if w is None else round(float(w), 2)

    pkg.set_cells(sheet_name, values)
    written = sum(1 for v in values.values() if v is not None)
    return {"sheet": sheet_name, "written": written,
            "cleared": sum(1 for v in values.values() if v is None)}
