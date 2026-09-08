"""產生空白分頁：由檔內空白範本（神明 / 先靈）複製 worksheet XML 並改寫
B1 日期、G1 頁次、A/C/E 編號欄，移除印表機設定參照與 codeName。"""
from __future__ import annotations

import datetime as _dt
import re
import uuid

from .config import CATEGORIES, ROWS_PER_COL
from .xlsxpkg import XlsxError, XlsxPackage, excel_serial

# 範本分頁名稱 -> 對應 worksheet part
_TEMPLATE_SHEET = {"神明": "神明", "先靈": "先靈"}


def _template_part(pkg: XlsxPackage, category: str) -> str:
    """回傳範本分頁的 worksheet part 名稱，如 xl/worksheets/sheet1.xml。"""
    wb = pkg.text("xl/workbook.xml")
    rels = pkg.text("xl/_rels/workbook.xml.rels")
    m = re.search(rf'<sheet [^>]*name="{re.escape(category)}"[^>]*r:id="(rId\d+)"', wb)
    if not m:
        raise XlsxError(f"找不到範本分頁：{category}")
    rid = m.group(1)
    m = re.search(rf'<Relationship Id="{rid}"[^>]*Target="([^"]+)"', rels)
    if not m:
        raise XlsxError(f"範本分頁 rel 遺失：{rid}")
    return "xl/" + m.group(1).lstrip("/").removeprefix("xl/")


def build_sheet_xml(template_xml: str, d: _dt.date, page: int) -> bytes:
    """由範本 XML 產生一張新分頁 XML。page 為 1-based 頁次。"""
    x = template_xml
    offset = (page - 1) * ROWS_PER_COL * 3

    # 1) 換新的 xr:uid
    x = re.sub(r'xr:uid="\{[0-9A-Fa-f-]+\}"',
               f'xr:uid="{{{str(uuid.uuid4()).upper()}}}"', x, count=1)

    # 2) 移除 codeName（避免與既有分頁衝突）
    x = re.sub(r'<sheetPr codeName="[^"]*"\s*/>', "<sheetPr/>", x, count=1)

    # 3) B1：改成真日期序列值 + 套 m月d日 樣式 (s="5")
    x = re.sub(r'<c r="B1"[^>]*/>',
               f'<c r="B1" s="5"><v>{excel_serial(d)}</v></c>', x, count=1)

    # 4) 頁次（第 N 頁）：放在第 33 列 C 欄（編號 60 那格的正下方），
    #    列印時落在第一頁範圍內。新增一列，不動既有 1~32 列。
    page_row = (f'<row r="33" spans="1:9" x14ac:dyDescent="0.25">'
                f'<c r="C33" s="2" t="inlineStr"><is><t>第{page}頁</t></is></c>'
                f'</row>')
    x = x.replace("</sheetData>", page_row + "</sheetData>", 1)
    x = x.replace('<dimension ref="A1:I32"/>', '<dimension ref="A1:I33"/>', 1)

    # 5) A/C/E 欄編號：原值 + offset
    if offset:
        def _bump(m: re.Match) -> str:
            return f'{m.group(1)}<v>{int(m.group(2)) + offset}</v>'
        x = re.sub(r'(<c r="[ACE]\d+" s="1">)<v>(\d+)</v>', _bump, x)

    # 6) 移除 pageSetup 的印表機設定參照（不複製 .bin，也不建 _rels）
    x = re.sub(r'(<pageSetup\b[^>]*?)\s+r:id="rId\d+"', r"\1", x, count=1)

    return x.encode("utf-8")


def generate_for_date(pkg: XlsxPackage, d: _dt.date,
                      pages: dict[str, int]) -> dict[str, list[str]]:
    """為單一日期產生神明/先靈分頁。pages = {"神明": n, "先靈": m}。
    已存在的頁略過；頁數不足則補足。回傳 {"created": [...], "skipped": [...]}。"""
    existing = set(pkg.sheet_names())
    created: list[str] = []
    skipped: list[str] = []
    ymd = d.strftime("%Y%m%d")

    for cat in CATEGORIES:
        want = max(1, int(pages.get(cat, 1)))
        tmpl = pkg.text(_template_part(pkg, cat))
        for page in range(1, want + 1):
            name = f"{cat}-{ymd}" if page == 1 else f"{cat}-{ymd}-{page}"
            if name in existing:
                skipped.append(name)
                continue
            pkg.add_worksheet(name, build_sheet_xml(tmpl, d, page))
            existing.add(name)
            created.append(name)
    return {"created": created, "skipped": skipped}
