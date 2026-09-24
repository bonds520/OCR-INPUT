"""列印檢視：分頁名解析、頁次/編號範圍、日期格式、非法名稱、/print 路由。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.printview import BadSheetName, parse, render  # noqa: E402


def main():
    assert parse("先靈-20260925") == ("先靈", 9, 25, 1)
    assert parse("神明-20260105-3") == ("神明", 1, 5, 3)
    for bad in ("先靈-2026092", "其他-20260925", "先靈-20261345", "先靈-20260925-0",
                "先靈-20260925-x", "<script>", "先靈-20260925-2-3"):
        try:
            parse(bad)
            raise AssertionError(f"應拒絕：{bad}")
        except BadSheetName:
            pass
    print("分頁名解析 OK")

    h = render(["先靈-20260925", "先靈-20260925-2", "神明-20260105-3"])
    assert h.count('<section class="sheet">') == 3
    assert "9月25日" in h and "1月5日" in h and "先靈(黃色)" in h and "神明(白色)" in h
    assert "第1頁" in h and "第2頁" in h and "第3頁" in h
    secs = h.split('<section class="sheet">')[1:]
    nums = lambda s: [int(x) for x in re.findall(r"<td>(\d+)</td>", s)]
    assert nums(secs[0]) == list(range(1, 91)) or sorted(nums(secs[0])) == list(range(1, 91))
    assert min(nums(secs[1])) == 91 and max(nums(secs[1])) == 180     # 第2頁
    assert min(nums(secs[2])) == 181 and max(nums(secs[2])) == 270    # 第3頁
    # 每頁 32 列表格 + 1 列頁次；3 組編號/重量
    assert secs[0].count("<tr>") == 32
    assert secs[0].count("編號") == 3 and secs[0].count("重量") == 3
    print("版面內容 OK")

    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    r = c.get("/print", params={"sheets": "先靈-20260925,神明-20260925"})
    assert r.status_code == 200 and r.text.count('<section class="sheet">') == 2
    assert c.get("/print", params={"sheets": "亂寫"}).status_code == 422
    assert c.get("/print", params={"sheets": ""}).status_code == 422
    assert c.get("/print", params={"sheets": ",".join(["先靈-20260925"] * 101)}).status_code == 422
    print("/print 路由 OK")
    print("\n✅ 列印檢視測試通過")


if __name__ == "__main__":
    main()
