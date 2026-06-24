#!/usr/bin/env python3
"""daemon_digest.py — 知识消化守护

由 cron_runner.sh digest 调度（每2小时6-23点）。
处理新采集的 raw 数据，生成结构化摘要到 wiki/。
"""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import (
    setup_logger, SECOND_BRAIN, RAW_DIR, WIKI_DIR, today_str
)

logger = setup_logger("daemon_digest", "daemon_digest.log")

def collect_recent_raw(days=2):
    """收集最近 days 天的 raw 数据"""
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(days=days)
    results = []
    for raw_type in ["feishu", "whatsapp", "meetings"]:
        d = RAW_DIR / raw_type
        if not d.exists():
            continue
        for f in sorted(d.iterdir(), reverse=True):
            if not f.is_file():
                continue
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                break
            results.append(f)
        if len(results) > 10:
            break
    return results

def digest_file(fpath):
    """将单个原始文件处理为结构化摘要"""
    try:
        content = fpath.read_text(encoding="utf-8")[:3000]
    except Exception:
        return None
    
    # 简单分类
    topic = "general"
    if "meeting" in fpath.name or "meet" in fpath.stem:
        topic = "meeting"
    elif "whatsapp" in fpath.stem or "wa_" in fpath.stem:
        topic = "chat"
    elif "feishu" in fpath.stem:
        topic = "feishu"
    
    # 保存摘要
    digest = {
        "source": str(fpath),
        "topic": topic,
        "date": today_str(),
        "size": len(content),
        "preview": content[:500]
    }
    
    digest_dir = RAW_DIR / "digest"
    digest_dir.mkdir(parents=True, exist_ok=True)
    out = digest_dir / f"{fpath.stem}_digest.json"
    out.write_text(json.dumps(digest, ensure_ascii=False, indent=2))
    return out

def main():
    logger.info("Daemon digest start")
    files = collect_recent_raw()
    count = 0
    for f in files:
        if digest_file(f):
            count += 1
    logger.info(f"Digested {count}/{len(files)} files")
    return 0

if __name__ == "__main__":
    sys.exit(main())
