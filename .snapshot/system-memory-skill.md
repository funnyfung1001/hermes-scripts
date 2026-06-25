---
name: system-memory
description: 二狗系统完整配置记忆 — 所有账户、路径、Token、管道、发送目标。WSL重启后加载此技能恢复全部上下文。
tags: [system, config, recovery, memory]
---

# 二狗系统完整配置记忆

> 加载本技能恢复全部系统配置上下文。
> 每次session结束后，检查是否有新配置信息需要更新到此skill。
> **WSL重启后的标准恢复流程**已提取为独立 skill `system-recovery-procedure`。
> 重启后：`skill_view(name='system-recovery-procedure')` 并按步骤执行。
> 注意：先查 Git history（`cd ~/.hermes/scripts-backup && git log --oneline -20`）了解中断前任务，再逐项恢复。
> 
> 用户曾多次指出我忘记了之前的配置——如用户说\"我感觉这次重启损失了很多信息，你都忘了\"、\"昨晚gemini给你的建议，你是不是也忘了？\"。所以每次获得新配置信息后，立即用skill_manage(action='patch')更新，不要等到被提醒。
> 用户曾多次指出我忘记了之前的配置——如用户说"我感觉这次重启损失了很多信息，你都忘了"、"昨晚gemini给你的建议，你是不是也忘了？"。所以每次获得新配置信息后，立即用skill_manage(action='patch')更新，不要等到被提醒。

## 用户偏好（合并版）
- 说话直接简洁，不需要铺垫和客套
- 不要提醒休息/睡觉（明确说过"以后不要提醒我休息了，我自己决定"）
- 出问题先给结论再展开细节
- 全量采集不跳过：本地模型免费无限用，所有源全量采集让32B分析，任何时候不要替用户决定"这个不重要可以跳过"
- 残留进程彻底清理（`fuser -k` + `ss -tlnp`确认端口释放）
- 所有系统配置必须写入skill而非仅memory（用户多次说"你是不是又忘了"）
- 任何脚本修改后立即 git commit + push 到 GitHub
- 关键配置三重备份：skills + GitHub(.snapshot/) + 第二大脑知识库(wiki/system/config.md)
- 新学会的能力立即同步到GitHub（用户要求"以后所有新学会的技能，和关联的参数以及关联信息，马上同步到github"）
- 写文档时默认用XML富格式（callout/checkbox/table），禁止纯文本/纯Markdown。排版必须专业，内容必须可执行落地，不能有空话套话。用户说过"还是老问题，没有学会用飞书cli的工具，还是纯文本，没法看，排版丑陋，缺少细节，都是空话，套话"
- 失忆恢复流程：`skill_view name=system-memory` → 先查 `~/.hermes/scripts-backup/` 的 Git 历史（`git log --oneline -20`）了解中断前任务背景 → 再对照 `wiki/system/config.md` → 最后根据 Git 时间线决定哪些任务需要恢复、哪些是已完成/僵尸的。**不要跳过 Git history 直接开始修复。**
- 沟通风格：直接干脆，不说废话，不猜测

## 时区
WAT (Africa/Lagos, UTC+1)

## 身份与发送目标

| 目标 | ID | 类型 |
|------|----|------|
| 冯立私聊 | `on_42429dc6344eee41ffa1d3f0858430e5` | union_id |
| C&I Nigeria 工作群 | `oc_25258127a0401e59b0bca9fe20aee436` | chat_id |
| Home Channel（冯立私聊入口） | `oc_110aebfae40be0864d19319de0e4d349` | chat_id |

## 云文档

