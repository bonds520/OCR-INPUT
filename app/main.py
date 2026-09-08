"""金紙秤重 OCR 系統 — FastAPI。

兩個功能：
  /  網頁（產生分頁 / 上傳辨識複核）
  /api/generate  產生空白分頁
  /api/ocr       上傳照片辨識（不寫檔）
  /api/write     複核後寫回分頁
所有對 XLSX 的寫入經同一把鎖序列化，寫前偵測 Excel 鎖檔並備份。
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import re
import tempfile
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import config
from .batch import BatchStore, mark_conflicts, run_ocr
from .ocr import recognize
from .sheetgen import generate_for_date
from .writeback import WEIGHT_REFS, page_of, write_weights
from .xlsxpkg import XlsxError, XlsxPackage, excel_lock_present

app = FastAPI(title="金紙秤重 OCR")
_WEB = Path(__file__).resolve().parents[1] / "web"
_lock = asyncio.Lock()
_batches = BatchStore()


# ---- schema ---------------------------------------------------------------
class GenerateReq(BaseModel):
    dates: list[str]                 # "YYYYMMDD"
    god_pages: int = 1               # 神明
    spirit_pages: int = 1            # 先靈


class WriteReq(BaseModel):
    sheet: str
    weights: dict[str, float | None]  # {"1": 8.4, ...}（表頭編號）
    overwrite: bool = False


class ItemReviewReq(BaseModel):
    sheet: str
    weights: dict[str, float | None]
    overwrite: bool = False


# ---- helpers ------------------------------------------------------------
def _guard_writable() -> None:
    if not config.XLSX_PATH.exists():
        raise HTTPException(500, f"找不到主檔：{config.XLSX_PATH}")
    if excel_lock_present(config.XLSX_PATH):
        raise HTTPException(409, "主檔正被 Excel 開啟中，請先關閉再試。")


def _parse_ymd(s: str) -> _dt.date:
    s = s.strip().replace("-", "").replace("/", "")
    if not re.fullmatch(r"\d{8}", s):
        raise HTTPException(422, f"日期格式需為 YYYYMMDD：{s!r}")
    return _dt.datetime.strptime(s, "%Y%m%d").date()


def _suggest_sheet(sheets: list[str], date_text: str, category: str | None) -> str | None:
    m = re.search(r"(\d{1,2})\D+(\d{1,2})", date_text or "")
    if not m or not category:
        return None
    mm, dd = int(m.group(1)), int(m.group(2))
    today = _dt.date.today()
    for yr in (today.year, today.year - 1, today.year + 1):
        try:
            name = f"{category}-{_dt.date(yr, mm, dd):%Y%m%d}"
        except ValueError:
            continue
        if name in sheets:
            return name
    return None


# ---- routes ----------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(_WEB / "index.html")


@app.get("/api/sheets")
def list_sheets():
    return {"sheets": XlsxPackage(config.XLSX_PATH).sheet_names()}


@app.post("/api/generate")
async def api_generate(req: GenerateReq):
    dates = [_parse_ymd(s) for s in req.dates]
    if not dates:
        raise HTTPException(422, "請至少輸入一個日期")
    pages = {"神明": max(1, req.god_pages), "先靈": max(1, req.spirit_pages)}
    async with _lock:
        _guard_writable()
        pkg = XlsxPackage(config.XLSX_PATH)
        result = {"created": [], "skipped": []}
        for d in dates:
            r = generate_for_date(pkg, d, pages)
            result["created"] += r["created"]
            result["skipped"] += r["skipped"]
        if result["created"]:
            pkg.backup(config.BACKUP_DIR, config.BACKUP_KEEP)
            pkg.save(config.XLSX_PATH)
    return result


@app.post("/api/ocr")
async def api_ocr(image: UploadFile):
    data = await image.read()
    if not data:
        raise HTTPException(422, "空檔案")
    suffix = Path(image.filename or "x.jpg").suffix or ".jpg"
    tmp = Path(tempfile.mkstemp(suffix=suffix)[1])
    try:
        tmp.write_bytes(data)
        res = recognize(tmp)
    except Exception as e:                       # noqa: BLE001
        raise HTTPException(502, f"OCR 失敗：{e}")
    finally:
        tmp.unlink(missing_ok=True)
    sheets = XlsxPackage(config.XLSX_PATH).sheet_names()
    return {
        "date_text": res.date_text,
        "category": res.category,
        "suggested_sheet": _suggest_sheet(sheets, res.date_text, res.category),
        "sheets": sheets,
        "cells": [
            {"no": c.no, "weight": c.weight, "confidence": c.confidence,
             "voided": c.voided, "flags": c.flags}
            for c in res.cells
        ],
    }


@app.post("/api/write")
async def api_write(req: WriteReq):
    weights = {int(k): v for k, v in req.weights.items()}
    async with _lock:
        _guard_writable()
        pkg = XlsxPackage(config.XLSX_PATH)
        try:
            summary = write_weights(pkg, req.sheet, weights, req.overwrite)
        except XlsxError as e:
            raise HTTPException(409, str(e))
        pkg.backup(config.BACKUP_DIR, config.BACKUP_KEEP)
        pkg.save(config.XLSX_PATH)
    return summary


# ================= 批次上傳（Plan C）=================
async def _run_batch_ocr(bid: str):
    b = _batches.get(bid)
    sheets = XlsxPackage(config.XLSX_PATH).sheet_names()
    for item in b.items:
        await asyncio.to_thread(run_ocr, item, b.year, sheets)
        mark_conflicts(b)


@app.post("/api/batch")
async def api_batch_create(year: int = Form(...), images: list[UploadFile] = ...):
    if not images:
        raise HTTPException(422, "請至少選一張圖")
    if not (2000 <= year <= 2100):
        raise HTTPException(422, "年份不合理")
    files = [(f.filename or "x.jpg", await f.read()) for f in images]
    files = [(n, d) for n, d in files if d]
    if not files:
        raise HTTPException(422, "檔案都是空的")
    b = _batches.create(year, files)
    asyncio.create_task(_run_batch_ocr(b.id))
    return b.public()


@app.get("/api/batch/{bid}")
async def api_batch_get(bid: str):
    try:
        b = _batches.get(bid)
    except KeyError:
        raise HTTPException(404, "批次不存在或已逾時清除")
    out = b.public()
    out["sheets"] = XlsxPackage(config.XLSX_PATH).sheet_names()
    return out


@app.get("/api/batch/{bid}/item/{iid}/image")
async def api_batch_image(bid: str, iid: str):
    try:
        item = _batches.get(bid).get(iid)
    except KeyError:
        raise HTTPException(404, "找不到項目")
    return FileResponse(item.image_path)


@app.post("/api/batch/{bid}/item/{iid}")
async def api_batch_review(bid: str, iid: str, req: ItemReviewReq):
    try:
        b = _batches.get(bid)
        item = b.get(iid)
    except KeyError:
        raise HTTPException(404, "找不到項目")
    if req.sheet not in XlsxPackage(config.XLSX_PATH).sheet_names():
        raise HTTPException(422, f"分頁不存在：{req.sheet}")
    item.target_sheet = req.sheet
    item.weights = req.weights
    item.overwrite = req.overwrite
    item.status = "confirmed"
    mark_conflicts(b)
    return item.public()


@app.post("/api/batch/{bid}/write")
async def api_batch_write(bid: str):
    try:
        b = _batches.get(bid)
    except KeyError:
        raise HTTPException(404, "批次不存在或已逾時清除")
    ready = [i for i in b.items if i.status == "confirmed" and i.weights is not None]
    if not ready:
        raise HTTPException(422, "沒有已確認的項目")
    if any(i.conflict for i in ready):
        raise HTTPException(409, "仍有分頁衝突未解決")

    results = []
    async with _lock:
        _guard_writable()
        pkg = XlsxPackage(config.XLSX_PATH)
        pkg.backup(config.BACKUP_DIR, config.BACKUP_KEEP)
        wrote_any = False
        for item in ready:
            try:
                w = {int(k): v for k, v in item.weights.items()}
                s = write_weights(pkg, item.target_sheet, w, item.overwrite)
                item.status = "written"
                wrote_any = True
                results.append({"id": item.id, "ok": True, **s})
            except XlsxError as e:
                item.status = "write_failed"
                item.error = str(e)
                results.append({"id": item.id, "ok": False, "error": str(e)})
        if wrote_any:
            pkg.save(config.XLSX_PATH)
    return {"results": results,
            "written": sum(1 for r in results if r["ok"]),
            "failed": sum(1 for r in results if not r["ok"])}


@app.delete("/api/batch/{bid}")
async def api_batch_delete(bid: str):
    _batches.drop(bid)
    return {"ok": True}
