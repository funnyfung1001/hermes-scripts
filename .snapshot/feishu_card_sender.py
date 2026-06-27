#!/usr/bin/env python3
"""feishu_card_sender.py — 飞书消息发送（三狗 Bot 身份）

三狗 Bot 专用于发卡片和消息，不响应任何群消息。
由 daily_briefing_generator / meeting_notes_manager 调用。
从 .env 读取 SANGOU_APP_ID / SANGOU_APP_SECRET 获取 tenant_token。
"""
import json, time, os, requests
from pathlib import Path

HOME = Path.home()

def _get_tenant_token():
    """获取三狗 Bot tenant_token（自动刷新缓存）"""
    token_file = HOME / ".hermes" / "feishu_sangou_tenant_token.json"
    env_file = HOME / ".hermes" / ".env"

    # 从缓存读取
    try:
        data = json.loads(token_file.read_text())
        token = data.get("tenant_access_token") or data.get("token", "")
        expires = data.get("expires_at", 0)
        if token and expires > time.time() + 60:
            return token
    except Exception:
        pass

    # 从 .env 读取三狗配置
    app_id = ""
    app_secret = ""
    for line in open(env_file):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip("'\"")
        if k.strip() == "SANGOU_APP_ID":
            app_id = v
        elif k.strip() == "SANGOU_APP_SECRET":
            app_secret = v

    if not app_id or not app_secret:
        print("[feishu_card_sender] ERROR: SANGOU_APP_ID/SECRET not found")
        return None

    # 刷新 token
    try:
        resp = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=10
        )
        data = resp.json()
        token = data.get("tenant_access_token")
        if token:
            data["expires_at"] = time.time() + data.get("expire", 7200) - 120
            token_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        return token
    except Exception as e:
        print(f"[feishu_card_sender] Token error: {e}")
        return None


def send_card(recipient_id, title, body, recipient_type="chat_id"):
    """发送卡片消息

    Args:
        recipient_id: 接收者 ID（chat_id 或 open_id）
        title: 卡片标题
        body: 卡片正文（markdown）
        recipient_type: chat_id（群聊）或 open_id/union_id（私聊）
    """
    token = _get_tenant_token()
    if not token:
        return False

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "blue"
        },
        "elements": [
            {"tag": "markdown", "content": body}
        ]
    }

    try:
        resp = requests.post(
            f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={recipient_type}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={
                "receive_id": recipient_id,
                "msg_type": "interactive",
                "content": json.dumps(card)
            },
            timeout=15
        )
        result = resp.json()
        ok = result.get("code") == 0
        if ok:
            print(f"[feishu_card_sender] OK: {title[:30]} → {recipient_id[:20]}")
        else:
            print(f"[feishu_card_sender] FAIL: {title[:30]} → {recipient_id[:20]}: {result.get('msg','')}")
        return ok
    except Exception as e:
        print(f"[feishu_card_sender] ERROR: {e}")
        return False


def send_text(recipient_id, text, recipient_type="chat_id"):
    """发送纯文本消息（三狗 Bot 身份，HTTP API 直连）

    Args:
        recipient_id: 接收者 ID
        text: 文本内容
        recipient_type: chat_id（群聊）或 open_id/union_id（私聊）
    """
    token = _get_tenant_token()
    if not token:
        return False

    content = json.dumps({"text": text})

    try:
        resp = requests.post(
            f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={recipient_type}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={
                "receive_id": recipient_id,
                "msg_type": "text",
                "content": content
            },
            timeout=15
        )
        result = resp.json()
        ok = result.get("code") == 0
        if ok:
            print(f"[feishu_card_sender] text OK → {recipient_id[:20]}: {text[:40]}...")
        else:
            print(f"[feishu_card_sender] text FAIL → {recipient_id[:20]}: {result.get('msg','')}")
        return ok
    except Exception as e:
        print(f"[feishu_card_sender] text ERROR: {e}")
        return False
