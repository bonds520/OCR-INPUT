"""把主檔單向複寫（覆蓋）到公用資料夾。

失敗（未掛載、目標被 Excel 開著、權限不足…）只回報警告，不影響本機寫入。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import config


def publish() -> dict:
    """回傳 {"enabled", "ok", "message"}。呼叫端在本機 save 成功後於鎖內呼叫。"""
    dst = config.PUBLISH_PATH
    if dst is None:
        return {"enabled": False, "ok": True, "message": ""}
    if not config.XLSX_PATH.exists():
        return {"enabled": True, "ok": False, "message": "本機主檔不存在"}
    if not dst.parent.exists():
        return {"enabled": True, "ok": False,
                "message": f"公用資料夾不存在或未掛載：{dst.parent}"}
    tmp = dst.with_name(dst.name + ".tmp")
    try:
        shutil.copy2(config.XLSX_PATH, tmp)
        os.replace(tmp, dst)               # 同目錄置換，儘量原子
        return {"enabled": True, "ok": True, "message": f"已複寫至 {dst}"}
    except (PermissionError, OSError) as e:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        hint = "（目標檔可能正被 Excel 開啟）" if isinstance(e, PermissionError) else ""
        return {"enabled": True, "ok": False,
                "message": f"複寫公用資料夾失敗：{e}{hint}"}
