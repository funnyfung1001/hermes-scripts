#!/usr/bin/env python3
"""daily_briefing_generator.py — 简报内容生成器

读取已采集的数据，调用 DeepSeek 生成结构化简报，发送飞书卡片。
"""
import sys, json, datetime, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import (
    setup_logger, get_deepseek_key, SECOND_BRAIN, DAILY_DIR,
    today_wat, today_str, DEEPSEEK_API, DEEPSEEK_MODEL
)

logger = setup_logger("briefing_gen", "briefing_gen.log")

def collect_data():
    """收集今天已采集的原始数据，提取可读文本"""
    today = today_str()
    today_compact = today.replace("-", "")
    raw = SECOND_BRAIN / "raw"
    sections = {}
    
    # Feishu 群消息 — 提取可读文本（支持新目录结构 v3）
    feishu_dir = raw / "feishu"
    if feishu_dir.exists():
        files = []
        # v3 新结构: raw/feishu/YYYYMMDD/*.json
        date_subdir = feishu_dir / today_compact
        if date_subdir.exists():
            files.extend(sorted(date_subdir.glob("*.json"), reverse=True)[:5])
        # 旧结构: raw/feishu/*YYYYMMDD*.json
        for pat in [f"*{today}*", f"*{today_compact}*"]:
            files.extend(feishu_dir.glob(pat))
        files = sorted(set(files), key=lambda f: f.stat().st_mtime, reverse=True)[:5]
        
        readable = []
        for f in files:
            try:
                data = json.loads(f.read_text())
                msgs = data.get("data", {}).get("items", [])
                for m in msgs[:20]:
                    msg_type = m.get("msg_type", "")
                    body = m.get("body", {})
                    content = body.get("content", "")
                    sid = m.get("sender", {}).get("id", "?")[:20]
                    
                    text = content
                    if msg_type == "text":
                        try:
                            text = json.loads(content).get("text", text)
                        except Exception:
                            pass
                    elif msg_type == "post":
                        try:
                            pd = json.loads(content)
                            for k in ["zh_cn", "content", "zh_en"]:
                                sec = pd.get(k, pd)
                                if isinstance(sec, dict):
                                    lines = []
                                    for para in sec.get("content", []):
                                        if isinstance(para, list):
                                            t = "".join(s.get("text", "") for s in para if isinstance(s, dict))
                                            if t:
                                                lines.append(t)
                                    if lines:
                                        text = "\n".join(lines)
                                        break
                        except Exception:
                            pass
                    readable.append(f"[{sid}] {str(text)[:300]}")
            except Exception:
                readable.append(f"[文件: {f.name}] (解析错误)")
        sections["feishu"] = "\n".join(readable[:30])
    
    # Meetings
    meetings_dir = raw / "meetings"
    if meetings_dir.exists():
        files = []
        for pat in [f"*{today}*", f"*{today_compact}*"]:
            files.extend(meetings_dir.glob(pat))
        topics = []
        for f in files[:3]:
            try:
                data = json.loads(f.read_text())
                topics.append(str(data.get("topic", "?")))
            except Exception:
                pass
        sections["meetings"] = "\n".join(topics)
    
    return sections

def generate_with_local_llm(data):
    """调用本地32B生成简报（大内容自动分段）"""
    import requests

    feishu_data = data.get('feishu', '无')[:2000]
    meeting_data = data.get('meetings', '无')[:2000]

    prompt = f"""你是一个C&I Nigeria业务简报助手。请根据以下今日采集的数据，生成结构化的每日简报。

今日日期：{today_str()}

## 今日数据概览

### 飞书群消息摘要
{feishu_data}

### 会议纪要
{meeting_data}

请严格按以下格式输出（CN 中文版模板）：

### 📋 今日概览
（整体情况介绍，2-3句话）

### 📊 项目进展
- 项目/事项：状态

### 📈 市场动态
- 行业新闻/竞争情报

### 👥 团队与行政
- 团队事项/HR/财务

### ✅ 待办事项
| # | 事项 | 负责人 |
|---|------|--------|

### 📝 综合摘要
（200字以内）

注意：严格按以上顺序输出，不要调换。"""

    # 如果 prompt 超过 2500 字符，分段处理
    if len(prompt) > 2500:
        parts = prompt.split("\n\n### ")
        chunks = []
        current = parts[0]
        for part in parts[1:]:
            if len(current) + len(part) < 2000:
                current += "\n\n### " + part
            else:
                chunks.append(current)
                current = "### " + part
        if current:
            chunks.append(current)

        results = []
        for i, chunk in enumerate(chunks):
            try:
                resp = requests.post(
                    "http://localhost:8080/v1/chat/completions",
                    json={
                        "messages": [
                            {"role": "system", "content": f"你是C&I Nigeria业务简报助手。这是第{i+1}/{len(chunks)}部分分析。{'最后部分，请汇总全部内容输出完整报告。' if i == len(chunks)-1 else '分析以下内容的关键信息。'}"},
                            {"role": "user", "content": chunk}
                        ],
                        "max_tokens": 800,
                        "temperature": 0.1
                    },
                    timeout=600
                )
                if resp.status_code == 200:
                    part = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    if part:
                        results.append(part)
            except Exception:
                pass

        if results:
            return "\n\n".join(results)
        return ""

    try:
        resp = requests.post(
            "http://localhost:8080/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1500,
                "temperature": 0.1
            },
            timeout=600
        )
        if resp.status_code == 200:
            return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        logger.error(f"32B call failed: {e}")
    return ""

