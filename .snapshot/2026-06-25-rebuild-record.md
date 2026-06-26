# 2026-06-25 全面重建记录

## 变更摘要

**触发事件**：Windows 电脑重启，WSL 重启后所有进程丢失（Gateway、llama-server、OpenViking）
**恢复过程中发现的系统性问题**：
1. lark-cli 在 cron/daemon 环境找不到
2. Gateway 无自愈机制
3. 32B 长文本推理超时
4. 三狗 Bot 卡片身份错误
5. 日会文档混乱（重复、中英文混杂）
6. 周会文档空白
7. 日报中文/英文文档格式不统一
8. OpenViking 向量库为空

---

## 文档框架统一（核心变更）

### 设计原则
- 每类文档严格分中/英文，不混杂
- 每个文档有唯一的标准模板（XML 定义）
- 所有脚本生成的 prompt 必须匹配对应的模板

### 文档清单

| 文档 | Token | 用途 | URL |
|------|-------|------|-----|
| **日会纪要（中文）** | `AkoGdGuBjovKoMxf3Qwc26FLnJg` | 每日站会中文纪要 | https://transsioner.feishu.cn/docx/AkoGdGuBjovKoMxf3Qwc26FLnJg |
| **日会纪要（英文）** | `AHRkdz0TDouA7qxFTzkc36QSnEf` | 每日站会英文纪要（新创建） | https://transsioner.feishu.cn/docx/AHRkdz0TDouA7qxFTzkc36QSnEf |
| **周会/周报（中文）** | `EYdqdDtfxoSvKGxcmfhcI2zdn2f` | 每周C&I团队纪要（新创建，替代旧英文空文档） | https://transsioner.feishu.cn/docx/EYdqdDtfxoSvKGxcmfhcI2zdn2f |
| **周会/周报（英文旧）** | `WvZSdhOm8oRjpQxusfvcNSvsnbb` | 英文版（已废弃，空文档） | — |
| **日报中文版** | `IltidiIKDosnuSxBuiscyuapnng` | 每日简报中文完整版 | — |
| **日报英文版** | `CrsSdqt6cored0xXeEhciXhcnsd` | 每日简报英文版 | — |
| **文档模板规范** | `VsPedjBJ8oXKOoxJnDocQdtRnMc` | 所有模板定义 | https://transsioner.feishu.cn/docx/VsPedjBJ8oXKOoxJnDocQdtRnMc |

### 每个文档的标准结构

```
日会中文：📋会议摘要 → 📊项目进展 → ✅待办 → 🔑关键决策 → ⚠️问题风险
日会英文：Summary → Project Updates → Action Items → Decisions → Risks
周会中文：📋会议概要 → 📊项目 → 💰财务 → 📈情报 → ✅待办 → 🔑决策 → ⚠️风险
日报中文：📋今日概览 → 📊项目 → 📈市场 → 👥团队 → ✅待办 → 📝摘要
日报英文：Overview → Projects → Intel → Team → Actions → Summary
digest 分析：📋基础信息 → 👥关键人物 → 📊数据提取 → ✅待办 → 🔗业务关联 → ⚠️异常 → 📝摘要
```

---

## 所有脚本修改清单

### 1. feishu_card_sender.py — 三狗 Bot 身份修复
- **问题**：卡片发送用了主 Bot (`FEISHU_APP_ID`)，三狗 Bot 身份丢失
- **修复**：改为从 `.env` 读取 `SANGOU_APP_ID`/`SANGOU_APP_SECRET`
- **效果**：三狗发到冯立私聊和 C&I Nigeria 工作群均 ✅
- **原因**：用户要求三狗专用于发卡片，不响应群消息

### 2. feishu_raw_collector.py — lark-cli 全路径
- **问题**：`subprocess.run(["lark-cli",...])` 在 cron/daemon 环境找不到
- **修复**：改为 `str(Path.home() / ".npm-global/bin/lark-cli")`
- **效果**：飞书群消息采集今日数据正常 ✅

### 3. config_shared.py — 同上
- **问题**：`lark_cli_user()` 裸命令
- **修复**：导入 `from pathlib import Path`，改为全路径

