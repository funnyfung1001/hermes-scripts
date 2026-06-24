#!/usr/bin/env python3
"""meeting_minutes_pipeline.py — 晨会纪要采集管道

从飞书 VC 妙记提取会议记录，写入第二大脑。
由 cron_runner.sh collect-minutes 调度（工作日10:15 WAT）。
"""
import sys, json, datetime, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import (
    setup_logger, lark_cli_user, SECOND_BRAIN, today_wat, today_str
)

logger = setup_logger("meeting_minutes", "meeting_minutes.log")

def get_latest_minutes():
    """获取飞书最新会议妙记"""
    result = lark_cli_user("GET", "open-apis/vc/v1/meeting_recording", timeout=60)
    if isinstance(result, dict) and "error" in result:
        logger.error(f"VC API error: {result['error']}")
        return []
    items = result.get("data", {}).get("items", [])
    if not items:
        logger.info("No meeting recordings found")
        return []
    return items

def save_minutes(meeting):
    """保存会议纪要到第二大脑"""
    meeting_id = meeting.get("id", "unknown")
    topic = meeting.get("topic", "未命名会议")
    date = meeting.get("date", today_str())
    
    rd = SECOND_BRAIN / "raw" / "meetings"
    rd.mkdir(parents=True, exist_ok=True)
    
    fpath = rd / f"meeting_{date}_{meeting_id[:12]}.json"
    fpath.write_text(json.dumps(meeting, ensure_ascii=False, indent=2))
    logger.info(f"Saved minutes: {fpath}")
    return fpath

def main():
    today = today_wat()
    logger.info(f"Meeting minutes pipeline running for {today}")
    
    meetings = get_latest_minutes()
    saved = 0
    for m in meetings:
        mdate = m.get("date", "")
        if mdate != today:
            logger.debug(f"Skip meeting date={mdate} != today={today}")
            continue
        save_minutes(m)
        saved += 1
    
    logger.info(f"Pipeline done: {saved} meetings saved")
    return 0

if __name__ == "__main__":
    sys.exit(main())
