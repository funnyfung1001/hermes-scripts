#!/bin/bash
# ================================================================
# WSL 启动自恢复脚本 — 由 Windows Task Scheduler 触发
# 功能：重启时自动恢复 scripts、第二大脑、Gateway、Hermes cron
# ================================================================
set -euo pipefail

LOG_FILE="$HOME/.hermes/logs/startup_recovery.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== WSL Startup Recovery: $(date) ==="

# ── 1. 恢复 ~/.hermes/scripts/ ────────────────────────────────
SCRIPTS_DIR="$HOME/.hermes/scripts"
BACKUP_DIR="$HOME/.hermes/scripts-backup"

if [ ! -f "$SCRIPTS_DIR/cron_runner.sh" ]; then
    echo "[scripts] Detected missing scripts. Restoring from backup..."
    if [ -d "$BACKUP_DIR/.git" ]; then
        cd "$BACKUP_DIR" && git pull 2>/dev/null || true
        cp "$BACKUP_DIR"/*.py "$SCRIPTS_DIR/" 2>/dev/null || true
        cp "$BACKUP_DIR"/*.sh "$SCRIPTS_DIR/" 2>/dev/null || true
        chmod +x "$SCRIPTS_DIR"/*.sh 2>/dev/null || true
        echo "[scripts] Restored $(ls "$SCRIPTS_DIR"/*.py "$SCRIPTS_DIR"/*.sh 2>/dev/null | wc -l) files"
    else
        echo "[scripts] WARNING: backup repo not found at $BACKUP_DIR"
    fi
else
    echo "[scripts] OK - already present"
fi

# ── 2. 恢复第二大脑目录 ~/hermes-business/ ──────────────────────
SECOND_BRAIN="$HOME/hermes-business/第二大脑"
if [ ! -d "$SECOND_BRAIN/raw/feishu" ]; then
    echo "[second_brain] Recreating directory structure..."
    mkdir -p "$SECOND_BRAIN"/{raw/{feishu,email,whatsapp,tiktok,meetings},wiki/{people,projects,companies,market,products,processes},daily,weekly}
    touch "$SECOND_BRAIN"/{INDEX.md,PEOPLE.md,TIMELINE.md}
    echo "[second_brain] Done"
else
    echo "[second_brain] OK - already present"
fi

# ── 3. 启动 Gateway（如果未运行） ──────────────────────────────
if ! pgrep -f "hermes gateway run" > /dev/null 2>&1; then
    echo "[gateway] Starting Hermes Gateway..."
    nohup hermes gateway run > "$HOME/.hermes/logs/gateway.log" 2>&1 &
    # 等5秒确认启动
    sleep 5
    if pgrep -f "hermes gateway run" > /dev/null 2>&1; then
        echo "[gateway] Started OK (PID: $(pgrep -f 'hermes gateway run' | head -1))"
    else
        echo "[gateway] FAILED to start"
    fi
else
    echo "[gateway] OK - already running (PID: $(pgrep -f 'hermes gateway run' | head -1))"
fi

# ── 4. 恢复 Hermes cron 作业（如果丢失） ───────────────────────
# llama-server-watchdog
if ! hermes cron list 2>/dev/null | grep -q "llama-server-watchdog"; then
    echo "[cron] Restoring llama-server-watchdog..."
    hermes cron create --schedule "*/5 * * * *" \
        --name "llama-server-watchdog" \
        --no-agent 2>/dev/null || true
fi

# openviking-watchdog
if ! hermes cron list 2>/dev/null | grep -q "openviking-watchdog"; then
    echo "[cron] Restoring openviking-watchdog..."
    hermes cron create --schedule "*/5 * * * *" \
        --name "openviking-watchdog" \
        --no-agent 2>/dev/null || true
fi

# Kanban 阻塞自愈
if ! hermes cron list 2>/dev/null | grep -q "kanban-blocked"; then
    echo "[cron] Restoring kanban-blocked-alert..."
    hermes cron create --schedule "*/5 * * * *" \
        --name "kanban-blocked-alert" \
        --no-agent 2>/dev/null || true
fi

# 二狗巡检
if ! hermes cron list 2>/dev/null | grep -q "二狗.*巡检\|patrol"; then
    echo "[cron] Restoring er-gou patrol..."
    hermes cron create --schedule "*/30 * * * *" \
        --name "er-gou-patrol" \
        --no-agent 2>/dev/null || true
fi

echo "[cron] Done"

# ── 5. 健康报告 ────────────────────────────────────────────────
# ── 6. 配置快照（确保远程同步正常） ──────────────────────────
echo "[snapshot] Running daily config snapshot..."
python3 "$SCRIPTS_DIR/daily_config_snapshot.py" 2>/dev/null || true

echo ""
echo "=== Recovery Summary: $(date) ==="
echo "scripts: $(ls "$SCRIPTS_DIR"/*.py "$SCRIPTS_DIR"/*.sh 2>/dev/null | wc -l) files"
echo "second_brain: $([ -d "$SECOND_BRAIN/raw/feishu" ] && echo 'OK' || echo 'MISSING')"
echo "gateway: $(pgrep -f 'hermes gateway' | head -1 || echo 'NOT RUNNING')"
echo "cron jobs: $(hermes cron list 2>/dev/null | grep -c 'Job ID' || echo '0')"
echo "=========================================="
