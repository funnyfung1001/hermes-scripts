---
name: system-recovery-procedure
description: Windows/WSL 重启后系统恢复标准操作流程 — 检查清单、逐项恢复、全量验证。加载此技能后按步骤执行，不用从头问用户情况。
tags: [wsl-recovery, gateway, llama-server, openviking, cron, lark-cli, pipeline-audit]
---

# 🔄 WSL/Windows 重启后系统恢复流程

> **前提**：用户重启了 Windows/WSL，当前消息已收到说明 Gateway 已上线。
> **原则**：先查 Git history 了解中断前任务，再按此清单逐项检查+恢复。
> **禁止**：不要问用户"需要检查什么"——直接按此清单执行。

## 第0步：查 Git history 了解中断前任务背景

这是最容易被跳过的一步，但用户明确要求不能跳过。

```bash
cd ~/.hermes/scripts-backup
git log --oneline -20
```

根据 Git 时间线判断：
- 如果有未 push 的修改 → 先 `git status` 确认
- 如果有中断的 commit → 记住中断时的任务内容
- 如果最近提交包含修复/备份 → 优先验证这些是否生效

**不要跳过 Git history 直接开始修复。** 用户抱怨过"我感觉这次重启损失了很多信息，你都忘了"。

## 第1步：恢复基础服务（3个并行启动）

### 1a. Gateway — 飞书消息通道
```bash
# 检查是否已在运行
ps aux | grep 'hermes gateway run' | grep -v grep

# 如果没在跑，启动（注意不要用 bg+notify，Gateway 是 daemon）
hermes gateway run --replace &
# 或
nohup hermes gateway run > ~/.hermes/logs/gateway.log 2>&1 &
```

### 1b. llama-server — 本地 32B 模型
```bash
# 先清理旧进程和端口
fuser -k 8080/tcp 2>/dev/null
sleep 2
ss -tlnp | grep 8080 || echo "端口已释放"

# 启动 32B
export CUDA_VISIBLE_DEVICES=0
nohup llama-server -m ~/llama.cpp/models/Qwen2.5-32B-Instruct-Q4_K_M.gguf \
  --host 0.0.0.0 --port 8080 -ngl 99 -c 8192 --mlock --no-mmap \
  > /tmp/llama-server.log 2>&1 &

# 等待加载（约 20 秒）
for i in $(seq 1 15); do
  status=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 http://localhost:8080/health 2>/dev/null)
  [ "$status" = "200" ] && echo "✅ llama-server ready" && break
  echo "等待中... ($i)"
  sleep 3
done

# 验证推理是否正常（测试简单请求）
curl -s --max-time 60 http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"回复一个字：好"}],"max_tokens":5,"temperature":0}'
```

> ⚠️ **已知问题**：health 返回 200 但 chat completions 无响应 → llama-server 推理队列被卡住。解决：`fuser -k 8080/tcp` 后重新启动。

### 1c. OpenViking — 本地向量库
```bash
export PATH="$HOME/.hermes/hermes-agent/venv/bin:$PATH"
set -a; source ~/.hermes/.env 2>/dev/null; set +a

nohup openviking-server --host 127.0.0.1 --port 1933 \
  --config ~/.openviking/ov.conf \
  > ~/.hermes/logs/openviking.log 2>&1 &

# 验证
sleep 5
curl -s --max-time 5 http://127.0.0.1:1933/health
# 应返回: {"healthy":true}（根路径 / 返回 404 是正常的）
```

## 第2步：确认 Hermes cron 和 crontab 自动恢复

```bash
# Hermes cron（应有 4 个作业）
hermes cron list

# 系统 crontab（应有约 11 条）
crontab -l
```

Hermes cron 在 Hermes 进程重启后会自动恢复所有作业。
crontab 配置在 WSL 文件系统中，重启后保留。
**通常不需要手动恢复。**

如果发现缺失，用 `cronjob(action='create')` 重建：
- llama-server-watchdog（`*/5 * * * *`，自动重启 Gateway + llama-server）
- openviking-watchdog（`*/5 * * * *`，自动重启 Gateway + OpenViking）
- kanban-blocked-alert（`*/5 * * * *`）
- er-gou-patrol（`*/30 * * * *`，deliver=origin）

