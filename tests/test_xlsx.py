"""M1 驗證：外科手術式分頁產生。全程在複本上操作，不碰真實主檔。"""
import datetime as dt
import re
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.sheetgen import build_sheet_xml, generate_for_date  # noqa: E402
from app.xlsxpkg import XlsxPackage, excel_serial  # noqa: E402

REAL = Path("/opt/ai/OCR-INPUT/金紙秤重表.xlsx")
OUT = Path(__file__).resolve().parents[1] / "sample" / "金紙秤重表_M1測試.xlsx"
WORK = Path("/tmp/claude-1000/-opt-ai-OCR-INPUT/6471c05f-afb0-4371-800e-87f39a33a8b9"
           "/scratchpad/m1_work.xlsx")


def _sheet_part(pkg, name):
    wb = pkg.text("xl/workbook.xml")
    rels = pkg.text("xl/_rels/workbook.xml.rels")
    rid = re.search(rf'<sheet [^>]*name="{re.escape(name)}"[^>]*r:id="(rId\d+)"', wb).group(1)
    tgt = re.search(rf'<Relationship Id="{rid}"[^>]*Target="([^"]+)"', rels).group(1)
    return "xl/" + tgt.lstrip("/").removeprefix("xl/")


def main():
    shutil.copy2(REAL, WORK)
    pkg = XlsxPackage(WORK)
    n_before = len(pkg.sheet_names())
    assert "先靈-20991231" not in pkg.sheet_names()

    # 產生兩個日期：一個 1 頁、一個神明2頁/先靈3頁
    r1 = generate_for_date(pkg, dt.date(2099, 12, 31), {"神明": 1, "先靈": 1})
    r2 = generate_for_date(pkg, dt.date(2099, 12, 30), {"神明": 2, "先靈": 3})
    # 重跑同日期 → 應全部略過（不足才補；這裡數量相同）
    r3 = generate_for_date(pkg, dt.date(2099, 12, 31), {"神明": 1, "先靈": 1})
    # 既有基礎頁 + 要求更多頁 → 只補續頁
    r4 = generate_for_date(pkg, dt.date(2099, 12, 31), {"神明": 1, "先靈": 2})

    print("r1 created:", r1["created"])
    print("r2 created:", r2["created"])
    print("r3 (should all skip):", r3)
    print("r4 (should add 先靈-...-2 only):", r4)

    assert r1["created"] == ["神明-20991231", "先靈-20991231"]
    assert r2["created"] == [
        "神明-20991230", "神明-20991230-2",
        "先靈-20991230", "先靈-20991230-2", "先靈-20991230-3",
    ]
    assert r3["created"] == [] and len(r3["skipped"]) == 2
    assert r4["created"] == ["先靈-20991231-2"], r4

    pkg.save(OUT)

    # ---- 驗證輸出檔 ----
    v = XlsxPackage(OUT)
    names = v.sheet_names()
    print(f"\n分頁數 {n_before} -> {len(names)} (+{len(names) - n_before})")
    assert len(names) == n_before + 8
    for nm in ("神明-20991231", "先靈-20991231", "先靈-20991231-2",
               "神明-20991230-2", "先靈-20991230-3"):
        assert nm in names, nm
    # append 到最後
    assert names[-8:] == [
        "神明-20991231", "先靈-20991231",
        "神明-20991230", "神明-20991230-2",
        "先靈-20991230", "先靈-20991230-2", "先靈-20991230-3",
        "先靈-20991231-2",
    ], names[-8:]

    # 內容抽查：先靈-20991231（第1頁）與 先靈-20991230-3（第3頁，編號181-270）
    p1 = v.text(_sheet_part(v, "先靈-20991231"))
    p3 = v.text(_sheet_part(v, "先靈-20991230-3"))

    assert f'<c r="B1" s="5"><v>{excel_serial(dt.date(2099,12,31))}</v></c>' in p1
    assert '<c r="C33" s="2" t="inlineStr"><is><t>第1頁</t></is></c>' in p1
    assert '<dimension ref="A1:I33"/>' in p1
    assert '先靈(黃色)' not in p1 or 't="s"' in p1  # 類別沿用範本 shared string
    assert 'r:id=' not in re.search(r'<pageSetup[^>]*/>', p1).group(0)
    assert '<c r="A3" s="1"><v>1</v></c>' in p1
    assert '<c r="E32" s="1"><v>90</v></c>' in p1
    assert 'codeName' not in p1

    assert '<c r="C33" s="2" t="inlineStr"><is><t>第3頁</t></is></c>' in p3
    assert '<c r="A3" s="1"><v>181</v></c>' in p3
    assert '<c r="C3" s="1"><v>211</v></c>' in p3
    assert '<c r="E32" s="1"><v>270</v></c>' in p3

    # 既有分頁 byte 不變
    with zipfile.ZipFile(REAL) as za, zipfile.ZipFile(OUT) as zb:
        untouched = 0
        for nm in za.namelist():
            if nm in ("[Content_Types].xml", "xl/workbook.xml",
                      "xl/_rels/workbook.xml.rels", "docProps/app.xml"):
                continue
            assert za.read(nm) == zb.read(nm), f"不該變卻變了：{nm}"
            untouched += 1
        print(f"原封未動的 part：{untouched} / {len(za.namelist())}")
        # printerSettings 全數保留（數量以基準檔為準）
        pa = len([n for n in za.namelist() if "printerSettings" in n])
        pb = len([n for n in zb.namelist() if "printerSettings" in n])
        assert pa == pb, (pa, pb)
        print(f"printerSettings 保留：{pb}")
        # calcPr 已加 fullCalcOnLoad
        assert 'fullCalcOnLoad="1"' in zb.read("xl/workbook.xml").decode()
        # app.xml 分頁數 = 基準 + 8
        base_sz = int(re.search(r'<vt:vector size="(\d+)" baseType="lpstr"',
                                za.read("docProps/app.xml").decode()).group(1))
        assert f'size="{base_sz + 8}" baseType="lpstr"' in zb.read("docProps/app.xml").decode()

    print("\n✅ M1 全部檢查通過 ->", OUT)


if __name__ == "__main__":
    main()
