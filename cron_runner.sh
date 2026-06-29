#!/bin/bash
# Hermes 统一定时任务入口 — 由系统 crontab 调度
# v5: 用 scheduler + health_check 替换 daemon
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

LOG_DIR="$HOME/.hermes/cron/output"
mkdir -p "$LOG_DIR"

CMD="${1:-help}"

case "$CMD" in
  scheduler)
    # ❌ 废弃：改用 engine.py（持久守护进程）
    echo "Deprecated: use 'engine' command instead"
    exit 1
    ;;

  engine-start)
    # 引擎启动 — 持久守护进程（替换 scheduler）
    # 不删锁文件，不设 timeout（engine 自己管理循环+超时）
    exec nohup python3 engine.py >> ~/.hermes/logs/engine.log 2>&1
    ;;

  engine-health)
    # 引擎健康检查 — 检查 PID 锁是否存活
    if [ -f "$HOME/.hermes/.engine.pid" ]; then
        OLD_PID=$(cat "$HOME/.hermes/.engine.pid")
        if kill -0 "$OLD_PID" 2>/dev/null; then
            echo "Engine running (PID $OLD_PID)"
            exit 0
        fi
    fi
    echo "Engine NOT running, restarting..."
    exec $0 engine-start
    ;;
  health-check)
    # 健康检查 — 每5分钟独立 watchdog
    exec timeout 60 python3 health_check.py
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
    # 互联网情报采集 — 每8小时
    rm -f "$HOME/.hermes/.internet_intel.lock" 2>/dev/null || true
    exec timeout 600 python3 internet_intel.py
    ;;
  sync-toolbox)
    # C&I 工具箱同步 — 每天5:00
    exec timeout 300 python3 sync_ci_toolbox.py
    ;;
  digest)
    # 知识消化 — 每12小时（scheduler 已有 deep_digest，本脚本仅做历史补采）
    rm -f "$HOME/hermes-business/第二大脑/raw/digest/.digest.lock" 2>/dev/null || true
    exec timeout 600 python3 daemon_digest.py
    ;;
  ingest)
    # 知识灌入 — 每天6:00
    exec python3 daily_ingest.py
    ;;
  patrol)
    # 巡检 — 每2小时半点
    exec python3 patrol_duty.py
    ;;
  self-health)
    # 系统自检（每小时）— 检查 cron + 操作系统级健康
    # 不修复，仅检查+告警
    exec timeout 30 python3 recovery_system.py --check-only --layers 0,1
    ;;

  state-snapshot)
    # 系统快照（每4小时）— 保存系统状态 + 今日学习更新
    # 由 cron_runner.sh state-snapshot 调用
    exec timeout 30 python3 state_manager.py snapshot
    ;;

  help|*)
    echo "Usage: $0 {engine-start|engine-health|health-check|self-health|state-snapshot|collect-minutes|daily-briefing|internet-intel|sync-toolbox|digest|ingest|patrol}"
    exit 1
    ;;
esac
