# 2026-06-25 文档框架统一 + 系统修复记录

## 变更背景
电脑重启后所有管道中断，恢复过程中发现：
1. 日会/日报/周会文档格式不统一，中英文混杂、重复
2. lark-cli 在 cron/daemon 环境找不到命令（缺全局 PATH）
3. 三狗 Bot 卡片发送用了主 Bot 身份
4. 32B 长文本推理超时导致 digest 和 batch_recovery 无法产出
5. 飞书群消息采集停止（lark-cli 路径问题）
6. er-gou-patrol Broken pipe 错误

## 一、文档框架统一

### 文档清单

| 文档 | Token | 用途 | 结构 |
|------|-------|------|------|
| 日会纪要（中文） | `AkoGdGuBjovKoMxf3Qwc26FLnJg` | 每日站会中文纪要 | `📋会议摘要 → 📊项目进展 → ✅待办 → 🔑关键决策 → ⚠️问题风险` |
| 日会纪要（英文） | `AHRkdz0TDouA7qxFTzkc36QSnEf` | 每日站会英文纪要 | `Summary → Project Updates → Action Items → Decisions → Risks` |
| 周会/周报（中文） | `EYdqdDtfxoSvKGxcmfhcI2zdn2f` | 每周C&I团队会议纪要 | `📋会议概要 → 📊项目 → 💰财务 → 📈情报 → ✅待办 → 🔑决策 → ⚠️风险` |
| 日报中文版 | `IltidiIKDosnuSxBuiscyuapnng` | 每日简报中文完整版 | `📋概览 → 📊项目 → 📈市场 → 👥团队 → ✅待办 → 📝摘要` |
| 日报英文版 | `CrsSdqt6cored0xXeEhciXhcnsd` | 每日简报英文版 | `Overview → Projects → Intel → Team → Actions → Summary` |
| 文档模板规范 | `VsPedjBJ8oXKOoxJnDocQdtRnMc` | 所有文档格式定义 | 见该文档 |

### 模板文件
`~/.hermes/scripts/doc_templates.xml` — XML 格式定义

### 三层分发逻辑（不变）
1. 完整详细版 → 飞书云文档
2. 中文摘要 → 私聊冯立（union_id: `on_42429dc6344eee41ffa1d3f0858430e5`）
3. 英文筛选 → C&I Nigeria 工作群（chat_id: `oc_25258127a0401e59b0bca9fe20aee436`）

---

## 二、修改的脚本清单

### 1. feishu_card_sender.py
- **问题**: 用的主 Bot AppID/Secret，三狗 Bot 身份丢失
- **修复**: 改为 `SANGOU_APP_ID`/`SANGOU_APP_SECRET` 从 `.env` 读取
- **验证**: 卡片发送到冯立私聊 ✅、C&I Nigeria 工作群 ✅

### 2. feishu_raw_collector.py
- **问题**: 调用 `lark-cli` 裸命令，cron/daemon 环境找不到
- **修复**: 改为 `str(Path.home() / ".npm-global/bin/lark-cli")` 全路径
- **验证**: `chats_20260625_1434.json` 成功产出 ✅

### 3. config_shared.py
- **问题**: 同上的 lark-cli 裸命令
- **修复**: `lark_cli_user()` 改为全路径
- **影响**: 被所有依赖 `config_shared` 的脚本继承

### 4. meeting_notes_manager.py
- **问题**: 
  - VC API 调用错误（`--date`→`--start`，`+recording` 返回格式解析错误）
  - `+notes` 返回数组未解析
  - 无英文文档和新建周会文档 ID
  - prompt 模板不标准
- **修复**: 
  - 修正所有 VC API 调用参数和返回值解析
  - 新增 `DAILY_MEETING_EN_DOC` 和 `WEEKLY_DOC`
  - 统一 prompt 模板匹配日会中文结构

### 5. daily_briefing_generator.py
- **问题**: prompt 模板太简单，无市场动态/团队行政等结构
- **修复**: 统一中文和英文模板，匹配日报标准结构
- **卡片发送**: 从 `send_feishu_message(纯文本)` 改为 `send_card(卡片)`

### 6. daemon_digest.py
- **问题**: 32B 处理 6000 字符每条超时（read timeout 600s），无降级
- **修复**: 增加 DeepSeek 超时降级，统一分析模板
- **效果**: 32B 超时后自动切换到 DeepSeek（60秒出结果）

