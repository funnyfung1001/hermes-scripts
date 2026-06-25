#!/usr/bin/env python3
"""feishu_all_collector.py — 飞书多源采集（v2）

通过 lark-cli 以 user 身份采集 Bitable/日历/云盘数据。
"""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import (
    setup_logger, lark_cli_user, RAW_DIR, today_str
)

logger = setup_logger("feishu_collector", "feishu_collector.log")

SOURCES = [
    ("bitable", "open-apis/bitable/v1/apps"),
    ("calendar", "open-apis/calendar/v4/calendars"),
    ("drive", "open-apis/drive/v1/files"),
]

def collect_source(name, path):
    result = lark_cli_user("GET", path, timeout=60)
    if isinstance(result, dict) and "error" in result:
        logger.warning(f"{name}: {result['error']}")
        return
    fd = RAW_DIR / "feishu"
    fd.mkdir(parents=True, exist_ok=True)
    out = fd / f"{name}_{today_str()}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    logger.info(f"{name}: collected")

def main():
    logger.info("Feishu all collector start")
    for name, path in SOURCES:
        collect_source(name, path)
    return 0

if __name__ == "__main__":
    sys.exit(main())
