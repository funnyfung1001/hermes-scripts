#!/usr/bin/env python3
"""patrol_duty.py — 巡检脚本

由 cron_runner.sh patrol 调度（每2小时半点）。
检查系统关键组件状态。
"""
import sys, json, os, subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import setup_logger, HERMES

logger = setup_logger("patrol", "patrol.log")

def check_gateway():
    # 检查 Gateway 进程是否存在
    r = subprocess.run(
        ["ps", "aux"],
        capture_output=True, text=True, timeout=10
    )
    ok = "hermes gateway run" in r.stdout or "gateway run" in r.stdout
    if not ok:
        logger.warning("Gateway process not found")
    return ok

def check_disk():
    r = subprocess.run(["df", "-h", "/"], capture_output=True, text=True)
    return r.stdout.strip().split("\n")[-1] if r.stdout else "?"

def main():
    logger.info("Patrol start")
    issues = []
    
    if not check_gateway():
        issues.append("Gateway not running")
    
    disk = check_disk()
    logger.info(f"Disk: {disk}")
    
    if issues:
        logger.warning(f"Issues: {', '.join(issues)}")
    else:
        logger.info("All clear")
    return len(issues)

if __name__ == "__main__":
    sys.exit(main())
