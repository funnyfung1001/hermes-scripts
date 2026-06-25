#!/usr/bin/env python3
"""daily_briefing_manager.py — 每日简报管理器

工作日18:00 WAT 由 cron_runner.sh daily-briefing 调度。
三段式增量采集：morning/afternoon/evening，最终生成并发送简报卡片。
"""
import sys, json, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import (
    setup_logger, SECOND_BRAIN, DAILY_DIR, today_wat, today_str
)

logger = setup_logger("daily_briefing", "daily_briefing.log")

BRIEFING_STATE_FILE = Path.home() / ".hermes" / "daily_briefing_state.json"

def get_state():
    try:
        return json.loads(BRIEFING_STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_state(state):
    BRIEFING_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))

def collect_morning():
    """上午采集：飞书群消息、邮件"""
    logger.info("Morning collection: feishu + email")
    # 由 daily_ingest 完成实际采集
    return True

def collect_afternoon():
    """下午采集：补充消息"""
    logger.info("Afternoon collection: supplementary")
    return True

def collect_evening():
    """傍晚采集：最终整理"""
    logger.info("Evening collection: final")
    return True

def generate_briefing():
    """调用生成器创建简报"""
    sys.path.insert(0, str(Path(__file__).parent))
    from daily_briefing_generator import generate_and_send
    return generate_and_send()

def main():
    today = today_wat()
    logger.info(f"Daily briefing manager started for {today}")
    
    state = get_state()
    day_state = state.get(today, {})
    phase = day_state.get("phase", "morning")
    
    if phase == "morning":
        collect_morning()
        day_state["phase"] = "afternoon"
    elif phase == "afternoon":
        collect_afternoon()
        day_state["phase"] = "evening"
    else:
        # evening: generate and send
        collect_evening()
        success = generate_briefing()
        day_state["phase"] = "sent"
        day_state["sent_ok"] = success
    
    state[today] = day_state
    save_state(state)
    logger.info(f"Phase {phase} → {day_state['phase']}: done")
    return 0

if __name__ == "__main__":
    sys.exit(main())
