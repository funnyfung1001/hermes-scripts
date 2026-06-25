#!/usr/bin/env python3
"""mail_reader.py — 邮件采集（读取 O365 邮件）

从 D:/hermes_data/email/ 读取已采集的邮件数据。
由 daemon_worker.py 定时调度。
"""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import setup_logger, RAW_DIR, today_str

logger = setup_logger("mail_reader", "mail_reader.log")

# Windows 端的邮件数据目录
EMAIL_DATA_DIR = Path("/mnt/d/hermes_data/email")

def collect_today_email():
    """读取今日邮件数据，存入第二大脑"""
    today = today_str()
    target = RAW_DIR / "email"
    target.mkdir(parents=True, exist_ok=True)
    
    collected = 0
    if not EMAIL_DATA_DIR.exists():
        logger.warning(f"Email data dir not found: {EMAIL_DATA_DIR}")
        return collected
    
    for f in EMAIL_DATA_DIR.glob(f"*{today}*"):
        try:
            content = f.read_text()
            out = target / f.name
            out.write_text(content)
            collected += 1
            logger.info(f"Email collected: {f.name}")
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
