#!/usr/bin/env python3
"""feishu_card_sender.py — 飞书卡片发送（三狗 Bot 身份）

发送消息卡片到飞书用户。由 daily_briefing_generator 等脚本调用。
"""
import json, time, os
from pathlib import Path

def _get_tenant_token():
    """获取 Bot tenant_token（自动刷新）"""
    token_file = Path.home() / ".hermes" / "feishu_sangou_tenant_token.json"
    app_id = "cli_a7bb82b4d1f8d013"
    app_secret = os.environ.get("SANGO_BOT_SECRET", "")
    
    if not app_secret:
        try:
            data = json.loads(token_file.read_text())
            app_secret = data.get("app_secret") or data.get("secret", "")
        except Exception:
            pass
    
    # 尝试从缓存读取有效的 token
    try:
        data = json.loads(token_file.read_text())
        token = data.get("tenant_token") or data.get("token", "")
        expires = data.get("expires_at", 0)
        if token and expires > time.time() + 60:
            return token
    except Exception:
        pass
    
    if not app_secret:
        return None
    
    # 刷新 token
    import requests
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10
    )
    data = resp.json()
    token = data.get("tenant_access_token")
    if token:
        # 缓存
        data["expires_at"] = time.time() + data.get("expire", 7200) - 120
        token_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return token

def send_card(recipient_id, title, body, sender="二狗"):
    """发送卡片消息"""
    token = _get_tenant_token()
    if not token:
        print("[feishu_card_sender] ERROR: no tenant token")
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
    
    import requests
    resp = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
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
    print(f"[feishu_card_sender] {'OK' if ok else 'FAIL'}: {title[:40]} → {recipient_id[:20]}")
    return ok