| 文档 | Token | 链接 |
|------|-------|------|
| 日会纪要 | `AkoGdGuBjovKoMxf3Qwc26FLnJg` | https://transsioner.feishu.cn/docx/AkoGdGuBjovKoMxf3Qwc26FLnJg |
| 周会/周报 | `WvZSdhOm8oRjpQxusfvcNSvsnbb` | https://transsioner.feishu.cn/docx/WvZSdhOm8oRjpQxusfvcNSvsnbb |
| 日报中文版 | `IltidiIKDosnuSxBuiscyuapnng` | https://transsioner.feishu.cn/docx/IltidiIKDosnuSxBuiscyuapnng | 模板见 `doc_templates.xml` 或 规范文档 `VsPedjBJ8oXKOoxJnDocQdtRnMc` |
| 日报英文版 | `CrsSdqt6cored0xXeEhciXhcnsd` | https://transsioner.feishu.cn/docx/CrsSdqt6cored0xXeEhciXhcnsd | 模板同上 |
| 日会纪要（英文） | `AHRkdz0TDouA7qxFTzkc36QSnEf` | https://transsioner.feishu.cn/docx/AHRkdz0TDouA7qxFTzkc36QSnEf | 2026-06-25创建 |
| 周会（中文） | `EYdqdDtfxoSvKGxcmfhcI2zdn2f` | https://transsioner.feishu.cn/docx/EYdqdDtfxoSvKGxcmfhcI2zdn2f | 2026-06-25创建 |
| 售后服务执行方案(主) | `E2SIduWxtod4dSxeJJlc0VVtnYg` | 2026-06-25生成，详见feishu-docx-generator skill |
| 保修卡模板 | `DDaedkbPwoFuwXxYAm5cTd0Znne` | PDF: `KYpjbIBm8olfBXx4LdqcVl2KnJc` |
| 技术交底协议模板 | `L8KqdgRhyoRby3xcNG6c5kKvnqg` | PDF: `EOjsbRl1Aoypg4xDwfQccY9Pn6c` |
| 质量安全免责协议模板 | `RphFdnSzJo3WN9xhUqrcvdkunuh` | PDF: `IyKabG71AoJHEIxz9ptc0g8LnT7` |
| 国包-EPC MOU模板 | `GnlsdWrDZoHPdGx5DqmcbUddn7d` | PDF: `GCvMbq7p8oLA4hxvbJWcVwMdnnd` |
| IHY-50KH3S安装检查清单 | `VmSgdMLMsoUgz5xFbTgcwhVPnnf` | PDF: `EOlfbBHiqo4FhUxyTlyctvomnWc` |

## 核心路径

| 用途 | 路径 |
|------|------|
| 脚本目录 | `~/.hermes/scripts/`（不是`~/scripts/`） |
| 第二大脑知识库 | `~/hermes-business/第二大脑/`（不是`~/second-brain/`或`~/.hermes/data/raw/second_brain/`） |
| GitHub 备份 | `github.com/funnyfung1001/hermes-scripts` |
| WSL 自启动脚本 | `~/.config/hermes-startup.sh` |
| Windows 开机启动 | `C:\\Users\\funny\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\hermes-startup.bat` |
| 巡检cron脚本 | `~/.hermes/scripts/patrol_duty.py` |
| D盘容灾备份 | `/mnt/d/hermes-backup/` |
| 售后方案源文件 | `~/hermes-business/第二大脑/wiki/system/after_sales_src/` — HTML排版源+PDF+生成脚本 |

## D 盘备份操作手册

**两步法（已验证 2026-06-25）：禁止 `cp -a` 大文件到 `/mnt/d/`，9p 协议会卡死。**

### 第一步：在 WSL ext4 内打包
```bash
BACKUP_DIR="/tmp/hermes-backup/$(date +%Y-%m-%d)"
mkdir -p "$BACKUP_DIR"
tar -czf "$BACKUP_DIR/hermes_config.tar.gz" -C ~ .hermes
tar -czf "$BACKUP_DIR/hermes_business.tar.gz" -C ~ hermes-business
tar -czf "$BACKUP_DIR/openviking_data.tar.gz" -C ~ .openviking
tar -czf "$BACKUP_DIR/config.tar.gz" -C ~ .config
tar -czf "$BACKUP_DIR/npm_global.tar.gz" -C ~ .npm-global
# 小文件：~4.3G
```

