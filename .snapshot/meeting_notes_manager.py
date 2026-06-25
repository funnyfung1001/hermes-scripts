#!/usr/bin/env python3
"""meeting_notes_manager.py — 日会/周会纪要管理

从飞书VC妙记提取会议记录，整理为结构化纪要，写入飞书云文档。
并分语言发送：中文私聊给冯立，英文筛选后发工作群。

日会：每天09:05-09:45 WAT，骑在 daily_ingest 上跑（10:00）
周会：每周五16:30-17:30 WAT，骑在 daily_briefing 上跑（18:00）

用法：
  python3 meeting_notes_manager.py              # 自动判断日会/周会
  python3 meeting_notes_manager.py --date 2026-06-24  # 指定日期
  python3 meeting_notes_manager.py --force daily      # 强制日会
  python3 meeting_notes_manager.py --force weekly     # 强制周会
  python3 meeting_notes_manager.py --dry-run          # 试运行
"""
import sys, json, datetime, subprocess, os
from pathlib import Path
from datetime import timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import setup_logger, today_wat, today_str, get_deepseek_key
from config_shared import DEEPSEEK_API, DEEPSEEK_MODEL

logger = setup_logger("meeting_notes", "meeting_notes.log")

_LARK_CLI = str(Path.home() / ".npm-global/bin/lark-cli")

# ── 文档配置 ──
DAILY_MEETING_DOC = "AkoGdGuBjovKoMxf3Qwc26FLnJg"
DAILY_MEETING_EN_DOC = "AHRkdz0TDouA7qxFTzkc36QSnEf"
WEEKLY_DOC_TOKEN="WvZSdhOm8oRjpQxusfvcNSvsnbb"
WEEKLY_DOC = "EYdqdDtfxoSvKGxcmfhcI2zdn2f"
BRIEFING_CN_DOC = "IltidiIKDosnuSxBuiscyuapnng"
BRIEFING_EN_DOC = "CrsSdqt6cored0xXeEhciXhcnsd"

# ── 发送目标 ──
FENGLI_OPEN_ID = "on_42429dc6344eee41ffa1d3f0858430e5"
WORK_CHAT_ID = "oc_25258127a0401e59b0bca9fe20aee436"

def run_lark(cmd_list, timeout=60):
    """执行 lark-cli 命令，使用全路径避免 cron 环境 PATH 问题"""
    # 确保第一条命令是全路径 lark-cli
    if cmd_list and cmd_list[0] == "lark-cli":
        cmd_list[0] = _LARK_CLI
    elif cmd_list and cmd_list[0] == _LARK_CLI:
        pass  # 已经使用全路径，不用改
    else:
        cmd_list = [_LARK_CLI] + cmd_list
    full_cmd = cmd_list + ["--as", "user"]
    try:
        r = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            return {"error": r.stderr.strip()[:300]}
        out = r.stdout.strip()
        return json.loads(out) if out else {}
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    except json.JSONDecodeError:
        return {"error": f"invalid json"}
    except Exception as e:
        return {"error": str(e)}

def search_meetings(date_str=None):
    """搜索今天（或指定日期）的 VC 妙记"""
    if not date_str:
        date_str = today_wat()
    
    # 正确的 lark-cli vc +search 用法：用 --start
    result = run_lark(["lark-cli", "vc", "+search", "--start", date_str])
    if "error" in result:
        logger.warning(f"VC search failed: {result['error']}")
        return []
    
    meetings = result.get("data", {}).get("items", [])
    return meetings

def get_minute_token(meeting_id):
    """从会议 ID 获取妙记 token
    
    lark-cli vc +recording --meeting-ids <id>
    返回: {"data":{"recordings":[{"meeting_id":"...","minute_token":"obcn..."}]}}
    """
    result = run_lark(["lark-cli", "vc", "+recording", "--meeting-ids", meeting_id])
    if "error" in result:
        logger.warning(f"Recording failed for {meeting_id}: {result['error']}")
        return None
    recordings = result.get("data", {}).get("recordings", [])
    if recordings:
        return recordings[0].get("minute_token")
    return None

