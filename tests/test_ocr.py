"""M2：對樣本照片跑 OCR，與人工標準答案逐格比對，輸出準確率。

先把樣本放到 /opt/ai/OCR-INPUT/samples/：
  神明_20260905_a.jpg  神明_20260905_b.jpg  先靈_20260905.jpg
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.ocr import recognize  # noqa: E402

SAMPLES = Path("/opt/ai/OCR-INPUT/samples")

# 人工標準答案（no -> weight）；未列出者視為空白。標 # 者為人工判讀存疑。
GROUND_TRUTH = {
    "20260905.jpg": {   # 神明(白色) 9/5, 1-18
        1: 11.6, 2: 13.6, 3: 14.4, 4: 13.0, 5: 15.8, 6: 12.2, 7: 13.0, 8: 14.0,
        9: 12.4, 10: 10.4, 11: 14.6, 12: 13.2, 13: 10.0, 14: 11.8, 15: 10.6,
        16: 7.2, 17: 11.2, 18: 11.4,
    },
    "20260905_B.jpg": {  # 先靈(黃色) 9/5, 1-47
        1: 11.8, 2: 14.2, 3: 12.6, 4: 10.6, 5: 10.2, 6: 11.6, 7: 15.4, 8: 10.2,
        9: 8.8, 10: 11.0, 11: 9.4, 12: 10.0, 13: 11.6, 14: 10.4, 15: 9.2,
        16: 7.2, 17: 14.4, 18: 9.8, 19: 10.4, 20: 13.0, 21: 10.6, 22: 10.2,
        23: 6.8, 24: 4.8, 25: 5.6, 26: 4.8, 27: 9.6, 28: 10.8, 29: 9.8, 30: 2.6,
        31: 7.8, 32: 5.0, 33: 10.6, 34: 9.6, 35: 7.4, 36: 10.0, 37: 7.0,
        38: 10.6, 39: 9.6, 40: 4.2, 41: 6.0, 42: 4.8, 43: 9.4, 44: 8.4, 45: 9.2,
        46: 8.0, 47: 10.0,
    },
    "20260906.jpg": {    # 先靈(黃色) 9/6, 1-55, #23 整格塗銷
        1: 8.4, 2: 7.4, 3: 6.6, 4: 7.2, 5: 7.8, 6: 9.6, 7: 8.8, 8: 7.6, 9: 9.2,
        10: 11.8, 11: 12.4, 12: 5.2, 13: 10.0, 14: 9.4, 15: 8.8, 16: 9.6,
        17: 7.2, 18: 9.8, 19: 11.8, 20: 8.8, 21: 10.8, 22: 4.0, 24: 10.0,
        25: 9.2, 26: 7.6, 27: 5.6, 28: 12.0, 29: 4.0, 30: 10.4,
        31: 8.2, 32: 8.0, 33: 9.6, 34: 19.6, 35: 11.4, 36: 4.2, 37: 11.0,
        38: 6.0, 39: 6.4, 40: 9.8, 41: 8.0, 42: 8.8, 43: 5.0, 44: 8.8, 45: 8.2,
        46: 4.8, 47: 9.6, 48: 9.2, 49: 8.6, 50: 8.0, 51: 2.4, 52: 6.8, 53: 10.6,
        54: 6.0, 55: 7.0,
    },
}


def run_one(name, gt):
    path = SAMPLES / name
    if not path.exists():
        print(f"  略過（找不到檔案）：{path}")
        return None
    t0 = time.time()
    res = recognize(path)
    dt = time.time() - t0
    got_w = {c.no: c.weight for c in res.cells if not c.voided}
    voided = {c.no for c in res.cells if c.voided}
    low = {c.no for c in res.cells if c.confidence == "low"}

    all_no = sorted(set(gt) | set(got_w))
    ok = miss = wrong = extra = 0
    lines = []
    for no in all_no:
        g = gt.get(no)
        p = got_w.get(no)
        if g is not None and p is not None and abs(g - p) < 1e-6:
            ok += 1
            continue
        if g is not None and p is None:
            miss += 1
            lines.append(f"    #{no}: 漏讀  應={g}")
        elif g is None and p is not None:
            extra += 1
            lines.append(f"    #{no}: 多讀  得={p}")
        else:
            wrong += 1
            flag = " [low]" if no in low else ""
            lines.append(f"    #{no}: 錯   應={g}  得={p}{flag}")
    tot = len(gt)
    print(f"\n=== {name}  ({dt:.1f}s) ===")
    print(f"  表頭: date={res.date_text!r} category={res.category!r}")
    vd = sorted(voided)
    print(f"  正確 {ok}/{tot}   錯 {wrong}   漏 {miss}   多讀 {extra}   "
          f"低信心 {len(low)}   判為塗銷 {vd}")
    for ln in lines:
        print(ln)
    return ok, tot, wrong, miss, extra


def main():
    tot_ok = tot_all = tot_wrong = tot_miss = tot_extra = 0
    for name, gt in GROUND_TRUTH.items():
        r = run_one(name, gt)
        if r:
            tot_ok += r[0]; tot_all += r[1]; tot_wrong += r[2]
            tot_miss += r[3]; tot_extra += r[4]
    if tot_all:
        print(f"\n===== 總計 =====")
        print(f"逐格正確率: {tot_ok}/{tot_all} = {tot_ok/tot_all*100:.1f}%")
        print(f"錯 {tot_wrong} / 漏 {tot_miss} / 多讀 {tot_extra}")


if __name__ == "__main__":
    main()
