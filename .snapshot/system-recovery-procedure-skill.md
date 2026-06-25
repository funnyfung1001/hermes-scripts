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

> ⚠️ **已知问题**：health 返回 200 但 chat completions 无响应 → llama-server 推理队列被卡住（长文本推理卡死阻塞后续请求）。排查：试一次简单推理（max_tokens=5）看是否在 30 秒内返回。修复：`fuser -k 8080/tcp` 后重新启动。注意这种卡死状态下 digest 和 internet-intel 的所有 LLM 调用都会超时（Read timed out）。

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

### 3d. OpenViking 写入管道验证
```bash
# 测试 content/write API（正确端点，不要用 search/upsert）
curl -s --connect-timeout 5 -X POST http://127.0.0.1:1933/api/v1/content/write \
  -H "Content-Type: application/json" \
  -d '{"uri":"viking://resources/second_brain/verify.md","content":"# 恢复验证","mode":"create","wait":false}'

# 看向量库是否增长
find ~/.openviking/workspace/vectordb/ -type f | wc -l
```

> ⚠️ **OpenViking API 要点（2026-06-25 发现）：**
> - 写入端点：`POST /api/v1/content/write`（不是 `/api/v1/search/upsert`）
> - URI scheme：`viking://resources/...`（不是 `memory://` 或 `file://`）
> - 异步写入：设 `wait=false`，否则等待 embedding 完成会超时
> - 速率控制：daemon_worker 每30分钟写入所有文件，需加 5秒间隔避免淹没队列
> - 重启测试用 `curl -s http://127.0.0.1:1933/health` 验证，根路径 `/` 返回 404 是正常的

## 第4步：验证实际产出（不仅仅是状态检查）

**用户明确要求**：不要只看"进程在跑"，要确认**实际有数据文件产出**。状态检查只告诉你"进程在跑"，真正的故障只有验证数据文件才能发现。

```bash
# 飞书群消息：今天是否有新文件？
ls -lt ~/hermes-business/第二大脑/raw/feishu/ | head -5

# 互联网情报：今天是否有分析产出？
ls -lt ~/hermes-business/第二大脑/raw/intel/ | head -5

# 知识消化：最近分析文件的时间？
ls -lt ~/hermes-business/第二大脑/raw/digest/ | head -10

# 日报：最近一期日期？
ls -lt ~/hermes-business/第二大脑/daily/ | head -5

# OpenViking 向量库：实际文件数
find ~/.openviking/workspace/vectordb/ -type f | wc -l
```

如果进程状态正常但无产出，排查方向：
- 飞书采集报错 → 检查日志是否 `not configured`（lark-cli 路径问题）
- digest/情报无分析 → 32B 可能推理卡死（health 200 但 chat 卡住）
- 邮件无数据 → 检查 Windows 端计划任务是否已执行

### 32B 推理验证（关键）

```bash
# 1. 简单测试（max_tokens=5，应在 10 秒内返回）
curl -s --max-time 30 http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"回复一个字：好"}],"max_tokens":5,"temperature":0}'

# 2. 如果返回 200 但内容为空，说明推理卡死
# 3. 长文本（>5000 字符）分析建议用 DeepSeek（20秒内完成）而不是 32B（可能超时）
```

### 3e. 会议纪要采集 — 搜妙记查今天是否有新会议

```bash
TODAY=$(date +%Y-%m-%d)
lark-cli vc +search --start "$TODAY" --as user | python3 -c "
import sys,json
d=json.load(sys.stdin)
for i in d.get('data',{}).get('items',[]):
    print(f\\\"  {i.get('id','?')} | {i.get('display_info','?').split(chr(10))[0]}\\\")
"
```
注意：有 meeting ID 不等于有 minute_token（需 `vc +recording`），有 minute_token 不等于有 AI 纪要（需 `vc +notes`，可用 transcript 降级）。

全部 API 细节见 `feishu-daily-system` skill 的 `references/lark-cli-vc-meetings.md`。

## 常见问题速查

| 问题 | 现象 | 处理 |
|------|------|------|
| Gateway 未运行 | 飞书消息收不到 | 自愈：5分钟内 watchdog 自动重启 |
| 32B 推理卡死 | health 200 但 chat 无响应 | `fuser -k 8080/tcp` → 重启 llama-server |
| 飞书采集报 `not configured` | 日志显示 lark-cli 配置丢失 | 检查脚本中用绝对路径 `~/.npm-global/bin/lark-cli`，不要用裸命令 |
| D 盘 I/O 卡死 | `ls /mnt/d/` 或 `cp` 卡住 | `kill -9` 残留 cp/dd 进程 → `cmd.exe /c "rmdir /s /q D:\\path"` 绕行 → `echo "test" > /mnt/d/test` 验证恢复 |
| er-gou-patrol Broken pipe | cron 报 `[Errno 32]` | 巡检命令太复杂（多级管道），简化成独立 terminal 命令 |
| OpenViking 写入失败 | 返回 NOT_FOUND | 用 `POST /api/v1/content/write`（不是 `/api/v1/search/upsert`），URI 用 `viking://resources/...` scheme（不是 `memory://` 或 `file://`），`wait=false` 异步写入。daemon_worker 循环中加 5 秒间隔速率控制避免并发淹没 |
| 日报/会议纪要管道 | 卡在某一步 | 检查 `daily_briefing*.log` 或 `meeting_notes*.log` 的 error 行 |
| cron_runner 没跑 | crontab 存在但任务不执行 | 检查 `cron_runner.sh` 是否可执行，`test -x` 验证 |
| Kanban 僵尸任务 | 同一任务连续多次 blocked alert | `hermes kanban archive <task_id>` 归档 |

## 恢复完成后

1. 用 `todo` 记录已检查和恢复的项目
2. 更新 `system-memory` skill 中的已知问题（如果有新发现）
3. 向用户输出恢复报告：✅/❌ 表格，最上方给结论
4. 如果发现需要修复的问题 → 直接修，不等待用户指示
5. 所有脚本修改后 → `git commit + push` 到 GitHub
