#!/bin/bash
# 数据库维护 — 每周 VACUUM
set -euo pipefail
for db in state.db kanban.db; do
  dbpath="$HOME/.hermes/$db"
  if [ -f "$dbpath" ]; then
    python3 -c "import sqlite3; conn=sqlite3.connect('$dbpath'); conn.execute('VACUUM'); conn.close()"
    echo "[vacuum] $db: OK"
  fi
done