def get_minute_notes(minute_token):
    """获取妙记 AI 纪要（summary/todos/chapters）——注意飞书可能还没生成
    
    lark-cli vc +notes --minute-tokens <token>
    返回: {"data":{"notes":[{"minute_token":"...","summary":"...","todos":[],"chapters":[]}]}}
    """
    result = run_lark(["lark-cli", "vc", "+notes", "--minute-tokens", minute_token])
    if "error" in result:
        logger.warning(f"Notes failed for {minute_token}: {result['error']}")
        return None
    notes_list = result.get("data", {}).get("notes", [])
    if notes_list:
        note = notes_list[0]
        if "error" in note:
            logger.info(f"Notes not available for {minute_token}: {note.get('error')}")
            return None
        return note
    return None

def get_transcript(minute_token):
    """导出妙记文字记录（纯文本）
    
    lark-cli api GET minutes/v1/minutes/{token}/transcript
    返回二进制文件内容（text/plain），自动保存到本地文件
    """
    result = run_lark(["lark-cli", "api", "GET", f"minutes/v1/minutes/{minute_token}/transcript"])
    if isinstance(result, dict) and "saved_path" in result:
        path = result["saved_path"]
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"Read transcript file failed: {e}")
            return None
    if isinstance(result, dict) and result.get("content_type") == "text/plain":
        path = result.get("saved_path", "")
        if path:
            try:
                return Path(path).read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
    return None

def get_minute_detail(minute_token):
    """获取妙记基本信息"""
    result = run_lark(["lark-cli", "api", "GET", f"minutes/v1/minutes/{minute_token}"])
    if isinstance(result, dict) and result.get("ok"):
        return result.get("data", {}).get("minute", {})
    return None

def llm_generate_notes(summary, transcript):
    """用 LLM 从 transcript+summary 生成结构化纪要（当妙记无 todos/chapters 时降级）"""
    api_key = get_deepseek_key()
    if not api_key:
        logger.error("No DeepSeek key for LLM fallback")
        return summary
    
    import requests
    
    prompt = f"""你是一个会议纪要助手。请根据以下会议转录记录和摘要，生成结构化的中文会议纪要。

## 会议摘要
{summary[:2000]}

## 对话记录（节选）
{transcript[:4000] if transcript else '(无详细记录)'}

请按以下严格格式输出（不要添加额外内容）：

### 📋 会议摘要
（2-3句话概括会议主题和主要结论）

### 📊 项目进展
**地区名：**
- 项目名：状态描述

### ✅ 待办事项
| # | 事项 | 负责人 | 截止 |
|---|------|--------|------|

### 🔑 关键决策
- 决策内容

### ⚠️ 问题与风险
- **级别：** 描述

注意：
- 项目进展用 **地区名：** 加粗分组
- 待办事项必须表格化，没有截止日期留空
- 输出严格按以上顺序，不要调换顺序"""
    
    try:
        resp = requests.post(
            DEEPSEEK_API,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 3000
            },
            timeout=120
        )
        content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        return content
    except Exception as e:
        logger.error(f"LLM fallback failed: {e}")
        return summary