### 第二步：用 dd 写入 D 盘
```bash
mkdir -p /mnt/d/hermes-backup/$(date +%Y-%m-%d)
# 小文件用 cp
cp /tmp/.../*.tar.gz /mnt/d/hermes-backup/$(date +%Y-%m-%d)/
# 大文件用 dd（bs=4M）
dd if=/tmp/hermes-backup/.../hermes_config.tar.gz of=/mnt/d/.../hermes_config.tar.gz bs=4M status=progress
```

### 模型备份
```bash
# 19GB 模型，约 2 分 16 秒（146 MB/s）
dd if=~/llama.cpp/models/Qwen2.5-32B-Instruct-Q4_K_M.gguf of=/mnt/d/hermes-backup/.../Qwen2.5-32B-Instruct-Q4_K_M.gguf bs=4M status=progress
```

### I/O 卡死急救
如果 `cp` 或 `dd` 卡住导致整条 `/mnt/d/` I/O 阻塞：
```bash
# 1. 找到并杀死残留 cp/dd 进程
ps aux | grep "cp " | grep /mnt/d | awk '{print $2}' | xargs -r kill -9
# 2. 用 Windows cmd 清理错误的备份
cmd.exe /c "rmdir /s /q D:\hermes-backup\2026-06-25"
# 3. 测试 I/O 恢复
echo "test" > /mnt/d/recovery_test.txt && rm -f /mnt/d/recovery_test.txt
```

### 完整性验证
```bash
# 文件数校验
ls /mnt/d/hermes-backup/YYYY-MM-DD/ 2>&1 | grep -c "Input/output"  # 应返回 0
# 小文件 md5sum 对比
md5sum /tmp/.../file.tar.gz /mnt/d/.../file.tar.gz  # 应一致
# 大文件大小对比
stat -c%s source.txt dest.txt  # 应一致
```

## 数据采集管道

