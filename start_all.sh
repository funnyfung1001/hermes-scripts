#!/bin/bash
# start_all.sh — WSL 启动时自动恢复 Hermes 后台服务
# 由 ~/.bashrc 触发，后台运行，不阻塞终端
#
# 启动：Gateway → llama-server (32B) → OpenViking
# 安全：每个服务先检查是否已在运行

set -euo pipefail

LOG="$HOME/.hermes/logs/auto_recovery.log"
exec >> "$LOG" 2>&1
echo ""
echo "=== Auto Recovery: $(date) ==="

# ── Gateway ──
if ! pgrep -f 'hermes gateway run' > /dev/null 2>&1; then
    echo "[gateway] Starting..."
    nohup hermes gateway run > "$HOME/.hermes/logs/gateway.log" 2>&1 &
    sleep 5
    if pgrep -f 'hermes gateway run' > /dev/null 2>&1; then
        echo "[gateway] OK (PID: $(pgrep -f 'hermes gateway run' | head -1))"
    else
        echo "[gateway] FAILED"
    fi
else
    echo "[gateway] already running"
fi

# ── llama-server (32B) ──
if ! pgrep -f llama-server > /dev/null 2>&1; then
    echo "[llama-server] Starting..."
    fuser -k 8080/tcp 2>/dev/null || true
    sleep 1
    export CUDA_VISIBLE_DEVICES=0
    nohup llama-server -m ~/llama.cpp/models/Qwen2.5-32B-Instruct-Q4_K_M.gguf \
      --host 0.0.0.0 --port 8080 -ngl 99 -c 8192 --no-mmap --timeout 300 \
      > /tmp/llama-server.log 2>&1 &
    # 等加载完成（最长60秒）
    for i in $(seq 1 20); do
        code=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 15 http://localhost:8080/health 2>/dev/null)
        if [ "$code" = "200" ]; then
            echo "[llama-server] OK (health=200)"
            break
        fi
        sleep 3
    done
    if ! pgrep -f llama-server > /dev/null 2>&1; then
        echo "[llama-server] FAILED - check /tmp/llama-server.log"
    fi
else
    echo "[llama-server] already running"
fi

# ── OpenViking ──
if ! curl -s --max-time 3 http://127.0.0.1:1933/health > /dev/null 2>&1; then
    echo "[openviking] Starting..."
    /home/funny/.hermes/hermes-agent/venv/bin/openviking-server \
        --host 127.0.0.1 --port 1933 \
        --config /home/funny/.openviking/ov.conf \
        > /home/funny/.hermes/logs/openviking.log 2>&1 &
    sleep 10
    if curl -s --max-time 5 http://127.0.0.1:1933/health > /dev/null 2>&1; then
        echo "[openviking] OK"
    else
        echo "[openviking] FAILED"
    fi
else
    echo "[openviking] already running"
fi

echo "=== Auto Recovery Done: $(date) ==="
