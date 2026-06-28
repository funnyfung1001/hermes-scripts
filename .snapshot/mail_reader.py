#!/usr/bin/env python3
"""mail_reader.py — 邮件采集（读取 O365 邮件）

从 D:/hermes_data/email/ 读取已采集的邮件数据。
由 daemon_worker.py 定时调度。
"""
import sys, json
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import setup_logger, RAW_DIR, today_str

logger = setup_logger("mail_reader", "mail_reader.log")

# Windows 端的邮件数据目录
EMAIL_DATA_DIR = Path("/mnt/d/hermes_data/email")

def collect_today_email():
    """读取今日邮件数据，存入第二大脑（兼容滞后调度，检查最近3天的新文件）"""
    target = RAW_DIR / "email"
    target.mkdir(parents=True, exist_ok=True)
    
    if not EMAIL_DATA_DIR.exists():
        logger.warning(f"Email data dir not found: {EMAIL_DATA_DIR}")
        return 0

    collected = 0
    # 检查最近3天，防止 daemon 调度滞后或跳 tick 漏文件
    today = datetime.now()
    dates_to_check = set()
    for delta in range(3):
        d = (today - timedelta(days=delta)).strftime("%Y-%m-%d")
        dates_to_check.add(d)
    
    # 同时加载目标目录中已有的文件名，避免不必要的覆盖写
    existing_in_target = set(f.name for f in target.iterdir() if f.is_file())
    
    for d_str in dates_to_check:
        for f in EMAIL_DATA_DIR.glob(f"*{d_str}*"):
            try:
                if f.name in existing_in_target:
                    # 已存在则比较大小，Windows 端文件更大说明有新内容
                    target_f = target / f.name
                    if target_f.exists() and target_f.stat().st_size >= f.stat().st_size:
                        continue
                content = f.read_text()
                out = target / f.name
                out.write_text(content)
                collected += 1
                logger.info(f"Email collected: {f.name} ({len(content)} chars)")
            except Exception as e:
                logger.warning(f"Failed to read {f.name}: {e}")
    
    return collected

def main():
    logger.info("Mail reader start")
    count = collect_today_email()
    logger.info(f"Mail reader done: {count} files")
    return 0

if __name__ == "__main__":
    sys.exit(main())
