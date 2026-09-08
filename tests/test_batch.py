"""Plan C 批次邏輯測試（OCR 以假資料替換，快速）。"""
import datetime as dt
import shutil
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import batch as B                       # noqa: E402
from app.ocr import OcrResult, Cell              # noqa: E402
from app.sheetgen import generate_for_date       # noqa: E402
from app.writeback import write_weights          # noqa: E402
from app.xlsxpkg import XlsxPackage              # noqa: E402

REAL = Path("/opt/ai/OCR-INPUT/金紙秤重表.xlsx")
WORK = Path("/tmp/claude-1000/-opt-ai-OCR-INPUT/6471c05f-afb0-4371-800e-87f39a33a8b9"
           "/scratchpad/batch_work.xlsx")
OUT = Path(__file__).resolve().parents[1] / "sample" / "金紙秤重表_C測試.xlsx"

FAKE = {
    "神_1.jpg": OcrResult("9月25日", "神明", [Cell(1, 8.4, "high"), Cell(2, 7.4, "high")], ""),
    "先_1.jpg": OcrResult("9月25日", "先靈", [Cell(1, 9.6, "high"), Cell(3, 5.0, "low")], ""),
    # 實際是第 2 頁（編號 91 起），但表頭無頁次資訊 -> 仍被建議到 先靈-20990925，造成衝突
    "先_p2.jpg": OcrResult("9月25日", "先靈", [Cell(91, 1.1, "high"), Cell(92, 2.2, "high")], ""),
}


def main():
    # 準備：主檔複本 + 先產生 20990925 分頁
    shutil.copy2(REAL, WORK)
    pkg = XlsxPackage(WORK)
    generate_for_date(pkg, dt.date(2099, 9, 25), {"神明": 1, "先靈": 1})
    pkg.save(WORK)
    sheets = XlsxPackage(WORK).sheet_names()

    store = B.BatchStore()
    files = [("神_1.jpg", b"x"), ("先_1.jpg", b"x"), ("先_p2.jpg", b"x")]
    bt = store.create(2099, files)
    assert bt.dir.exists() and len(bt.items) == 3

    pathmap = {str(it.image_path): FAKE[it.filename] for it in bt.items}
    B.recognize = lambda p: pathmap[str(p)]

    for it in bt.items:
        B.run_ocr(it, bt.year, sheets)
    B.mark_conflicts(bt)

    by = {i.filename: i for i in bt.items}
    assert by["神_1.jpg"].status == "ocr_done"
    assert by["神_1.jpg"].target_sheet == "神明-20990925"
    assert by["先_1.jpg"].target_sheet == "先靈-20990925"
    # 兩張先靈都指到 先靈-20990925 -> 衝突
    assert by["先_1.jpg"].conflict and by["先_p2.jpg"].conflict
    assert not by["神_1.jpg"].conflict
    print("路由 + 衝突偵測 OK")

    # 解掉衝突：先_dup 改指續頁（先產生一張）
    pkg = XlsxPackage(WORK)
    generate_for_date(pkg, dt.date(2099, 9, 25), {"神明": 1, "先靈": 2})
    pkg.save(WORK)
    by["先_p2.jpg"].target_sheet = "先靈-20990925-2"
    B.mark_conflicts(bt)
    assert not any(i.conflict for i in bt.items)
    print("改指續頁後衝突解除 OK")

    # 模擬 /api/batch/{id}/write 的交易：一次載入、逐項寫、一次存
    for it in bt.items:
        it.weights = {str(c["no"]): c["weight"] for c in it.cells}
        it.status = "confirmed"
    pkg = XlsxPackage(WORK)
    pkg.backup.__doc__  # noop
    results = []
    for it in bt.items:
        w = {int(k): v for k, v in it.weights.items()}
        s = write_weights(pkg, it.target_sheet, w, it.overwrite)
        results.append(s)
    pkg.save(OUT)
    print("批次寫入:", results)

    v = XlsxPackage(OUT)
    import re
    from app.writeback import WEIGHT_REFS
    def wcells(sheet):
        xml = v.read_part(v.worksheet_part(sheet)).decode()
        allv = dict(re.findall(r'<c r="([BDF]\d+)"(?![^>]*t="s")[^>]*><v>([0-9.]+)</v>', xml))
        return {k: val for k, val in allv.items() if k in set(WEIGHT_REFS)}
    assert wcells("神明-20990925") == {"B3": "8.4", "B4": "7.4"}, wcells("神明-20990925")
    assert wcells("先靈-20990925") == {"B3": "9.6", "B5": "5"}, wcells("先靈-20990925")
    assert wcells("先靈-20990925-2") == {"B3": "1.1", "B4": "2.2"}, wcells("先靈-20990925-2")

    store.drop(bt.id)
    assert not bt.dir.exists()
    print("暫存目錄清除 OK")
    print("\n✅ Plan C 批次邏輯全部通過 ->", OUT)


if __name__ == "__main__":
    main()
