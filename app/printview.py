"""空白秤重表列印檢視：由分頁名直接產生 A4 空白表，不讀 xlsx。

版面對照 Excel 範本：日期(B1:C1 合併)、金紙總類(E1:F1 合併)、3 組編號/重量 x 30 列、
頁次在第 33 列 C 欄（編號 60 正下方）。微調請改下方 CSS 變數。
"""
from __future__ import annotations

import datetime as _dt
import re
from html import escape

ROWS, BLOCKS = 30, 3
_NAME = re.compile(r"^(神明|先靈)-(\d{8})(?:-(\d{1,2}))?$")
_LABEL = {"神明": "神明(白色)", "先靈": "先靈(黃色)"}


class BadSheetName(ValueError):
    pass


def parse(name: str) -> tuple[str, int, int, int]:
    """分頁名 -> (類別, 月, 日, 頁次)。"""
    m = _NAME.match(name)
    if not m:
        raise BadSheetName(name)
    cat, ymd, page = m.groups()
    try:
        d = _dt.datetime.strptime(ymd, "%Y%m%d").date()
    except ValueError:
        raise BadSheetName(name)
    page = int(page) if page else 1
    if page < 1:
        raise BadSheetName(name)
    return cat, d.month, d.day, page


def _sheet(name: str) -> str:
    cat, mo, d, page = parse(name)
    base = (page - 1) * ROWS * BLOCKS
    body = []
    for i in range(ROWS):
        tds = "".join(
            f'<td>{base + b * ROWS + i + 1}</td><td></td>' for b in range(BLOCKS)
        )
        body.append(f"<tr>{tds}</tr>")
    return (
        '<section class="sheet"><table>'
        "<colgroup>" + "<col>" * 6 + "</colgroup>"
        f'<tr><td>日期</td><td colspan="2">{mo}月{d}日</td>'
        f'<td>金紙總類</td><td colspan="2">{escape(_LABEL[cat])}</td></tr>'
        + "<tr>" + "<td>編號</td><td>重量</td>" * BLOCKS + "</tr>"
        + "".join(body)
        + f'</table><div class="pg"><span>第{page}頁</span></div></section>'
    )


_CSS = """
:root{ --row-h:8mm; --font:18pt; --m-top:9mm; --m-left:6mm; --m-right:6mm; }
*{ box-sizing:border-box; }
body{ margin:0; background:#888; font-family:"PMingLiU","新細明體","MingLiU",
      "AR PL UMing TW","Noto Serif CJK TC",serif; }
.bar{ position:sticky; top:0; z-index:9; background:#1e293b; color:#fff; padding:10px 16px;
      font:14px system-ui,"Microsoft JhengHei",sans-serif; display:flex; gap:16px; align-items:center; }
.bar button{ background:#2563eb; color:#fff; border:0; border-radius:6px; padding:7px 18px; font-size:15px; cursor:pointer; }
.bar .tip{ color:#cbd5e1; font-size:13px; }
.sheet{ width:210mm; height:296mm; margin:14px auto; background:#fff; overflow:hidden;
        padding:var(--m-top) var(--m-right) 0 var(--m-left); box-shadow:0 1px 6px rgba(0,0,0,.4); }
table{ width:100%; table-layout:fixed; border-collapse:collapse; }
td{ border:1px solid #000; height:var(--row-h); padding:0; text-align:center; vertical-align:middle;
    font-size:var(--font); line-height:1; white-space:nowrap; overflow:hidden; }
.pg{ display:grid; grid-template-columns:repeat(6,1fr); height:var(--row-h); }
.pg span{ grid-column:3; text-align:center; font-size:var(--font); line-height:var(--row-h); }
@page{ size:A4 portrait; margin:0; }
@media print{
  body{ background:#fff; }
  .bar{ display:none; }
  .sheet{ margin:0; box-shadow:none; }
  .sheet + .sheet{ break-before:page; }
}
"""


def render(names: list[str]) -> str:
    sheets = "".join(_sheet(n) for n in names)
    return (
        '<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
        "<title>列印空白秤重表</title>"
        f"<style>{_CSS}</style></head><body>"
        f'<div class="bar"><span>共 {len(names)} 頁</span>'
        '<button onclick="window.print()">列印</button>'
        '<span class="tip">列印視窗請選 A4、縮放 100%；若出現頁首頁尾請關閉。</span></div>'
        f"{sheets}"
        "<script>addEventListener('load',()=>setTimeout(()=>window.print(),300));</script>"
        "</body></html>"
    )