### WhatsApp
- Bridge 在 Windows 端：`C:\Users\funny\wweb-mcp\`
- 启动命令：`node bin.js --mode whatsapp-api --api-port 3001 --auth-strategy local`
- API 认证：`Authorization: Bearer` + `api_key.txt` 中的 key
- API 端点：`/api/groups`（群列表），`/api/chats`（聊天列表），`/api/status`（状态）
- 计划任务注册（无窗口后台运行）：`schtasks /create /tn "WhatsAppBridge" /tr "C:\Users\funny\wweb-mcp\start_bridge_no_console.bat" /sc ONSTART /delay 0000:30 /rl HIGHEST /f`
- 开机自启脚本：`C:\Users\funny\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\hermes-startup.bat`
- 采集脚本：`~/.hermes/scripts/whatsapp_collector.py`
- 存储：`~/hermes-business/第二大脑/raw/whatsapp/`
- **认证方式**：`Authorization: Bearer <api_key>`，api_key 在 `C:\\Users\\funny\\wweb-mcp\\.wwebjs_auth\\api_key.txt`
- **已注册为 Windows 计划任务**（无窗口后台运行）：任务名 `WhatsAppBridge`，`C:\\Users\\funny\\wweb-mcp\\start_bridge_no_console.bat` 为入口，开机30秒后启动
- **计划任务注册脚本**：`C:\\Users\\funny\\Desktop\\install-wa-service.bat`（右键管理员运行）
- **⚠️ bat 文件注意事项**：Windows cmd 默认 GBK 编码，bat 文件中不要用中文或 emoji，全部纯 ASCII
- **已验证端点**：`/api/groups`（53个群✅）、`/api/chats`（87个聊天✅）、`/api/status`
- 采集脚本：`~/.hermes/scripts/whatsapp_collector.py`
- **⚠️ 脚本 bug**：`whatsapp_collector.py` 中每次 `requests.get()` 必须显式传 `headers`
- 存储：`~/hermes-business/第二大脑/raw/whatsapp/`

### 邮件
- 数据源：`D:/hermes_data/email/`
- 采集脚本：`~/.hermes/scripts/mail_reader.py`
- 存储：`~/hermes-business/第二大脑/raw/email/`

### 飞书群消息
- 采集脚本：`~/.hermes/scripts/feishu_raw_collector.py`
- 方式：lark-cli api --as user（1.0.57）
- 存储：`~/hermes-business/第二大脑/raw/feishu/`

### OpenViking
- 地址：`localhost:1933`
- 版本：v0.3.17，auth_mode=dev
- **启动命令**：`openviking-server --host 127.0.0.1 --port 1933 --config ~/.openviking/ov.conf`
- **embedding 配置**（ov.conf）：
  - provider: `jina`
  - model: `jina-embeddings-v5-text-small`
  - dimension: 1024
  - api_key: 在 `.env` 中（jina 开头）
- **vlm 配置**：volcengine，模型 `ep-m-20260524072117-9c5gt`
- **旧配置（已废弃）**：doubao-embedding-vision-251215（2048维），重启后已清理重建。当前新集合是空的（vector/count=0），需等待写入管道对接后才能存入数据。
- 数据目录：`~/.openviking/workspace/vectordb/`
- 集合名：`context`，1024维
- API路径：`/api/v1/search/search`（搜索），`/api/v1/system/status`（状态），`/health`（健康检查）
- Hermes OpenViking 插件路径：`~/.hermes/plugins/memory/openviking/`（未激活）

## 模型

### 本地32B
- 服务：llama-server :8080（`~/llama.cpp/build/bin/llama-server`）
- 模型文件：`~/llama.cpp/models/Qwen2.5-32B-Instruct-Q4_K_M.gguf`（19GB，已从D盘复制到WSL内部）
- 速度：~2t/s，每条batch_recovery请求约2-3分钟
- 跨文件系统复制大文件时，cp会报"cannot allocate memory"（buffer冲突），改用 `dd if=... of=... bs=1M status=progress`
- 启动流程：先 `fuser -k 8080/tcp` 清端口 → `nohup ... --mlock > log &` → 等~20秒模型加载 → API就绪
- 从1.5B换到32B时旧进程可能残留，有时需要两次kill

### DeepSeek
- API key 在 `~/.hermes/.env` 中
- 分工：只用于审核、规划、非敏感内容。信息安全/原始业务数据交给本地32B

## lark-cli
- 版本：1.0.57（`~/.npm-global/bin/lark-cli`，已加入PATH）
- API path 不要带 `open-apis/` 前缀（1.0.57自动加）
- 参数用 `--params` 代替 `--query`
- **✅ `docs +update` 支持 `--as user` 参数**（以前skill写"不支持"是错误的）。使用 `--as user` 可以直接写用户创建的文档，不需要bot权限。
- **写入新文档的方式**：
  - 先 `lark-cli api POST "docx/v1/documents" --data '{"title":"标题"}' --as user` 创建文档
  - 然后 `lark-cli docs +update --api-version v2 --doc "<doc_id>" --command overwrite --doc-format markdown --as user --content @./file.md` 全量覆盖写入
  - `--content @file` 只支持**相对路径**，不支持绝对路径
- **修改已有文档**：
  - `block_delete` 批量删除：`--block-id "id1,id2,id3"`（逗号分隔）
  - `str_replace` 查找替换：`--pattern "旧文本" --content "新文本"`（content为空=删除）
  - `append` 追加：追加到文档末尾
  - `overwrite` ⚠️ 全量覆盖（会丢失图片、评论）
- **读取文档**：
  - 获取block列表：`lark-cli api GET "docx/v1/documents/{doc_id}/blocks?page_size=500" --as user`
  - 获取raw内容：`lark-cli api GET "docx/v1/documents/{doc_id}/raw_content" --as user`
- ⚠️ 发消息有 bug（99992402 field validation failed），IM消息走主Bot HTTP API

## 卡片发送
- **三狗Bot（专用于发卡片和消息，不响应群消息）**：
  - AppID: `SANGOU_APP_ID=cli_aa833bbc3bfcdcd9`（在 `.env` 中）
  - Secret: `SANGOU_APP_SECRET`（在 `.env` 中）
  - Token 缓存：`feishu_sangou_tenant_token.json`
  - 三狗不响应任何工作群消息，只负责发卡片
| 三狗Bot（发卡片专用） | `SANGOU_APP_ID=cli_aa833bbc3bfcdcd9`（在`.env`中），`SANGOU_APP_SECRET`，token 缓存 `feishu_sangou_tenant_token.json` | 只发卡片不响应群消息。由 `feishu_card_sender.send_card()` 使用。中文摘要→你私聊，英文筛选→C&I Nigeria工作群 |
- 中文摘要→冯立私聊（union_id=`on_42429dc6344eee41ffa1d3f0858430e5`）用三狗发卡片
- 英文筛选→C&I Nigeria工作群（chat_id=`oc_25258127a0401e59b0bca9fe20aee436`）用三狗发卡片
- 不走 lark-cli CLI（99992402 bug）

## 定时任务

### 系统 crontab（11条）
```
*/30 * * * * cron_runner.sh daemon              # 守护进程(采集+消化+idle_work)
15 10 * * 1-5 cron_runner.sh collect-minutes    # 晨会纪要
0 18 * * 1-5 cron_runner.sh daily-briefing      # 每日简报
0 */3 * * * cron_runner.sh internet-intel       # 互联网情报(预留)
0 5 * * * cron_runner.sh sync-toolbox           # C&I工具箱同步
0 6,8,10,12,14,16,18,20,22 cron_runner.sh digest  # 知识消化
0 6 * * * cron_runner.sh ingest                 # 知识灌入
30 */2 * * * cron_runner.sh patrol              # 巡检
0 2 * * * cleanup_cron_output.sh                # 清理cron output
0 3 * * 0 vacuum_state.sh                       # DB VACUUM
30 2 * * * daily_config_snapshot.py             # 配置备份到GitHub
```

### Hermes cron（4个）
| 作业 | 频率 | 用途 |
|------|------|------|
| llama-server-watchdog | */5 * * * * | 监控本地模型 |
| openviking-watchdog | */5 * * * * | 监控OpenViking |
| kanban-blocked-alert | */5 * * * * | 阻塞任务告警 |
| er-gou-patrol | */30 * * * * | 系统巡检 |

## 断点续传模式（batch_recovery 模式）

长时间运行的 LLM 批处理作业（如补历史日会/周会/简报）需要 checkpoint 支持：

- 每条成功处理后写入 `.batch_recovery_{phase}_checkpoint.txt`
- 下次启动时读取 checkpoint，跳过已完成的日期
- 即使被超时打断也能从上次位置恢复
- 实现方式：`checkpoint_file = Path(__file__).parent / f".batch_recovery_{phase}_checkpoint.txt"`，成功后 `checkpoint_file.write_text(ds)`

## 工作流

### 会议纪要（日会/周会）
1. 飞书VC妙记 → vc +search → minute_token
2. 本地32B生成结构化中文纪要（交叉验证多数据源）
3. 写入云文档（日会→AkoGd..., 周会→WvZS...）
4. 中文摘要 → 私聊冯立（union_id）
5. 英文筛选 → C&I Nigeria工作群（chat_id）

### 每日简报
1. 采集飞书群消息/邮件/会议纪要
2. 本地32B生成结构化简报（交叉验证）
3. 写入日报中文版云文档（Iltidi...）
4. 英文版写入日报英文版云文档（CrsSd...）
5. 中文摘要 → 私聊冯立
6. 英文版 → C&I Nigeria工作群

### daemon_worker 主循环
1. WhatsApp采集（bridge可用时）
2. 飞书群消息采集（feishu_raw_collector）
3. 邮件采集（mail_reader）
4. 知识消化（digest_new_data，可调本地32B或DeepSeek）
5. 空闲时 idle_work：随机选 knowledge_link / deep_read / cross_ref，全走本地32B

## 已知问题

| # | 问题 | 症状 | 处理 |
|---|------|------|------|
| 1 | WSL重启 `scripts/` 丢失 | `__pycache__/` 残留，.py/.sh 文件消失 | 从 git 恢复；参考 `system-maintenance-records` |
| 2 | Gateway 意外杀死 | 日志最后 `Received SIGTERM — initiating shutdown` | ✅ 自愈（2026-06-25）：双 watchdog 每5分钟自动 `hermes gateway run --replace`。启动脚本 `~/.config/hermes-startup.sh` 保底。最长盲区 5 分钟 |
| 3 | D盘备份 `Input/output error` | `cp -a` 到 `/mnt/d/` 跨文件系统，重启/休眠后文件损坏 | 备份后必须 `ls -la 2>&1 | grep -c "Input/output"` 验证。**禁止 `cp -a` 大文件到 D 盘**，用 `dd bs=4M`。残留 cp 进程会阻塞整条 9p I/O，先用 `kill -9` 清理再用 `cmd.exe /c` 绕道操作 |
| 4 | llama-server-watchdog idle timeout | 报 TimeoutError(600s)，但服务器正常 | 模型加载慢 ~20秒，用 `ps aux | grep Qwen2.5-32B` 确认 |
| 5 | 32B OOM → 静默 fallback 1.5B | API 正常返回但质量骤降 | 巡检用 `ps aux` 确认模型文件名 |
| 6 | cp 跨文件系统卡死 | `cp -a` 到 `/mnt/d/` 卡死，阻塞 9p I/O | 用 `dd bs=4M status=progress`；残留检测：`ps aux | grep "cp " | grep /mnt/d` |
| 7 | Windows bat GBK 编码 | 中文/emoji 乱码 | 全部纯 ASCII |
| 8 | OpenViking 巡检用 `/` 根路径 | 404 误判宕机 | 用 `/health` 端点 |
| 9 | lark-cli 发消息 99992402 | IM 消息 field validation failed | 走主 Bot HTTP API，不用 lark-cli |
| 10 | `LOCAL_LLM_ENDPOINT` 拼 URL 重复路径 | 请求路径变 `.../v1/.../v1/chat/...` | 值是完整 URL `http://localhost:8080/v1/chat/completions`，拼接时不重复加 |
| 11 | 残留进程阻塞端口 | llama-server 退出后端口未释放 | 必须 `fuser -k 8080/tcp` + `ss -tlnp | grep 8080` 验证 |
| 12 | 实战验证胜过配置检查 | 配置看起来在跑但实际 0 产出 | 必须实际运行验证输出 |
| 13 | 长时间批处理超时 | Hermes 后台进程约 5 分钟全局超时 | 用 `setsid python3 script.py >> log 2>&1 &` 脱离进程组 |
| 14 | WhatsApp Bridge 认证不持久 | 报 401 | 每次 `requests.get()` 显式传 `headers={'Authorization': 'Bearer <key>'}` |
| 15 | schtasks /tr 不支持 `&&` 或 `&` | 计划任务注册失败 | 调用独立 .bat 文件 |
| 16 | WSL 查 Windows 进程 | `ps aux` 查不到 | 用 `tasklist.exe /FI "IMAGENAME eq xxx.exe"`，GBK 解码用 `encoding='gbk'` |
| 17 | WSL 无法强制杀 Windows 进程 | taskkill /F 拒绝访问 | 必须 Windows 管理员终端或 Process Hacker |
| 18 | Windows 僵尸进程诊断 | HandleCount=0 + 内存 20-500K + Responding=True | 内核态僵尸，常见于 san11pk.exe (secdrv)；方案优先级：sc stop secdrv → Process Explorer → 重启电脑 |
| 19 | **lark-cli 在 cron/daemon 环境找不到** | 所有 `subprocess.run(["lark-cli",...])` 报 `not configured`，但手动运行正常 | cron 和 `daemon_worker.py` 环境没有 `~/.npm-global/bin` 在 PATH 里。修复：所有脚本中用 `str(Path.home() / ".npm-global/bin/lark-cli")` 绝对路径调用，而非裸 `"lark-cli"`。已修复文件：`config_shared.py`、`feishu_raw_collector.py`、`daily_briefing_generator.py`（2026-06-25）|
| 21 | **OpenViking content/write API 不是 /search/upsert** | 向 `/api/v1/search/upsert` POST 返回 NOT_FOUND | 正确端点：`POST /api/v1/content/write`。URI scheme 必须是 `viking://`。`wait=true` 会等 embedding 完成导致超时，推荐 `wait=false`。详见 `references/openviking-content-write-api.md` |
| 22 | **OpenViking ingest 速率控制** | daemon_worker 一次性写入 20+ 个文件，embedding 队列被淹没 | `openviking_ingest.py` 中 `write_to_ov()` 必须加全局速率控制，每条间隔 >= 5 秒。用 `wait=false`（异步）避免卡住主循环。详见 `system-recovery-procedure` skill |
| 23 | **lark-cli VC 妙记 API 参数错误** | `vc +search --date` 报错、`+recording` 返回 None、`+notes` 返回空 dict、transcript 取不到内容 | `--date` 参数不存在，改用 `--start`。`+recording` 的 token 在 `data.recordings[0].minute_token`，不是直接字段。`+notes` 返回 `data.notes[0]`（数组）。transcript API 返回 binary 文件，用 saved_path 读取。详见 `feishu-daily-system` skill |
| 24 | 三狗Bot 卡片发送用错了 AppID（已修复） | 发卡片到工作群报 Bot not in chat | 用三狗Bot SANGOU_APP_ID=cli_aa833bbc3bfcdcd9 发卡片，不能混用主Bot。三狗静默不响应群消息。2026-06-25 已修复 feishu_card_sender.py |

