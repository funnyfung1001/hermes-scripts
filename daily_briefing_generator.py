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
    """收集今天已采集的原始数据"""
    today = today_str()
    raw = SECOND_BRAIN / "raw"
    sections = {}
    
    # Feishu 群消息
    feishu_dir = raw / "feishu"
    if feishu_dir.exists():
        files = sorted(feishu_dir.glob(f"*{today}*"))
        sections["feishu"] = "\n".join(f.read_text()[:2000] for f in files[:3])
    
    # Meetings
    meetings_dir = raw / "meetings"
    if meetings_dir.exists():
        files = sorted(meetings_dir.glob(f"*{today}*"))
        sections["meetings"] = "\n".join(
            json.loads(f.read_text()).get("topic", "?") for f in files[:3]
            if f.suffix == ".json"
        )
    
    return sections

def generate_with_deepseek(data):
    """调用 DeepSeek 生成简报"""
    api_key = get_deepseek_key()
    if not api_key:
        logger.error("No DeepSeek API key")
        return "⚠ DeepSeek API key 未配置，简报生成失败。"
    
    import requests
    
    prompt = f"""你是一个业务简报助手。请根据以下今日采集的数据，生成一份简洁的飞书简报卡片内容（纯文本，支持Markdown）。

今日日期：{today_str()}

## 今日数据概览

### 飞书群消息摘要
{data.get('feishu', '无')[:1500]}

### 会议纪要
{data.get('meetings', '无')}

请按以下格式输出：
**📊 今日概览**
- 关键数字/进展
- 重要事项

**📌 待办关注**
- 需要跟进的议题

**📅 明日提醒**
- 已知安排"""
    
    resp = requests.post(
        DEEPSEEK_API,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": DEEPSEEK_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 2000
        },
        timeout=120
    )
    result = resp.json()
    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        logger.error(f"DeepSeek returned empty: {result}")
        return "⚠ 简报生成异常。"
    return content

def send_briefing_card(content, recipient_id=None):
    """发送简报卡片"""
    sys.path.insert(0, str(Path(__file__).parent))
    from feishu_card_sender import send_card
    
    if not recipient_id:
        # 默认发送给冯立
        recipient_id = "on_42429dc6344eee41ffa1d3f0858430e5"
    
    ok = send_card(
        recipient_id=recipient_id,
        title=f"📋 每日简报 — {today_str()}",
        body=content,
        sender="二狗"
    )
    return ok

def generate_and_send(recipient_id=None):
    """主要入口：采集→生成→发送"""
    logger.info("Generating daily briefing...")
    
    data = collect_data()
    content = generate_with_deepseek(data)
    
    # 保存到 daily 目录
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    out = DAILY_DIR / f"briefing_{today_str()}.md"
    out.write_text(content)
    logger.info(f"Briefing saved: {out}")
    
    # 发送
    ok = send_briefing_card(content, recipient_id)
    logger.info(f"Briefing sent: {ok}")
    return ok

def main():
    return 0 if generate_and_send() else 1

if __name__ == "__main__":
    sys.exit(main())