def format_notes(minute_notes, minute_detail, transcript=None):
    """将妙记内容格式化为结构化中文纪要"""
    # 获取基本信息
    summary = minute_notes.get("summary", "") if minute_notes else ""
    todos = minute_notes.get("todos", []) if minute_notes else []
    chapters = minute_notes.get("chapters", []) if minute_notes else []
    
    # 获取日期
    create_time = None
    if minute_detail:
        ts_ms = minute_detail.get("create_time", 0)
        if ts_ms:
            create_time = datetime.datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    
    meeting_date = today_wat()
    if create_time:
        meeting_date = create_time.astimezone(timezone(timedelta(hours=1))).strftime("%Y-%m-%d")
    
    weekday_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday_str = ""
    if create_time:
        weekday_str = weekday_map[create_time.astimezone(timezone(timedelta(hours=1))).weekday()]
    
    # 用 LLM 降级（如果缺少 todos/chapters）
    if (not todos or not chapters) and (summary or transcript):
        logger.info("Using LLM fallback for structured notes")
        llm_notes = llm_generate_notes(summary, transcript)
        # 如果 LLM 返回了完整内容，直接用 LLM 结果
        if llm_notes and len(llm_notes) > len(summary):
            return llm_notes, meeting_date, weekday_str
    
    # 组装格式化的纪要
    lines = []
    lines.append(f"## {meeting_date}（{weekday_str}）" if weekday_str else f"## {meeting_date}")
    
    # 总结
    if summary:
        lines.append("\n### 📋 会议总结")
        lines.append(summary)
    
    # 待办
    if todos:
        lines.append("\n### ✅ 待办事项")
        lines.append("| # | 待办事项 | 负责人 | 备注 |")
        lines.append("|---|---------|--------|------|")
        for i, todo in enumerate(todos, 1):
            title = todo.get("title", "")
            assignee = todo.get("assignee", {}).get("name", "")
            status = todo.get("status", "")
            lines.append(f"| {i} | {title} | {assignee} | {status} |")
    
    # 章节
    if chapters:
        lines.append("\n### 📑 讨论内容")
        for ch in chapters:
            title = ch.get("title", "未命名章节")
            content = ch.get("summary", "")
            lines.append(f"\n**{title}**")
            if content:
                lines.append(content)
    
    return "\n".join(lines), meeting_date, weekday_str

def update_doc(doc_token, content, meeting_date):
    """更新飞书云文档（先检查日期是否已存在，避免重复追加）"""
    # 先写入临时文件
    tmp_file = Path(f"/tmp/meeting_notes_{meeting_date}.md")
    tmp_file.write_text(content)
    
    # 先获取文档 raw_content，检查日期是否已存在
    # （避免因日期格式差异导致 str_replace 失配而 fallback 到 append）
    doc_raw = run_lark([
        "lark-cli", "api", "GET",
        f"docx/v1/documents/{doc_token}/raw_content"
    ])
    if isinstance(doc_raw, dict) and doc_raw.get("ok"):
        raw_text = doc_raw.get("data", {}).get("content", "")
        # 检查纯 YYYY-MM-DD 是否出现在文档中（匹配多种日期格式）
        if meeting_date in raw_text:
            logger.info(f"Date {meeting_date} already exists in doc, skipping update")
            tmp_file.unlink(missing_ok=True)
            return True
    
    # 文档中还没有今天的日期，用 append
    logger.info("Date not found in doc, using append")
    result = run_lark([
        "lark-cli", "docs", "+update", "--api-version", "v2",
        "--doc", doc_token, "--doc-format", "markdown",
        "--command", "append",
        "--content", f"\n{content}\n"
    ])
    
    tmp_file.unlink(missing_ok=True)
    return "error" not in result

def send_message(recipient_id, text, recipient_type="open_id"):
    """发送消息到飞书"""
    result = run_lark([
        "lark-cli", "api", "POST",
        f"im/v1/messages?receive_id_type={recipient_type}",
        "--data", json.dumps({
            "receive_id": recipient_id,
            "msg_type": "text",
            "content": json.dumps({"text": text})
        })
    ])
    return result.get("ok", False)

def summarize_chinese(content):
    """将完整纪要总结为中文私聊摘要"""
    # 提取关键信息
    lines = content.split("\n")
    summary_lines = []
    todos_lines = []
    decision_lines = []
    
    current_section = None
    for line in lines:
        if "会议总结" in line:
            current_section = "summary"
        elif "待办事项" in line:
            current_section = "todos"
        elif "关键决策" in line:
            current_section = "decision"
        elif line.startswith("## "):
            current_section = "header"
            summary_lines.append(line)
        elif current_section == "summary" and line.strip():
            summary_lines.append(line)
        elif current_section == "todos" and line.strip():
            todos_lines.append(line)
        elif current_section == "decision" and line.strip():
            decision_lines.append(line)
    
    result = "📋 *会议纪要摘要*\n\n"
    if summary_lines:
        result += "\n".join(summary_lines[:5]) + "\n\n"
    if todos_lines:
        result += "✅ *待办事项*\n" + "\n".join(todos_lines[:10]) + "\n"
    return result

