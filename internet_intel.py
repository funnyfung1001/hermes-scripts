#!/usr/bin/env python3
"""internet_intel.py — 互联网情报采集

由 cron_runner.sh internet-intel 调度（每3小时）。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from config_shared import setup_logger

logger = setup_logger("internet_intel", "internet_intel.log")

def main():
    logger.info("Internet intel collection tick")
    # 预留：未来接入 RSS/API 情报源
    return 0

if __name__ == "__main__":
    sys.exit(main())
