# 二狗系统配置快照

> 生成时间: 2026-06-25 WAT
> 本文件包含所有非敏感的系统配置。
> 敏感凭据（API keys、Token secrets）只记录变量名和来源，不记录具体值。
> 具体值在 `~/.hermes/.env` 中，GitHub 不备份 .env。

---

## 1. 系统基础

| 项目 | 值 |
|------|-----|
| 时区 | WAT (Africa/Lagos, UTC+1) |
| 脚本目录 | `~/.hermes/scripts/` |
| 第二大脑 | `~/hermes-business/第二大脑/` |
| GitHub 备份仓库 | `github.com/funnyfung1001/hermes-scripts` |
| WSL 自启动 | `~/.config/hermes-startup.sh` |
| Windows 开机启动 | `C:\Users\funny\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\hermes-startup.bat` |
| 本地模型 | `~/llama.cpp/models/Qwen2.5-32B-Instruct-Q4_K_M.gguf`（19GB，llama-server :8080） |
| OpenViking | v0.3.17，localhost:1933，155条向量 |
| Hermes 版本 | v0.17.0 |

## 2. 飞书发送目标

| 目标 | ID | 类型 |
|------|-----|------|
| 冯立私聊 | `on_42429dc6344eee41ffa1d3f0858430e5` | union_id |
| C&I Nigeria 工作群 | `oc_25258127a0401e59b0bca9fe20aee436` | chat_id |
| Home Channel(默认通道) | `oc_110aebfae40be0864d19319de0e4d349` | chat_id |

## 3. 飞书云文档

| 文档 | Token | 用途 |
|------|-------|------|
| 日会纪要 | `AkoGdGuBjovKoMxf3Qwc26FLnJg` | 每日站会结构化纪要 |
| 周会/周报 | `WvZSdhOm8oRjpQxusfvcNSvsnbb` | 每周会议纪要 |
| 日报中文完整版 | `IltidiIKDosnuSxBuiscyuapnng` | 中文版每日简报(详细) |
| 日报英文版 | `CrsSdqt6cored0xXeEhciXhcnsd` | 英文版每日简报 |
| 冯立主日历 | `feishu.cn_nOG0f25YOnL2FhRXckUJdd@group.calendar.feishu.cn` | 日历ID |

## 4. 环境变量清单

以下变量在 `~/.hermes/.env` 中配置，需要对应设置的值见下表：

| 变量名 | 用途 | 值来源 |
|--------|------|--------|
| `FEISHU_APP_ID` | 飞书主Bot AppID | `cli_aa8c6a1189381bd4` |
| `FEISHU_APP_SECRET` | 飞书主Bot AppSecret | 安全敏感，在 .env 中 |
| `FEISHU_HOME_CHANNEL` | 默认消息通道ID | `oc_110aebfae40be0864d19319de0e4d349` |
| `DEEPSEEK_API_KEY` | DeepSeek API key | 安全敏感，在 .env 中 |
| `TAVILY_API_KEY` | 网页搜索 | 安全敏感，在 .env 中 |
| `GEMINI_API_KEY` | Gemini API | 安全敏感，绑定项目 |
| `GOOGLE_API_KEY` | Google API | 安全敏感，在 .env 中 |
| `MS_TOKEN_1` | TikTok ms_token #1 | 安全敏感，在 .env 中 |
| `MS_TOKEN_2` | TikTok ms_token #2 | 安全敏感，在 .env 中 |
| `APIFY_API_TOKEN` | Apify爬虫平台 | 安全敏感，在 .env 中 |
| `EGOU_APP_SECRET` | 二狗Bot AppSecret | 同 FEISHU_APP_SECRET |
| `SANGOU_APP_ID` | 三狗Bot AppID | `cli_aa833bbc3bfcdcd9` |
| `SANGOU_APP_SECRET` | 三狗Bot AppSecret | 安全敏感，在 .env 中 |
| `VOLC_ARK_API_KEY` | 火山引擎方舟key | 安全敏感，在 .env 中 |
| `VOLC_ACCESS_KEY` | 火山引擎access key | 安全敏感，在 .env 中 |
| `VOLC_SECRET_KEY` | 火山引擎secret key | 安全敏感，在 .env 中 |
| `CRM_BASE_TOKEN` | CRM系统 token | 安全敏感，在 .env 中 |
| `PSI_BASE_TOKEN` | PSI系统 token | 安全敏感，在 .env 中 |
| `CI_TOOLBOX_TOKEN` | C&I工具箱 token | 安全敏感，在 .env 中 |
| `WHATSAPP_BRIDGE` | WhatsApp Bridge URL | `http://172.27.208.1:3001` |
| `WHATSAPP_API_KEY` | WhatsApp API key | 自动从 api_key.txt 读取 |

## 5. 数据采集管道

| 源 | 脚本 | 存储位置 | 状态 |
|----|------|----------|------|
| WhatsApp | `whatsapp_collector.py` | `第二大脑/raw/whatsapp/` | ✅脚本正常，需Windows端启动bridge |
| 邮件 | `mail_reader.py` | `第二大脑/raw/email/` | ✅正常，从`D:/hermes_data/email/`读取 |
| 飞书群消息 | `feishu_raw_collector.py` | `第二大脑/raw/feishu/` | ✅正常 |
| 飞书VC妙记 | `meeting_minutes_pipeline.py` | 云文档+第二大脑 | ✅正常 |
| 互联网(网页) | `internet_intel.py` | `第二大脑/raw/intel/` | ✅v2版已补充Tavily搜索+32B分析 |
| 互联网(多渠道) | `internet_intel.py`(待升级) | `第二大脑/raw/intel/` | ⏳待用Apify集成TikTok/X/YouTube/LinkedIn |
| TikTok(旧) | `tiktok_collector_v2.py`(丢失) | — | ❌WSL重启丢失，参考文档在skill中 |
| 多Agent采集 | `multi_media_agent.py`/`ci-competitor-monitor.py`(丢失) | — | ❌WSL重启丢失 |

