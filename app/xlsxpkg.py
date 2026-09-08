"""OOXML (.xlsx) 外科手術式編輯。

原則：讀取原始 zip，**未更動的 part 一律原封 bytes 複製**（保留壓縮、時間戳、
外部屬性），只重寫我們明確要改的幾個文字 part，並可新增 part。
既有 126 張分頁、126 個 printerSettings*.bin 完全不動。

用途：
  - 產生分頁（新增 worksheet part + 登記 4 處索引）
  - 回填重量（只改單一 sheetN.xml 的 <c> 內容）
"""
from __future__ import annotations

import datetime as _dt
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

_CT = "[Content_Types].xml"
_WB = "xl/workbook.xml"
_WB_RELS = "xl/_rels/workbook.xml.rels"
_APP = "docProps/app.xml"
_WS_CT = ("application/vnd.openxmlformats-officedocument."
          "spreadsheetml.worksheet+xml")
_WS_REL_TYPE = ("http://schemas.openxmlformats.org/officeDocument/"
                "2006/relationships/worksheet")
_EXCEL_EPOCH = _dt.date(1899, 12, 30)  # 序列值 0（含 1900 閏年 bug 的慣例）

# Excel 分頁名稱不允許的字元
_BAD_SHEETNAME = re.compile(r"[:\\/?*\[\]]")


def excel_serial(d: _dt.date) -> int:
    return (d - _EXCEL_EPOCH).days


class XlsxError(RuntimeError):
    pass