## 第3步：检查采集管道（3 项核心）

### 3a. 飞书群消息采集
```bash
# 测试 Lark CLI 是否正常
lark-cli api GET "im/v1/chats?page_size=1" --as user

# 跑一次采集测试
python3 -c "
import sys; sys.path.insert(0, '$HOME/.hermes/scripts')
import feishu_raw_collector as frc
chats = frc.collect_all_groups()
msgs = frc.collect_group_messages(chat_id='oc_810da690991714e6de5df4b17649ad8c', page_size=3)
print('Chats:', len(chats), '| Msgs:', len(msgs) if isinstance(msgs, list) else 'ok')
"
```

> ⚠️ **已知问题**：`lark-cli` 在 cron/daemon 环境找不到。修复：所有脚本中 `lark-cli` 已改为 `str(Path.home() / ".npm-global/bin/lark-cli")` 绝对路径。如果采集仍报错，检查 `config_shared.py`、`feishu_raw_collector.py` 中是否用了裸 `"lark-cli"`。

### 3b. 互联网情报采集
```bash
tail -30 ~/.hermes/logs/internet_intel.log
```
检查最后是否有 "Searching:" 行。如果有 "Read timed out" 说明 32B 还没就绪（回第1步）。

### 3c. 邮件采集
```bash
ls -lt /mnt/d/hermes_data/email/ | head -10
tail -10 ~/.hermes/logs/mail_reader.log
```

## 第4步：全量验证清单

```bash
echo "=== 1. Gateway ==="
ps aux | grep 'hermes gateway run' | grep -v grep | wc -l

echo "=== 2. 32B 模型 ==="
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/health
ps aux | grep llama-server | grep 'Qwen2.5-32B'

echo "=== 3. OpenViking ==="
curl -s --max-time 3 http://127.0.0.1:1933/health

echo "=== 4. Hermes cron ==="
hermes cron list | grep -c "active"

echo "=== 5. crontab ==="
crontab -l | grep -c "^\|^[0-9]"

echo "=== 6. 第二大脑 raw 目录 ==="
ls -d ~/hermes-business/第二大脑/raw/*/ | wc -l

echo "=== 7. D 盘备份 ==="
ls /mnt/d/hermes-backup/ 2>/dev/null | tail -3

echo "=== 8. GitHub 状态 ==="
cd ~/.hermes/scripts-backup && git status -s

echo "=== 9. OpenViking 向量库 ==="
find ~/.openviking/workspace/vectordb/ -type f | wc -l
```

## 常见问题速查

| 问题 | 现象 | 处理 |
|------|------|------|
| Gateway 未运行 | 飞书消息收不到 | 自愈：5分钟内 watchdog 自动重启 |
| 32B 推理卡死 | health 200 但 chat 无响应 | `fuser -k 8080/tcp` → 重启 llama-server |
| 飞书采集报 `not configured` | 日志显示 lark-cli 配置丢失 | 检查脚本中用绝对路径 `~/.npm-global/bin/lark-cli`，不要用裸命令 |
| D 盘 I/O 卡死 | `ls /mnt/d/` 卡住 | `kill -9` 残留 cp/dd 进程，`cmd.exe /c` 绕过 |
| er-gou-patrol Broken pipe | cron 报 `[Errno 32]` | 巡检命令太复杂（多级管道），简化成独立 terminal 命令 |
| 日报/会议纪要管道 | 卡在某一步 | 检查 `daily_briefing*.log` 或 `meeting_notes*.log` 的 error 行 |
| cron_runner 没跑 | crontab 存在但任务不执行 | 检查 `cron_runner.sh` 是否可执行，`test -x` 验证 |
| Kanban 僵尸任务 | 同一任务连续多次 blocked alert | `hermes kanban archive <task_id>` 归档 |

## 恢复完成后

1. 用 `todo` 记录已检查和恢复的项目
2. 更新 `system-memory` skill 中的已知问题（如果有新发现）
3. 向用户输出恢复报告：✅/❌ 表格，最上方给结论
4. 如果发现需要修复的问题 → 直接修，不等待用户指示
5. 所有脚本修改后 → `git commit + push` 到 GitHub