## 6. 定时任务

### 系统 crontab（crontab -e 查看完整）
```
*/30 * * * * cron_runner.sh daemon              # 守护进程
15 10 * * 1-5 cron_runner.sh collect-minutes    # 晨会纪要
0 18 * * 1-5 cron_runner.sh daily-briefing      # 每日简报
0 */3 * * * cron_runner.sh internet-intel       # 互联网情报
0 5 * * * cron_runner.sh sync-toolbox           # C&I工具箱同步
0 6,8,10,12,14,16,18,20,22 cron_runner.sh digest  # 知识消化
0 6 * * * cron_runner.sh ingest                 # 知识灌入
30 */2 * * * cron_runner.sh patrol              # 巡检
0 2 * * * cleanup_cron_output.sh                # 清理cron output
0 3 * * 0 vacuum_state.sh                       # DB VACUUM
30 2 * * * python3 daily_config_snapshot.py     # 配置备份到GitHub
```

### Hermes cron（4个）
| 名 | 频率 | 用途 |
|----|------|------|
| llama-server-watchdog | */5 * * * * | 监控本地32B模型 |
| openviking-watchdog | */5 * * * * | 监控OpenViking |
| kanban-blocked-alert | */5 * * * * | 阻塞任务告警 |
| er-gou-patrol | */30 * * * * | 系统巡检 |

## 7. 核心脚本清单（~20个）

| 脚本 | 文件名 | 用途 |
|------|--------|------|
| 守护进程 | `daemon_worker.py` | 采集+消化+idle_work主循环，每30分钟 |
| 知识消化 | `daemon_digest.py` | 全量扫描raw/中未消化文件，每2小时 |
| 批量恢复 | `batch_recovery.py` | 补历史日会/周会/简报，32B交叉验证 |
| 日会纪要 | `meeting_notes_manager.py` | 日会/周会纪要生成+发送 |
| 晨会管道 | `meeting_minutes_pipeline.py` | 飞书VC妙记→结构化→云文档 |
| 每日简报 | `daily_briefing_generator.py` | 简报生成+分语言发送+云文档 |
| 简报管理 | `daily_briefing_manager.py` | 简报调度管理 |
| 每日摄入 | `daily_ingest.py` | 每日数据摄入管道 |
| 飞书采集 | `feishu_raw_collector.py` | 群消息/私聊采集 |
| 飞书全集 | `feishu_all_collector.py` | 飞书多源采集v2 |
| 飞书卡片 | `feishu_card_sender.py` | 主Bot HTTP API发卡片 |
| 邮件采集 | `mail_reader.py` | 从Windows邮件目录采集 |
| WhatsApp | `whatsapp_collector.py` | WhatsApp消息采集 |
| 互联网 | `internet_intel.py` | 网页搜索+32B分析（待升级多渠道） |
| 工具箱同步 | `sync_ci_toolbox.py` | C&I工具箱同步 |
| 配置快照 | `daily_config_snapshot.py` | 每天2:30备份到GitHub |
| 巡检 | `patrol_duty.py` | 系统巡检 |
| cron入口 | `cron_runner.sh` | 9子命令调度入口 |
| 日志清理 | `cleanup_cron_output.sh` | cron output清理 |
| DB维护 | `vacuum_state.sh` | 每周DB VACUUM |

## 8. 已知问题清单

1. WSL重启后`~/.hermes/scripts/`丢失→从git恢复
2. lark-cli 1.0.57发消息有bug(99992402)→走主Bot HTTP API
3. lark-cli `docs +update`不支持`--as`参数
4. `LOCAL_LLM_ENDPOINT`已是完整URL(`/v1/chat/completions`)，拼接别重复
5. cp大文件19GB跨NTFS→ext4报"Cannot allocate memory"→用dd
6. 32B被OOM后llama-server静默fallback到1.5B→检查响应中model字段
7. 杀进程必须`fuser -k` + 验证`ss -tlnp | grep 8080`
8. feishu_card_sender别用lark-cli，用主Bot HTTP API
9. 32B抄送巡检脚本检查gateway用`ps aux`而非`hermes gateway status`

## 9. 工作流设计

### 信息安全
- 所有原始业务数据（WhatsApp/飞书消息/邮件/会议内容）→ 只走本地32B，绝不外传
- DeepSeek 只处理：规划、格式审核、简报筛选摘要（脱敏后）
- 互联网情报（公开新闻）→ 32B分析，DeepSeek可辅助

### 全量采集原则
- 本地模型无限免费使用，电脑24小时开机
- 飞书私聊/群聊、WhatsApp私聊/群聊、邮件、互联网 → 全部全量采集
- 不跳过、不省token、不代替本地模型验证
- 每条数据由32B仔细分析（deep_digest）

### idle_work（空闲深度学习）
- 本地模型空闲时随机选择：
  1. knowledge_link - 连接不同来源的知识
  2. deep_read - 深度阅读一个raw文件
  3. cross_ref - 多源交叉验证
- 结果存入 `第二大脑/raw/digest/`
