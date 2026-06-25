#!/usr/bin/env python3
"""meeting_minutes_pipeline.py — 晨会纪要采集管道

从飞书妙记（Minutes）提取会议记录，写入第二大脑。
由 cron_runner.sh collect-minutes 调度（工作日10:15 WAT）。
"""
import sys, json, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import (
    setup_logger, SECOND_BRAIN, today_wat, today_str
)

logger = setup_logger("meeting_minutes", "meeting_minutes.log")

def _lark_api(method, path, params=None):
    """通过 subprocess 调用 lark-cli（不走 config_shared 的旧版路径逻辑）"""
    import subprocess, shlex
    cmd = ["lark-cli", "api", method, path]
    if params:
        cmd.extend(["--params", shlex.quote(json.dumps(params))])
    cmd.extend(["--as", "user"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return {"error": r.stderr.strip()[:200]}
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except Exception as e:
        return {"error": str(e)}

def get_today_minutes():
    """获取今天的最新会议妙记
    
    飞书 Minutes API: minutes/v1/minutes
    lark-cli 1.0.57 自动加 /open-apis/ 前缀，所以传相对路径即可
    """
    result = _lark_api("GET", "minutes/v1/minutes", {"page_size": 5})
    if not isinstance(result, dict) or not result.get("ok"):
        logger.warning(f"Minutes API failed: {str(result.get('error', result))[:100]}")
        # 尝试 vc recording 接口
        result2 = _lark_api("GET", "vc/v1/meeting_recording", {"page_size": 5})
        if isinstance(result2, dict) and result2.get("ok"):
            items = result2.get("data", {}).get("items", [])
            if isinstance(items, list):
                return items
        return []
    
    items = result.get("data", {}).get("items", [])
    if not isinstance(items, list):
        logger.info("No meeting minutes found")
        return []
    return items

def save_minutes(minute):
    """保存会议纪要到第二大脑，避免重复保存"""
    if not isinstance(minute, dict):
        logger.warning(f"Invalid minute data: {type(minute)}")
        return None
    minute_id = minute.get("id", "unknown")
    topic = minute.get("topic", "未命名会议")
    # 妙记的 create_time 是时间戳
    create_ts = minute.get("create_time", 0)
    if isinstance(create_ts, (int, float)) and create_ts > 0:
        date = datetime.datetime.fromtimestamp(create_ts / 1000).strftime("%Y-%m-%d")
    else:
        date = str(create_ts)[:10] if create_ts else today_str()
    
    rd = SECOND_BRAIN / "raw" / "meetings"
    rd.mkdir(parents=True, exist_ok=True)
    
    fpath = rd / f"meeting_{date}_{minute_id[:12]}.json"
    if fpath.exists():
        logger.info(f"Minutes already saved: {fpath.name}")
        return fpath
    
    fpath.write_text(json.dumps(minute, ensure_ascii=False, indent=2))
    logger.info(f"Saved minutes: {topic[:30]} → {fpath.name}")
    return fpath

def main():
    today = today_wat()
    logger.info(f"Meeting minutes pipeline running for {today}")
    
    meetings = get_today_minutes()
    saved = 0
    for m in meetings:
        # 判断日期
        create_ts = m.get("create_time", 0)
        if isinstance(create_ts, (int, float)) and create_ts > 0:
            mdate = datetime.datetime.fromtimestamp(create_ts / 1000).strftime("%Y-%m-%d")
        else:
            mdate = str(m.get("date", ""))[:10]
        
        if mdate != today:
            logger.debug(f"Skip: date={mdate} != today={today}")
            continue
        
        save_minutes(m)
        saved += 1
    
    logger.info(f"Pipeline done: {saved} meetings saved")
    return 0

if __name__ == "__main__":
    sys.exit(main())
