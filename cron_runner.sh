#!/bin/bash
# Hermes 统一定时任务入口 — 由系统 crontab 调度
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

LOG_DIR="$HOME/.hermes/cron/output"
mkdir -p "$LOG_DIR"

CMD="${1:-help}"

case "$CMD" in
  daemon)
    # 守护进程 — 每30分钟
    exec python3 daemon_worker.py daemon
    ;;
  collect-minutes)
    # 晨会纪要采集 — 工作日10:15 WAT
    exec python3 meeting_minutes_pipeline.py
    ;;
  daily-briefing)
    # 每日简报采集+生成+发送 — 工作日18:00 WAT
    exec python3 daily_briefing_manager.py
    ;;
  internet-intel)
    # 互联网情报采集 — 每3小时
    exec python3 internet_intel.py
    ;;
  sync-toolbox)
    # C&I 工具箱同步 — 每天5:00
    exec python3 sync_ci_toolbox.py
    ;;
  digest)
    # 知识消化 — 每2小时(6-23点)
    exec python3 daemon_digest.py
    ;;
  ingest)
    # 知识灌入 — 每天6:00
    exec python3 daily_ingest.py
    ;;
  patrol)
    # 巡检 — 每2小时半点
    exec python3 patrol_duty.py
    ;;
  collect-email)
    # 检查邮件采集状态
    echo "[cron_runner] collect-email: stub"
    ;;
  help|*)
    echo "Usage: $0 {daemon|collect-minutes|daily-briefing|internet-intel|sync-toolbox|digest|ingest|patrol|collect-email}"
    exit 1
    ;;
esac