def send_briefing_card(content, recipient_id=None):
    """发送简报卡片"""
    sys.path.insert(0, str(Path(__file__).parent))
    from feishu_card_sender import send_card
    
    if not recipient_id:
        # 默认发到 Home 群
        recipient_id = "oc_110aebfae40be0864d19319de0e4d349"
    
    ok = send_card(
        recipient_id=recipient_id,
        title=f"📋 每日简报 — {today_str()}",
        body=content,
        recipient_type="chat_id"
    )
    return ok

def generate_and_send(recipient_id=None):
    """主要入口：采集→生成→发送（分语言）"""
    logger.info("Generating daily briefing...")
    
    data = collect_data()
    content = generate_with_local_llm(data)
    
    # 保存到 daily 目录
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    out = DAILY_DIR / f"briefing_{today_str()}.md"
    out.write_text(content)
    logger.info(f"Briefing saved: {out}")
    
    # 1. 写入飞书云文档（详细版）
    try:
        update_briefing_doc(content)
    except Exception as e:
        logger.warning(f"Doc update failed: {e}")
    
    # 2. 中文摘要 → 私聊给冯立（卡片+云文档链接）
    try:
        cn_summary = summarize_cn_briefing(content)
        sys.path.insert(0, str(Path(__file__).parent))
        from feishu_card_sender import send_card
        send_card(
            recipient_id="on_42429dc6344eee41ffa1d3f0858430e5",
            title=f"📋 每日简报 — {today_str()}",
            body=f"{cn_summary[:1500]}\n\n📄 详细全文：https://transsioner.feishu.cn/docx/IltidiIKDosnuSxBuiscyuapnng",
            recipient_type="union_id"
        )
    except Exception as e:
        logger.warning(f"CN send failed: {e}")

    # 3. 英文筛选 → 发工作群（C & I Nigeria，卡片+云文档链接）
    try:
        en_summary = filter_en_briefing(content)
        if en_summary:
            sys.path.insert(0, str(Path(__file__).parent))
            from feishu_card_sender import send_card
            send_card(
                recipient_id="oc_25258127a0401e59b0bca9fe20aee436",
                title=f"📋 DAILY BRIEFING — {today_str()}",
                body=f"{en_summary[:1500]}\n\n📄 Full: https://transsioner.feishu.cn/docx/CrsSdqt6cored0xXeEhciXhcnsd",
                recipient_type="chat_id"
            )
    except Exception as e:
        logger.warning(f"EN send failed: {e}")
    
    return True

def main():
    return 0 if generate_and_send() else 1

# ── 辅助函数：分语言发送 + 云文档 ─────────────────────────

def update_briefing_doc(content):
    """将详细简报写入飞书云文档（中文版+英文版）"""
    import subprocess, json
    from pathlib import Path
    _LARK_CLI = str(Path.home() / ".npm-global/bin/lark-cli")

    CN_DOC = "IltidiIKDosnuSxBuiscyuapnng"   # 日报中文完整版
    EN_DOC = "CrsSdqt6cored0xXeEhciXhcnsd"   # 日报英文版

    # 写中文版
    result_cn = subprocess.run(
        [_LARK_CLI, "docs", "+update", "--api-version", "v2",
         "--doc", CN_DOC,
         "--command", "append",
         "--content", f"\n## {today_str()}\n{content}\n"],
        capture_output=True, text=True, timeout=30
    )
    if result_cn.returncode == 0:
        logger.info(f"CN briefing doc updated: {CN_DOC}")
    else:
        logger.warning(f"CN doc update failed: {result_cn.stderr[:200]}")
    
    # 写英文版（用 DeepSeek 翻译/筛选）
    try:
        en_briefing = filter_en_briefing(content)
        if en_briefing:
            result_en = subprocess.run(
                [_LARK_CLI, "docs", "+update", "--api-version", "v2",
                 "--doc", EN_DOC,
                 "--command", "append",
                 "--content", f"\n## {today_str()}\n{en_briefing}\n"],
                capture_output=True, text=True, timeout=30
            )
            if result_en.returncode == 0:
                logger.info(f"EN briefing doc updated: {EN_DOC}")
    except Exception as e:
        logger.warning(f"EN doc update failed: {e}")
    
    return True

def send_feishu_message(recipient_id, text, recipient_type="open_id"):
    """发送飞书消息（走三狗 Bot HTTP API，不走 lark-cli CLI——避免 99992402 bug）"""
    sys.path.insert(0, str(Path(__file__).parent))
    from feishu_card_sender import send_text
    return send_text(recipient_id=recipient_id, text=text, recipient_type=recipient_type)

def summarize_cn_briefing(content):
    """从完整简报提取中文摘要"""
    return content[:1500]  # 简化为取前1500字

def filter_en_briefing(content):
    """用本地32B筛选英文工作群内容"""
    import requests
    prompt = f"""Extract key information from this Chinese daily briefing and output in English following this structure:

{content[:2000]}

Format:
**Overview**
(2-3 sentences)

**Project Updates**
- (bullet points)

**Market Intelligence**
- (bullet points)

**Action Items**
- (bullet points with owners)

**Summary**
(100 words max)"""
    try:
        resp = requests.post(
            "http://localhost:8080/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1000,
                "temperature": 0.1
            },
            timeout=600
        )
        if resp.status_code == 200:
            return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception:
        pass
    return ""

if __name__ == "__main__":
    sys.exit(main())
