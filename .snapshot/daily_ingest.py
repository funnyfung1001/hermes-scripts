#!/usr/bin/env python3
"""daily_ingest.py — 每日摄入管道

由 cron_runner.sh ingest 调度（每天6:00）。
依次采集：WhatsApp → TikTok → 飞书群消息 → 飞书私聊 → 邮件
"""
import sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import setup_logger, RAW_DIR, today_str

logger = setup_logger("daily_ingest", "daily_ingest.log")

def step_whatsapp():
    """采集 WhatsApp"""
    logger.info("Step 1: WhatsApp (quick)")
    try:
        import daemon_worker as dw
        dw.collect_whatsapp()
    except Exception as e:
        logger.warning(f"WhatsApp failed: {e}")

def step_feishu():
    """采集飞书群消息"""
    logger.info("Step 2: Feishu groups")
    try:
        from config_shared import lark_cli_user
        result = lark_cli_user("GET", "open-apis/im/v1/messages", timeout=50)
        if isinstance(result, dict) and "error" not in result:
            fd = RAW_DIR / "feishu"
            fd.mkdir(parents=True, exist_ok=True)
            out = fd / f"群消息_{today_str()}.json"
            out.write_text(str(result))
    except Exception as e:
        logger.warning(f"Feishu failed: {e}")

def main():
    logger.info(f"Daily ingest start for {today_str()}")
    step_whatsapp()
    step_feishu()
    logger.info("Daily ingest done")
    return 0

if __name__ == "__main__":
    sys.exit(main())