### 4. meeting_notes_manager.py — 大量修复
- **问题**：
  - `vc +search --date` 参数不存在（实际用 `--start`）
  - `+recording` 返回值在 `data.recordings[0].minute_token` 不是直接 `data.minute_token`
  - `+notes` 返回值在 `data.notes[0]` 数组
  - 没有新增的英文文档和周会文档 ID
  - prompt 模板不匹配新框架
- **修复**：
  - `run_lark()` 自动替换 `lark-cli` 为全路径
  - 修正所有 API 返回值解析
  - 新增 `DAILY_MEETING_EN_DOC` 和 `WEEKLY_DOC`
  - 统一 prompt 模板

### 5. daily_briefing_generator.py — prompt 统一
- **问题**：老 prompt 只有"概览+待办+明日提醒"三个字段
- **修复**：按新模板改为"概览→项目→市场→团队→待办→摘要"六段结构
- **卡片发送**：从纯文本改为 `feishu_card_sender.send_card()` 卡片

### 6. daemon_digest.py — 32B 自动分段
- **问题**：32B 处理 6000 字符超时
- **修复**：`call_llm()` 检测 >2500 字符时按段落切成 2000 字符块，逐块处理拼接
- **原因**：用户明确要求不要浪费本地模型，任务切小让 32B 跑完

### 7. daemon_worker.py — 同上 + OpenViking
- **问题**：无 OpenViking 写入步骤
- **修复**：新增第6步 `openviking_ingest.ingest_new_content()`
- **digest prompt**：统一模板

### 8. batch_recovery.py — 完整重写
- **问题**：32B 每条超时 600 秒
- **修复**：`call_llm()` 自动分段 + 全部走本地 32B（无 DeepSeek 降级）
- **周会指向**：从旧英文文档换为新中文文档
- **断点续传**：checkpoint 机制保留
- **当前状态**：正在后台跑，已完成 05-18 日报中文第一条

### 9. openviking_ingest.py — 新建
- **背景**：OpenViking 向量库为空
- **功能**：扫描 `raw/digest/`、`raw/intel/`、`raw/meetings/` 写入 OpenViking
- **API**：`POST /api/v1/content/write`，URI scheme `viking://resources/second_brain/`
- **速率控制**：每条间隔 5 秒，避免淹没 embedding 队列
- **首次写入**：61 条文档（digest + intel + meetings）

### 10. doc_templates.xml — 新建模板规范
- **内容**：所有 5 类文档的 XML 格式定义
- **存储**：`~/.hermes/scripts/doc_templates.xml`

---

## 系统修复清单

| # | 问题 | 修复方式 | 验证 |
|---|------|---------|------|
| 1 | lark-cli cron 环境找不到 | 所有脚本 full path | feishu 采集正常 ✅ |
| 2 | Gateway 无自愈 | watchdog 改为自动重启 | 最长 5 分钟恢复 |
| 3 | D 盘备份 I/O 卡死 | `dd bs=4M` 替代 `cp -a` | 23G 备份成功 ✅ |
| 4 | 32B 推理卡死 | `fuser -k 8080/tcp` 重启 | 测试正常 ✅ |
| 5 | er-gou-patrol Broken pipe | 简化巡检命令 | 运行正常 ✅ |
| 6 | 日会文档重复 | `block_delete` 删 14 个块 | rev 195 ✅ |
| 7 | 三狗卡片身份 | 改 SANGOU_APP_ID | 私聊+工作群 ✅ |
| 8 | 32B 长文本超时 | 自动分段（2000字/块） | 分段测试通过 ✅ |
| 9 | OpenViking 为空 | 新建 ingest 管道 + 61条 | 72K→268K ✅ |
| 10 | 飞书采集报 not configured | 全路径修复 | chats_20260625 ✅ |

---

## 启动脚本和自愈

### WSL 启动脚本
`~/.config/hermes-startup.sh` — Gateway 自动启动

### Hermes cron watchdogs（4 个）
| job_id | 名称 | 频率 | 功能 |
|--------|------|------|------|
| a22d2054ba09 | llama-server-watchdog | */5 * * * * | 自动重启 Gateway + llama-server |
| de21a569a20d | openviking-watchdog | */5 * * * * | 自动重启 Gateway + OpenViking |
| 5372f2f8cffb | kanban-blocked-alert | */5 * * * * | 阻塞任务告警 |
| 6f21820dc8f0 | er-gou-patrol | */30 * * * * | 系统巡检 |

