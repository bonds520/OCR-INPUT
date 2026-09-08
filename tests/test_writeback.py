"""M4 驗證：回填重量到分頁（在複本上操作）。"""
import datetime as dt
import re
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.sheetgen import generate_for_date        # noqa: E402
from app.writeback import cell_ref, page_of, write_weights, WEIGHT_REFS  # noqa: E402
from app.xlsxpkg import XlsxError, XlsxPackage      # noqa: E402

REAL = Path("/opt/ai/OCR-INPUT/金紙秤重表.xlsx")
WORK = Path("/tmp/claude-1000/-opt-ai-OCR-INPUT/6471c05f-afb0-4371-800e-87f39a33a8b9"
           "/scratchpad/m4_work.xlsx")
OUT = Path(__file__).resolve().parents[1] / "sample" / "金紙秤重表_M4測試.xlsx"


def _cells(pkg, sheet):
    """只回傳「重量」欄 (B/D/F 3~32) 有值的格。"""
    xml = pkg.read_part(pkg.worksheet_part(sheet)).decode()
    all_v = dict(re.findall(r'<c r="([A-F]\d+)"[^>]*><v>([0-9.]+)</v>', xml))
    return {k: v for k, v in all_v.items() if k in set(WEIGHT_REFS)}


def main():
    # 對照表：編號 -> 儲存格
    assert cell_ref(1, 1) == "B3" and cell_ref(30, 1) == "B32"
    assert cell_ref(31, 1) == "D3" and cell_ref(60, 1) == "D32"
    assert cell_ref(61, 1) == "F3" and cell_ref(90, 1) == "F32"
    assert page_of("先靈-20991231") == 1 and page_of("先靈-20991231-2") == 2
    assert cell_ref(91, 2) == "B3" and cell_ref(180, 2) == "F32"
    print("編號->儲存格對照 OK")

    shutil.copy2(REAL, WORK)
    pkg = XlsxPackage(WORK)
    generate_for_date(pkg, dt.date(2099, 12, 31), {"神明": 1, "先靈": 2})

    # 第一頁：寫 3 個值 + 1 個續頁編號範圍的值
    w1 = {1: 8.4, 2: 7.4, 31: 8.2, 61: 9.6, 23: None}
    s1 = write_weights(pkg, "先靈-20991231", w1, overwrite=False)
    print("寫入摘要 p1:", s1)
    assert s1["written"] == 4

    # 續頁：表頭編號 91、120、180
    s2 = write_weights(pkg, "先靈-20991231-2", {91: 5.0, 120: 6.5, 180: 7.0}, overwrite=False)
    assert s2["written"] == 3

    # 未勾覆蓋、又寫已有資料的分頁 -> 應擋下
    try:
        write_weights(pkg, "先靈-20991231", {1: 1.1}, overwrite=False)
        raise AssertionError("應該擋下覆蓋")
    except XlsxError as e:
        print("覆蓋保護 OK:", e)

    # 勾覆蓋 -> 整頁清空後重寫
    s3 = write_weights(pkg, "先靈-20991231", {5: 12.3}, overwrite=True)
    print("覆蓋寫入:", s3)

    pkg.backup.__self__ if False else None
    pkg.save(OUT)

    v = XlsxPackage(OUT)
    c1 = _cells(v, "先靈-20991231")
    c2 = _cells(v, "先靈-20991231-2")
    print("先靈-20991231 值格:", c1)
    print("先靈-20991231-2 值格:", c2)
    assert c1 == {"B7": "12.3"}, c1                     # 覆蓋後只剩 #5
    assert c2 == {"B3": "5", "B32": "6.5", "F32": "7"}, c2

    # 既有 126 分頁 + 其他 part 未被動到
    with zipfile.ZipFile(REAL) as za, zipfile.ZipFile(OUT) as zb:
        idx = {"[Content_Types].xml", "xl/workbook.xml",
               "xl/_rels/workbook.xml.rels", "docProps/app.xml"}
        same = sum(1 for n in za.namelist()
                   if n not in idx and za.read(n) == zb.read(n))
        print(f"原封 part：{same}/{len(za.namelist())}")
        assert same == len(za.namelist()) - len(idx)
        assert len([n for n in zb.namelist() if "printerSettings" in n]) == 126

    print("\n✅ M4 全部檢查通過 ->", OUT)


if __name__ == "__main__":
    main()
