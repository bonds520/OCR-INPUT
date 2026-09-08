# 金紙秤重 OCR 系統

管理 `金紙秤重表.xlsx`：產生空白秤重分頁供列印；活動後上傳紙本照片，用本機 vLLM 辨識手寫重量，人工複核後寫回對應分頁。

## 功能

1. **產生分頁** — 網頁輸入日期（可多筆），系統在 XLSX 產生 `神明-YYYYMMDD` / `先靈-YYYYMMDD` 一組（不足時補續頁 `-2`、`-3`…，續頁編號 91–180、181–270…）。列印由人工在 Excel 執行。
2. **上傳辨識（單張）** — 上傳一張秤重表照片 → OCR 出重量初稿 → 人工在網頁逐格對照原圖修正 → 選定目標分頁 → 寫回 `B/D/F` 欄。
3. **批次上傳** — 一次多張 + 填「作業年份」→ 背景逐張 OCR → 總表逐列點「複核」對照原圖修正、確認目標分頁（系統依年份+OCR日期/類別給建議，比不到留空）→「寫入已確認列」一次交易寫入（單次備份、單次存檔；部分失敗照寫其餘）。同一分頁被兩列指到會標紅擋下。

## 安裝

```bash
cd /opt/ai/OCR-INPUT/gold-paper-ocr
./setup.sh
```

需求：Python 3.11+、本機 vLLM（Qwen VLM）在 `http://localhost:8000/v1` 運行。

## 啟動

### 手動（開發）
```bash
./run.sh        # http://<本機IP>:8770
```

### systemd（正式，目前不設開機自啟）
```bash
sudo cp deploy/gold-paper-ocr.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start gold-paper-ocr        # 啟動
sudo systemctl status gold-paper-ocr
# 要開機自啟時再： sudo systemctl enable gold-paper-ocr
journalctl -u gold-paper-ocr -f           # 看記錄
```

瀏覽器開 `http://<本機IP>:8770`。

## 設定（環境變數）

| 變數 | 預設 | 說明 |
|---|---|---|
| `GPO_XLSX_PATH` | `/opt/ai/OCR-INPUT/金紙秤重表.xlsx` | 主檔路徑（日後改掛 SMB 改這裡） |
| `GPO_BACKUP_DIR` | `<主檔目錄>/backups` | 備份目錄，保留最近 30 份 |
| `GPO_VLLM_URL` | `http://localhost:8000/v1` | vLLM OpenAI 相容端點 |
| `GPO_VLLM_MODEL` | `/models/Qwen3.6-27B-FP8` | 模型 ID |

systemd 版本改 `deploy/gold-paper-ocr.service` 裡的 `Environment=`。

## 運作與安全

- **寫檔方式**：外科手術式 zip 注入 —— 只重寫索引檔與被改動的分頁，其餘 125 張分頁、印表機設定原封不動。
- 每次寫入前自動備份到 `GPO_BACKUP_DIR`。
- 寫入前偵測 `~$金紙秤重表.xlsx`（Excel 開啟鎖檔），存在則拒絕並提示先關閉 Excel。
- 所有寫入經單一鎖序列化，一次一筆。
- **寫入前請確保沒人在 Excel 開著主檔。**
- OCR 上傳的影像用完即刪，不留存。
- 辨識準確率約 93%（手寫），**務必逐格人工複核**；表頭「類別」判定不可靠，一律人工確認目標分頁。
- 目前無帳號權限，限內網使用。

## 專案結構

```
app/
  main.py       FastAPI：/api/sheets /api/generate /api/ocr /api/write
  config.py     設定（讀環境變數）
  xlsxpkg.py    OOXML 外科手術式讀寫
  sheetgen.py   由空白範本產生新分頁
  writeback.py  編號→儲存格對照、回填、覆蓋保護
  ocr.py        vLLM 呼叫、回應解析、驗證
web/index.html  單頁前端
deploy/gold-paper-ocr.service   systemd unit
tests/          test_xlsx / test_writeback（複本上跑）、test_ocr（需 samples/）
```

## 測試

```bash
./.venv/bin/python tests/test_xlsx.py        # 分頁產生
./.venv/bin/python tests/test_writeback.py   # 回填
./.venv/bin/python tests/test_batch.py       # 批次邏輯（OCR 用假資料）
./.venv/bin/python tests/test_ocr.py         # OCR 準確率（需 /opt/ai/OCR-INPUT/samples/*.jpg）
```