### 7. daemon_worker.py
- **问题**: 无 OpenViking 写入步骤，digest prompt 少"分析报告"标题
- **修复**: 新增第6步 `openviking_ingest.ingest_new_content()`，prompt 增加标题

### 8. batch_recovery.py
- **问题**: 32B 每条约 600 秒超时，无降级，周会文档指向旧的英文文档
- **修复**: 完全重写（237→237行），增加 DeepSeek 降级，周会指向新中文文档
- **断点续传**: checkpoint 机制保留
- **效果**: 32B 超时后自动降级 DeepSeek（20-30秒/条）

### 9. openviking_ingest.py（新建）
- **用途**: 将第二大脑 digest/intel/meetings 写入 OpenViking 向量库
- **API**: `POST /api/v1/content/write`，URI scheme `viking://resources/second_brain/`
- **速率控制**: 每条间隔至少 5 秒，避免淹没 embedding 队列

### 10. doc_templates.xml（新建）
- **用途**: 所有文档的 XML 格式模板定义
- **内容**: 日会中/英、周会、日报中/英、digest 分析、第二大脑 Index

---

## 三、已知问题修复

| # | 问题 | 修复 | 验证 |
|---|------|------|------|
| 1 | lark-cli cron 环境找不到 | 所有脚本全路径调用 | `feishu_raw_collector` 产出今日数据 ✅ |
| 2 | Gateway 无自愈 | watchdog 改为自动重启 | 每次 crash 5分钟内自动恢复 |
| 3 | D盘备份 I/O 卡死 | `dd bs=4M` 替代 `cp -a` | 23G 备份成功 ✅ |
| 4 | 32B 推理卡死 | `fuser -k 8080/tcp` 重启 | 测试返回"好" ✅ |
| 5 | er-gou-patrol Broken pipe | 简化巡检命令 | 正常运行 ✅ |
| 6 | 日会文档 06-09/06-10 重复 | `block_delete` 删除14个块 | rev 195 ✅ |
| 7 | 三狗卡片身份错误 | 改用 SANGOU_APP_ID | 私聊+工作群 ✅ |
| 8 | 32B digest/batch 超时 | DeepSeek 降级 | 测试通过 ✅ |
| 9 | OpenViking 为空 | 新建 ingest 管道 + 首次写入61条 | 72K→268K ✅ |

---

## 四、启动脚本和自愈

### WSL 启动脚本
`~/.config/hermes-startup.sh` — Gateway 自动启动（第43-56行）

### Hermes cron watchdogs
- `llama-server-watchdog`（`*/5 * * * *`）— 自动重启 Gateway + llama-server
- `openviking-watchdog`（`*/5 * * * *`）— 自动重启 Gateway + OpenViking
- `kanban-blocked-alert`（`*/5 * * * *`）— 阻塞任务告警
- `er-gou-patrol`（`*/30 * * * *`）— 系统巡检

### 系统 crontab（11条）
详见 `~/.hermes/scripts/cron_runner.sh`

---

## 五、恢复流程

WSL 重启后：
1. `skill_view(name='system-recovery-procedure')` — 加载独立 skill
2. 先 `cd ~/.hermes/scripts-backup && git log --oneline -20` 了解中断前任务
3. 按 skill 步骤逐项恢复（Gateway → llama-server → OpenViking → 验证管道）
4. 所有修改后的脚本已同步到 GitHub

---

## 六、GitHub 提交记录

```
f05e3ad full backup: all script changes + doc templates + skill updates (2026-06-25 doc framework)
bba5740 fix: daemon_digest fallback to DeepSeek on 32B timeout
b3a23b8 fix: feishu_card_sender use sangou bot (SANGOU_APP_ID/SECRET) instead of main bot
327f9cb fix: correct lark-cli VC meeting APIs (search/recording/notes/transcript), add full path
3c22807 fix: OV ingest use viking:// scheme, rate limit 5s per write
c677985 fix: lark-cli full path for cron env, card send for daily briefing, OV ingest pipe
84218a2 feat: extract system-recovery-procedure as standalone skill, add pipeline audit checklist
15de9fc fix: batch_recovery add DeepSeek fallback
4040ce7 fix: batch_recovery indentation error
ae0daa5 fix: batch_recovery rewrite with proper DeepSeek fallback
```
