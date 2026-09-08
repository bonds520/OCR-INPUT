"""批次上傳：多張照片 → 背景逐張 OCR → 總表人工逐列複核 → 一次交易寫入。

狀態只放記憶體 + 暫存目錄，逾時或完成即清；服務重啟則需重傳。
"""
from __future__ import annotations

import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .ocr import recognize
from .writeback import cell_ref, page_of

TTL_SECONDS = 2 * 3600
_CLEAN_KEEP_FLAGS = ("out_of_range", "parse")


@dataclass
class BatchItem:
    id: str
    filename: str
    image_path: Path
    status: str = "ocr_pending"          # ocr_pending|ocr_done|ocr_failed|confirmed|written|write_failed|skipped
    error: str = ""
    date_text: str = ""
    ocr_category: str | None = None
    # OCR 初稿（複核前）與複核後結果
    cells: list[dict] = field(default_factory=list)     # [{no,weight,confidence,voided,flags}]
    target_sheet: str | None = None
    weights: dict[str, float | None] | None = None      # 複核後；key 為表頭編號字串
    overwrite: bool = False
    conflict: bool = False

    def public(self) -> dict:
        return {
            "id": self.id, "filename": self.filename, "status": self.status,
            "error": self.error, "date_text": self.date_text,
            "ocr_category": self.ocr_category, "target_sheet": self.target_sheet,
            "overwrite": self.overwrite, "conflict": self.conflict,
            "n_values": sum(1 for c in self.cells if c.get("weight") is not None),
            "cells": self.cells,
        }


@dataclass
class Batch:
    id: str
    year: int
    dir: Path
    created_at: float = field(default_factory=time.time)
    items: list[BatchItem] = field(default_factory=list)

    def public(self) -> dict:
        done = all(i.status not in ("ocr_pending",) for i in self.items)
        return {"id": self.id, "year": self.year, "ocr_done": done,
                "items": [i.public() for i in self.items]}

    def get(self, item_id: str) -> BatchItem:
        for i in self.items:
            if i.id == item_id:
                return i
        raise KeyError(item_id)


class BatchStore:
    def __init__(self) -> None:
        self._b: dict[str, Batch] = {}

    def sweep(self) -> None:
        now = time.time()
        for bid in [k for k, v in self._b.items() if now - v.created_at > TTL_SECONDS]:
            self.drop(bid)

    def drop(self, bid: str) -> None:
        b = self._b.pop(bid, None)
        if b:
            shutil.rmtree(b.dir, ignore_errors=True)

    def create(self, year: int, files: list[tuple[str, bytes]]) -> Batch:
        self.sweep()
        bid = uuid.uuid4().hex[:12]
        d = Path(tempfile.mkdtemp(prefix=f"gpo_batch_{bid}_"))
        b = Batch(id=bid, year=year, dir=d)
        for name, data in files:
            iid = uuid.uuid4().hex[:8]
            p = d / f"{iid}{Path(name).suffix or '.jpg'}"
            p.write_bytes(data)
            b.items.append(BatchItem(id=iid, filename=name, image_path=p))
        self._b[bid] = b
        return b

    def get(self, bid: str) -> Batch:
        self.sweep()
        if bid not in self._b:
            raise KeyError(bid)
        return self._b[bid]


def run_ocr(item: BatchItem, year: int, sheet_names: list[str]) -> None:
    """單一 item 的 OCR（會阻塞，呼叫端丟到執行緒）。"""
    try:
        res = recognize(item.image_path)
        item.date_text = res.date_text
        item.ocr_category = res.category
        item.cells = [
            {"no": c.no, "weight": c.weight, "confidence": c.confidence,
             "voided": c.voided, "flags": c.flags}
            for c in res.cells
        ]
        item.target_sheet = _suggest(sheet_names, year, res.date_text, res.category)
        item.status = "ocr_done"
    except Exception as e:                       # noqa: BLE001
        item.status = "ocr_failed"
        item.error = str(e)


def _suggest(sheets: list[str], year: int, date_text: str, category: str | None) -> str | None:
    import re
    m = re.search(r"(\d{1,2})\D+(\d{1,2})", date_text or "")
    if not m or not category:
        return None
    mm, dd = int(m.group(1)), int(m.group(2))
    name = f"{category}-{year:04d}{mm:02d}{dd:02d}"
    return name if name in sheets else None


def mark_conflicts(batch: Batch) -> None:
    """兩列以上指到同一分頁 -> 全部標紅。"""
    seen: dict[str, list[BatchItem]] = {}
    for i in batch.items:
        if i.target_sheet and i.status in ("ocr_done", "confirmed"):
            seen.setdefault(i.target_sheet, []).append(i)
    for i in batch.items:
        i.conflict = bool(i.target_sheet and len(seen.get(i.target_sheet, [])) > 1)