### 系统 crontab（11条）
```
*/30 * * * * cron_runner.sh daemon              # 守护进程
15 10 * * 1-5 cron_runner.sh collect-minutes    # 晨会纪要
0 18 * * 1-5 cron_runner.sh daily-briefing      # 每日简报
0 */3 * * * cron_runner.sh internet-intel       # 互联网情报
0 5 * * * cron_runner.sh sync-toolbox           # C&I工具箱同步
0 6,8,10,12,14,16,18,20,22 cron_runner.sh digest  # 知识消化
0 6 * * * cron_runner.sh ingest                 # 知识灌入
30 */2 * * * cron_runner.sh patrol              # 巡检
0 2 * * * cleanup_cron_output.sh                # 清理
0 3 * * 0 vacuum_state.sh                       # DB维护
30 2 * * * daily_config_snapshot.py             # 配置备份到GitHub
```

---

## 恢复流程

WSL 重启后标准恢复：
1. `skill_view(name='system-recovery-procedure')` 加载恢复 skill
2. 先查 Git history：`cd ~/.hermes/scripts-backup && git log --oneline -20`
3. 按 skill 步骤逐项恢复（Gateway → llama-server → OpenViking → 验证管道）
4. 所有修改已同步到 GitHub

---

## GitHub 提交历史

```
fc90e56 fix: 32B call_llm auto-chunking (remove DeepSeek fallback, split long content)
d97eaee docs: 2026-06-25 full rebuild record — doc framework, 10 script fixes
f05e3ad full backup: all script changes + doc templates + skill updates
bba5740 fix: daemon_digest fallback to DeepSeek on 32B timeout
b3a23b8 fix: feishu_card_sender use sangou bot
327f9cb fix: correct lark-cli VC meeting APIs
3c22807 fix: OV ingest use viking:// scheme
c677985 fix: lark-cli full path for cron env
84218a2 feat: extract system-recovery-procedure as standalone skill
15de9fc fix: batch_recovery add DeepSeek fallback
4040ce7 fix: batch_recovery indentation error
ae0daa5 fix: batch_recovery rewrite with proper DeepSeek fallback
```

---

## 备份策略

| 位置 | 内容 |
|------|------|
| **D 盘** `/mnt/d/hermes-backup/YYYY-MM-DD/` | 全量 tar.gz + 模型 gguf（dd） |
| **GitHub** `scripts-backup/.snapshot/` | 所有脚本 + 配置文件 + doc_templates |
| **第二大脑** `wiki/system/` | 配置索引 + 变更记录 markdown |
| **Skills** `system-recovery-procedure` | 完整恢复流程 |
| **Skills** `system-memory` | 已知问题 + 路径配置 |

### D 盘备份方法（两步法）
```bash
# 1. WSL ext4 内打包
tar -czf /tmp/hermes-backup/YYYY-MM-DD/hermes_config.tar.gz -C ~ .hermes
# 2. dd 写入 D 盘（不要 cp -a）
dd if=/tmp/hermes-backup/.../hermes_config.tar.gz of=/mnt/d/hermes-backup/.../hermes_config.tar.gz bs=4M status=progress
```

---

## 2026-06-25 18:40 最终检查结果

### 检查清单
| 项目 | 状态 |
|------|------|
| Gateway | ✅ |
| llama-server 32B | ✅ (去掉--mlock，内存不足时不会卡死) |
| OpenViking | ✅ |
| 32B 短推理 | ✅ |
| 32B 分段(2500字) | ✅ |
| 邮件采集 | ✅ 今日持续产出 |
| 飞书群消息采集(v3) | ✅ 326条/8群(20260625) |
| WhatsApp采集 | ✅ 117条(3群+87私聊)，Bridge Windows端 |
| 互联网情报 | ✅ 今日已产出 |
| Hermes Cron | ✅ 4个active |
| batch_recovery | ⏳ 后台运行中(补历史) |

### 已知问题
1. llama-server --mlock 在系统运行一段时间后可能因内存碎片失败，已改为 --no-mmap 替代
2. WhatsApp Bridge 需 Windows 端手动启动（计划任务 WhatsAppBridge 开机自启）
3. 日报文档有日期空缺(06-10~06-16)，batch_recovery 正在补
4. D盘备份使用 dd bs=4M 而非 cp -a，避免 9p I/O 卡死
