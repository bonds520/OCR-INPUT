"""金紙秤重表手寫重量 OCR：呼叫本機 vLLM（Qwen3.6-27B VLM）。

輸出每一「編號 -> 重量」的判讀值與信心，供人工複核畫面使用。
只讀「重量」欄；編號欄由系統固定，不辨識。
"""
from __future__ import annotations

import base64
import io
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from .config import (CELLS_PER_PAGE, VLLM_BASE_URL, VLLM_MODEL,
                     WEIGHT_MAX, WEIGHT_MIN)

_MAX_EDGE = 1600          # 送模型前縮圖長邊上限
_TIMEOUT = 600

_PROMPT = """你是資料輸入員。這是一張「金紙秤重表」，手寫的藍筆數字是每包的重量（公斤）。

版面：三組「編號 / 重量」直欄。左組編號 1-30、中組 31-60、右組 61-90。
每個編號右邊一格是該包重量的手寫數字。

規則：
- 手寫用逗號當小數點：「11,6」= 11.6，「9,8」= 9.8。
- 只列出「重量格有手寫數字」的編號；空白格完全不要列出。
- 有塗改、覆寫的格，取最後寫定的值。
- 整格被劃掉 / 打叉 / 塗銷的編號，放進 voided 陣列，不要放進 weights。
- 看不清楚、沒把握的編號，同時放進 low 陣列（weights 仍照最接近字面填）。
- 不要推測、不要補零。

只輸出 JSON，不要任何其他文字。weights 的 key 是編號字串、value 是數字：
{"date_text":"9月5日","category":"神明","weights":{"1":11.6,"2":13.6},"low":[16],"voided":[]}
"""


@dataclass
class Cell:
    no: int
    weight: float | None
    confidence: str          # high | low
    voided: bool = False
    flags: list[str] = None  # 後處理加的警示：out_of_range / parse

    def __post_init__(self):
        if self.flags is None:
            self.flags = []


@dataclass
class OcrResult:
    date_text: str
    category: str | None
    cells: list[Cell]
    raw: str

    def as_dict(self):
        d = asdict(self)
        return d


def _encode(image_path: Path) -> str:
    im = Image.open(image_path)
    im = ImageOps.exif_transpose(im)          # 依 EXIF 轉正
    im = im.convert("RGB")
    w, h = im.size
    scale = min(1.0, _MAX_EDGE / max(w, h))
    if scale < 1.0:
        im = im.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _call_vllm(b64: str) -> str:
    payload = {
        "model": VLLM_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": _PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
        "temperature": 0,
        "max_tokens": 1500,
    }
    r = httpx.post(f"{VLLM_BASE_URL}/chat/completions", json=payload,
                   timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"模型未回傳 JSON：{text[:200]}")
    return json.loads(m.group(0))


def _norm_weight(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    s = str(v).strip().replace(",", ".").replace(" ", "")
    s = re.sub(r"[^0-9.]", "", s)
    if s in ("", "."):
        return None
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def _as_int_set(v) -> set[int]:
    out = set()
    for x in v or []:
        try:
            out.add(int(x))
        except (ValueError, TypeError):
            pass
    return out


def parse_response(raw: str) -> OcrResult:
    data = _extract_json(raw)
    low = _as_int_set(data.get("low"))
    voided = _as_int_set(data.get("voided"))
    weights = data.get("weights") or {}

    cells: list[Cell] = []
    for k, v in weights.items():
        try:
            no = int(k)
        except (ValueError, TypeError):
            continue
        if not (1 <= no <= CELLS_PER_PAGE) or no in voided:
            continue
        w = _norm_weight(v)
        c = Cell(no=no, weight=w, confidence="low" if no in low else "high")
        if w is None:
            c.flags.append("parse")
            c.confidence = "low"
        elif not (WEIGHT_MIN <= w <= WEIGHT_MAX):
            c.flags.append("out_of_range")
            c.confidence = "low"
        cells.append(c)
    for no in sorted(voided):
        if 1 <= no <= CELLS_PER_PAGE:
            cells.append(Cell(no=no, weight=None, confidence="high", voided=True))
    cells.sort(key=lambda c: c.no)
    cat = data.get("category")
    if cat:
        cat = "神明" if "神" in cat else ("先靈" if "先" in cat or "靈" in cat else None)
    return OcrResult(date_text=str(data.get("date_text", "")).strip(),
                     category=cat, cells=cells, raw=raw)


def recognize(image_path: str | Path) -> OcrResult:
    return parse_response(_call_vllm(_encode(Path(image_path))))