## 多渠道互联网采集（待重建）

以下多渠道采集框架曾因 WSL 重启而丢失，用户花大量时间调过，记录在此供重建参考：

| 渠道 | 方案 | 状态 | Key/Token |
|------|------|------|-----------|
| **TikTok** | Apify TikTok scraper（首选）或 `TikTokApi` v7.3.3（备选，ms_token认证） | ❌ 脚本丢失 | `APIFY_API_TOKEN` / `MS_TOKEN_1`/`MS_TOKEN_2` 在 .env 中 |
| **X/Twitter** | `xurl` skill（Hermes内置，`social-media/xurl`）或 Apify | ✅ skill可用 | — |
| **YouTube** | `youtube-content` skill（Hermes内置），`youtube_transcript_api` 已装 | ✅ skill可用 | — |
| **LinkedIn** | Apify LinkedIn scraper（用 APIFY_API_TOKEN） | ❌ 未集成 | `APIFY_API_TOKEN` |
| **Facebook** | Apify Facebook scraper | ❌ 未集成 | `APIFY_API_TOKEN` |
| **Instagram** | Apify Instagram scraper | ❌ 未集成 | `APIFY_API_TOKEN` |
| **网页搜索** | Tavily → DuckDuckGo fallback | ✅ `internet_intel.py` v2 | `TAVILY_API_KEY` 在 .env 中 |

丢失的脚本：`tiktok_collector_v2.py`（TikTokApi实现）、`multi_media_agent.py`、`ci-competitor-monitor.py`
参考文档在 feishu-daily-system skill 的 `references/second-brain-extra/tiktok-api-migration.md`

`internet_intel.py` 当前(v2)只做了网页搜索，还需升级为Apify多渠道版。
