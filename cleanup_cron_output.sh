#!/bin/bash
# 清理 cron output — 保留最近7天
set -euo pipefail
find "$HOME/.hermes/cron/output" -name "*.md" -mtime +7 -delete 2>/dev/null || true