@dataclass
class XlsxPackage:
    src: Path
    _parts: dict[str, bytes] = field(default_factory=dict)      # name -> bytes（僅載入需檢視/修改的）
    _infos: dict[str, zipfile.ZipInfo] = field(default_factory=dict)
    _order: list[str] = field(default_factory=list)             # 原始 part 順序
    _overrides: dict[str, bytes] = field(default_factory=dict)  # 要重寫的既有 part
    _additions: dict[str, bytes] = field(default_factory=dict)  # 新增 part

    # ---- 載入 -------------------------------------------------------------
    def __post_init__(self) -> None:
        with zipfile.ZipFile(self.src, "r") as z:
            for info in z.infolist():
                self._order.append(info.filename)
                self._infos[info.filename] = info
            for name in (_CT, _WB, _WB_RELS, _APP):
                self._parts[name] = z.read(name)

    def read_part(self, name: str) -> bytes:
        if name in self._additions:
            return self._additions[name]
        if name in self._overrides:
            return self._overrides[name]
        if name in self._parts:
            return self._parts[name]
        with zipfile.ZipFile(self.src, "r") as z:
            return z.read(name)

    def text(self, name: str) -> str:
        return self.read_part(name).decode("utf-8")

    # ---- 查詢 -------------------------------------------------------------
    def sheet_names(self) -> list[str]:
        wb = self.text(_WB)
        return re.findall(r'<sheet [^>]*name="([^"]*)"', wb)

    def _max_num(self, pattern: str, text: str) -> int:
        nums = [int(m) for m in re.findall(pattern, text)]
        return max(nums) if nums else 0

    # ---- 新增分頁 -------------------------------------------------------
    def add_worksheet(self, name: str, xml: bytes) -> None:
        """新增一張 worksheet：寫 sheetN.xml，並登記到
        [Content_Types].xml / workbook.xml.rels / workbook.xml / app.xml。"""
        if not name or len(name) > 31 or _BAD_SHEETNAME.search(name):
            raise XlsxError(f"分頁名稱不合法：{name!r}")
        if name in self.sheet_names():
            raise XlsxError(f"分頁已存在：{name!r}")

        ct = self._overrides.get(_CT, self._parts[_CT]).decode("utf-8")
        rels = self._overrides.get(_WB_RELS, self._parts[_WB_RELS]).decode("utf-8")
        wb = self._overrides.get(_WB, self._parts[_WB]).decode("utf-8")
        app = self._overrides.get(_APP, self._parts[_APP]).decode("utf-8")

        # 檔名編號：現有 xl/worksheets/sheetN.xml 的最大值 +1（含本批已加入者）
        existing = "\n".join(self._order) + "\n" + "\n".join(self._additions)
        n = self._max_num(r"xl/worksheets/sheet(\d+)\.xml", existing) + 1
        part_name = f"xl/worksheets/sheet{n}.xml"

        rid = f"rId{self._max_num(r'Id=\"rId(\d+)\"', rels) + 1}"
        sheet_id = self._max_num(r'sheetId=\"(\d+)\"', wb) + 1

        # [Content_Types].xml
        ins = f'<Override PartName="/{part_name}" ContentType="{_WS_CT}"/>'
        ct = ct.replace("</Types>", ins + "</Types>", 1)

        # workbook.xml.rels
        ins = (f'<Relationship Id="{rid}" Type="{_WS_REL_TYPE}" '
               f'Target="worksheets/sheet{n}.xml"/>')
        rels = rels.replace("</Relationships>", ins + "</Relationships>", 1)

        # workbook.xml：<sheet> 追加到最後（append 到分頁尾端）
        ins = (f'<sheet name={quoteattr(name)} sheetId="{sheet_id}" '
               f'r:id="{rid}"/>')
        wb = wb.replace("</sheets>", ins + "</sheets>", 1)
        # 強制開檔重算（讓新分頁 H2/I2 立即有值）
        if "fullCalcOnLoad" not in wb:
            wb = re.sub(r"<calcPr ([^/]*?)/>",
                        r'<calcPr \1 fullCalcOnLoad="1"/>', wb, count=1)

        # docProps/app.xml：更新分頁數與名稱清單（best-effort）
        app = self._bump_app(app, name)

        self._overrides[_CT] = ct.encode("utf-8")
        self._overrides[_WB_RELS] = rels.encode("utf-8")
        self._overrides[_WB] = wb.encode("utf-8")
        self._overrides[_APP] = app.encode("utf-8")
        self._additions[part_name] = xml

    @staticmethod
    def _bump_app(app: str, new_name: str) -> str:
        m = re.search(r"(<vt:vector size=\")(\d+)(\" baseType=\"lpstr\">)", app)
        if not m:
            return app  # 結構不符就跳過，Excel 會自行修正
        size = int(m.group(2)) + 1
        app = app[:m.start()] + m.group(1) + str(size) + m.group(3) + app[m.end():]
        app = app.replace("</vt:vector></TitlesOfParts>",
                          f"<vt:lpstr>{escape(new_name)}</vt:lpstr>"
                          "</vt:vector></TitlesOfParts>", 1)
        app = re.sub(r"(<vt:variant><vt:i4>)(\d+)(</vt:i4></vt:variant>)",
                     lambda mm: mm.group(1) + str(int(mm.group(2)) + 1) + mm.group(3),
                     app, count=1)
        return app

    # ---- 改單一 worksheet part（回填用）------------------------------
    def replace_part(self, name: str, data: bytes) -> None:
        if name not in self._infos and name not in self._additions:
            raise XlsxError(f"part 不存在：{name}")
        (self._additions if name in self._additions else self._overrides)[name] = data

    def worksheet_part(self, sheet_name: str) -> str:
        wb = self.text(_WB)
        m = re.search(rf'<sheet [^>]*name="{re.escape(sheet_name)}"[^>]*r:id="(rId\d+)"', wb)
        if not m:
            raise XlsxError(f"分頁不存在：{sheet_name}")
        rid = m.group(1)
        rels = self.text(_WB_RELS)
        m = re.search(rf'<Relationship Id="{rid}"[^>]*Target="([^"]+)"', rels)
        return "xl/" + m.group(1).lstrip("/").removeprefix("xl/")

    def _ensure_full_recalc(self) -> None:
        wb = self._overrides.get(_WB, self._parts[_WB]).decode("utf-8")
        if "fullCalcOnLoad" not in wb:
            wb = re.sub(r"<calcPr ([^/]*?)/>",
                        r'<calcPr \1 fullCalcOnLoad="1"/>', wb, count=1)
            self._overrides[_WB] = wb.encode("utf-8")

    def set_cells(self, sheet_name: str, values: dict[str, float | None]) -> None:
        """把 {A1格參照: 值} 寫進指定分頁。值為 None 代表清空該格。
        只動被指定的 <c>，其餘 bytes 不變；公式格請勿列入。"""
        part = self.worksheet_part(sheet_name)
        xml = self.read_part(part).decode("utf-8")
        for ref, val in values.items():
            if val is None:
                repl = rf'<c r="{ref}"\1/>'
            else:
                num = f"{float(val):g}"
                repl = rf'<c r="{ref}"\1><v>{num}</v></c>'
            pat = rf'<c r="{ref}"( s="\d+")?(?:/>|>.*?</c>)'
            xml, n = re.subn(pat, repl, xml, count=1)
            if n == 0:
                raise XlsxError(f"{sheet_name} 找不到儲存格 {ref}")
        self._ensure_full_recalc()
        self.replace_part(part, xml.encode("utf-8"))

    def count_filled(self, sheet_name: str, refs: list[str]) -> int:
        xml = self.read_part(self.worksheet_part(sheet_name)).decode("utf-8")
        return sum(1 for r in refs
                   if re.search(rf'<c r="{r}"[^>]*><v>', xml))

    # ---- 寫出 -----------------------------------------------------------
    def save(self, dest: Path) -> None:
        dest = Path(dest)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        with zipfile.ZipFile(self.src, "r") as zin, \
             zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for name in self._order:
                info = self._infos[name]
                if name in self._overrides:
                    zi = zipfile.ZipInfo(name, date_time=info.date_time)
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    zi.external_attr = info.external_attr
                    zout.writestr(zi, self._overrides[name])
                else:
                    # 原封不動：連壓縮方式一起沿用
                    zout.writestr(info, zin.read(name))
            for name, data in self._additions.items():
                zi = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                zi.compress_type = zipfile.ZIP_DEFLATED
                zout.writestr(zi, data)
        tmp.replace(dest)

    def backup(self, backup_dir: Path, keep: int) -> Path:
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = backup_dir / f"{self.src.stem}_{stamp}{self.src.suffix}"
        shutil.copy2(self.src, dst)
        olds = sorted(backup_dir.glob(f"{self.src.stem}_*{self.src.suffix}"))
        for p in olds[:-keep]:
            p.unlink()
        return dst


def excel_lock_present(xlsx_path: Path) -> bool:
    """Excel 開啟中會建立 ~$檔名。存在則不應寫入。"""
    return (Path(xlsx_path).parent / f"~${Path(xlsx_path).name}").exists()