def filter_english(content):
    """筛选英文内容发工作群"""
    # 提取待办事项和决策（用 DeepSeek 筛选）
    api_key = get_deepseek_key()
    if not api_key:
        # fallback: 直接提取待办
        lines = content.split("\n")
        filtered = []
        in_todo = False
        for line in lines:
            if "待办事项" in line:
                in_todo = True
            if "关键决策" in line:
                in_todo = False
            if in_todo and line.strip():
                filtered.append(line)
        return "\n".join(filtered[:10])
    
    import requests
    
    prompt = f"""Extract actionable items and key decisions from this Chinese meeting note, output in English (brief, bullet points only):

{content[:3000]}

Output format:
**Meeting Updates**
- (bullet points in English)

**Action Items**
- (bullet points with owner in English)"""
    
    try:
        resp = requests.post(DEEPSEEK_API,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": DEEPSEEK_MODEL, "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.3, "max_tokens": 1500},
            timeout=60)
        return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception:
        return "[English summary unavailable]"

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="指定日期 YYYY-MM-DD")
    parser.add_argument("--force", choices=["daily", "weekly"], help="强制处理类型")
    parser.add_argument("--dry-run", action="store_true", help="试运行，不写入文档")
    args = parser.parse_args()
    
    date_str = args.date or today_wat()
    day_of_week = datetime.datetime.strptime(date_str, "%Y-%m-%d").weekday() if date_str.count("-") == 2 else 0
    
    # 自动判断会议类型
    if args.force:
        meeting_type = args.force
    elif day_of_week == 4:  # 周五
        meeting_type = "weekly"
    elif 0 <= day_of_week <= 4:  # 周一至五
        meeting_type = "daily"
    else:
        logger.info("Weekend — no meetings")
        return 0
    
    doc_token = WEEKLY_DOC_TOKEN if meeting_type == "weekly" else DAILY_MEETING_DOC
    meeting_label = "周会" if meeting_type == "weekly" else "日会"
    
    logger.info(f"Processing {meeting_label} for {date_str}")
    
    # 1. 搜索会议
    meetings = search_meetings(date_str)
    if not meetings:
        logger.info(f"No {meeting_label} found for {date_str}")
        # 日会没有时静默退出（可能是休息日）
        return 0 if meeting_type == "daily" else 1
    
    for meeting in meetings:
        meeting_id = meeting.get("meeting_id") or meeting.get("id")
        if not meeting_id:
            continue
        
        # 2. 获取妙记 token
        minute_token = get_minute_token(meeting_id)
        if not minute_token:
            logger.warning(f"No recording for meeting {meeting_id}")
            continue
        
        # 3. 获取妙记详情
        minute_detail = get_minute_detail(minute_token)
        
        # 4. 获取妙记内容
        minute_notes = get_minute_notes(minute_token)
        
        # 5. 获取 transcript（用于 LLM 降级）
        transcript = get_transcript(minute_token) if (not minute_notes or not minute_notes.get("todos")) else None
        
        # 6. 格式化为结构化纪要
        content, meeting_date, _ = format_notes(minute_notes, minute_detail, transcript)
        
        if args.dry_run:
            logger.info(f"[DRY RUN] Would update doc {doc_token}")
            print(content[:500])
            continue
        
        # 7. 写入飞书云文档
        ok = update_doc(doc_token, content, meeting_date)
        if not ok:
            logger.error("Failed to update doc")
            continue
        logger.info(f"Doc updated: {doc_token}")
        
        # 8. 中文私聊给冯立（union_id）
        cn_summary = summarize_chinese(content)
        send_message(FENGLI_OPEN_ID, f"📋 {meeting_label}纪要 — {meeting_date}\n\n{cn_summary}\n\n详细内容：https://transsioner.feishu.cn/docx/{doc_token}", recipient_type="union_id")
        logger.info("Chinese summary sent to Fengli")
        
        # 9. 英文筛选后发工作群
        en_summary = filter_english(content)
        if en_summary:
            send_message(WORK_CHAT_ID, f"📋 {meeting_label.upper()} Meeting — {meeting_date}\n\n{en_summary}\n\nFull notes: https://transsioner.feishu.cn/docx/{doc_token}", recipient_type="chat_id")
            logger.info("English summary sent to work chat")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
