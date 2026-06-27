#!/usr/bin/env python3
"""feishu_all_collector.py — 飞书全量采集（v3）

通过 lark-cli 以 user 身份采集：
1. 群列表 → lark-cli api im/v1/chats --as user --params '{"page_size":50}'
2. 群消息 → 遍历群列表，lark-cli api im/v1/messages --as user --params '{"container_id_type":"chat","container_id":"<chat_id>","page_size":50}'
3. 私聊 → 同样通过 im/v1/messages，container_id 是用户的 DM chat_id
4. Bitable/日历/云盘（兼容保留）

采集到的消息按日期写入第二大脑知识库：
  raw/feishu/YYYYMMDD/feishu_<chat_id>_YYYYMMDD.json

关键：
- user 身份才能采集私聊和群消息，bot 身份只能收发给自己的消息
- 全量采集默认 10 个关键群 + DM
- 消息去重：按 message_id 去重
"""
import sys, json, os, re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import setup_logger, RAW_DIR, today_str

logger = setup_logger("feishu_all_collector", "feishu_collector.log")

# lark-cli 全路径
_LARK_CLI = str(Path.home() / ".npm-global/bin/lark-cli")

# ── 关键群配置（默认采集的群 chat_id） ──
# DM（冯立私聊）
DM_CHAT_ID = "oc_110aebfae40be0864d19319de0e4d349"
# C&I Nigeria 工作群
WORK_CHAT_ID = "oc_25258127a0401e59b0bca9fe20aee436"
# 关键群列表（可从环境变量配置，默认前 10 个活跃群）
KEY_CHATS = os.environ.get("FEISHU_KEY_CHATS", "").split(",") if os.environ.get("FEISHU_KEY_CHATS") else []

# 消息去重集合（会话内持久）
_seen_message_ids = set()


def _run_lark(method, path, params=None, data=None, timeout=60):
    """调用 lark-cli API，返回 JSON"""
    import subprocess
    cmd = [_LARK_CLI, "api", method, path, "--as", "user", "--format", "json"]
    if params:
        cmd.extend(["--params", json.dumps(params)])
    if data is not None:
        cmd.extend(["--data", json.dumps(data)])
    try:
        # 构建可靠的子进程环境
        env = os.environ.copy()
        # 确保 HOME 存在（daemon/cron 环境可能缺失）
        env.setdefault("HOME", str(Path.home()))
        # 显式设置 LARK_CLI_PROFILE 指向 hermes 配置文件，避免依赖环境变量探测
        env["LARK_CLI_PROFILE"] = "hermes"
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        if r.returncode != 0:
            logger.warning(f"lark-cli error: {r.stderr[:200]}")
            return {"error": r.stderr[:200]}
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    except json.JSONDecodeError as e:
        return {"error": f"json: {e}"}


def collect_chat_list(page_size=50):
    """获取所有可见群列表"""
    logger.info("Collecting chat list...")
    result = _run_lark("GET", "im/v1/chats", {"page_size": page_size})
    if isinstance(result, dict) and result.get("ok"):
        items = result.get("data", {}).get("items", [])
        logger.info(f"  Got {len(items)} chats")
        return items
    logger.warning(f"  Failed: {result.get('error', 'unknown')}")
    return []


def collect_group_messages(chat_id, page_size=50, max_pages=5):
    """采集指定群/私聊的消息（支持翻页，最多5页=250条）"""
    all_items = []
    page_token = ""
    for _ in range(max_pages):
        params = {"container_id_type": "chat", "container_id": chat_id, "page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        result = _run_lark("GET", "im/v1/messages", params)
        if isinstance(result, dict) and result.get("ok"):
            items = result.get("data", {}).get("items", [])
            all_items.extend(items)
            if result.get("data", {}).get("has_more"):
                page_token = result.get("data", {}).get("page_token", "")
            else:
                break
        else:
            break

    # 去重
    new_items = []
    for item in all_items:
        mid = item.get("message_id", "")
        if mid and mid not in _seen_message_ids:
            _seen_message_ids.add(mid)
            new_items.append(item)
    return new_items


def save_messages(chat_id, messages, date_str=None):
    """按日期保存消息到文件"""
    if not messages:
        return 0
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")

    chat_dir = RAW_DIR / "feishu" / date_str
    chat_dir.mkdir(parents=True, exist_ok=True)

    out = chat_dir / f"feishu_{chat_id}_{date_str}.json"
    existing = []
    if out.exists():
        try:
            existing = json.loads(out.read_text())
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

    # 合并去重
    seen = {m.get("message_id", "") for m in existing}
    for m in messages:
        mid = m.get("message_id", "")
        if mid and mid not in seen:
            seen.add(mid)
            existing.append(m)

    out.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
    logger.info(f"  Saved {len(messages)} msgs → {out} (total {len(existing)})")
    return len(messages)


def collect_all():
    """全量采集：群列表 → 群消息 → 私聊"""
    date_str = datetime.now().strftime("%Y%m%d")
    total = 0

    # 1. 群列表
    chats = collect_chat_list()
    chat_ids = []

    # 提取关键群的 chat_id
    for c in chats:
        cid = c.get("chat_id", "")
        if cid:
            chat_ids.append(cid)

    # 添加 DM 和工作群
    if DM_CHAT_ID and DM_CHAT_ID not in chat_ids:
        chat_ids.append(DM_CHAT_ID)
    if WORK_CHAT_ID and WORK_CHAT_ID not in chat_ids:
        chat_ids.append(WORK_CHAT_ID)

    # 添加环境变量配置的关键群
    for kc in KEY_CHATS:
        if kc and kc not in chat_ids:
            chat_ids.append(kc)

    # 2. 采集每个群的消息（最多 10 个 + DM）
    max_chats = min(len(chat_ids), 12)
    for cid in chat_ids[:max_chats]:
        msgs = collect_group_messages(cid, page_size=50)
        if msgs:
            n = save_messages(cid, msgs, date_str)
            total += n
        # 不要太快，避免被限频
        import time
        time.sleep(1)

    logger.info(f"Total: {total} new messages from {max_chats} chats")
    return total


# ── 旧接口兼容（bitable/calendar/drive） ──
SOURCES_OLD = [
    ("bitable", "open-apis/bitable/v1/apps"),
    ("calendar", "open-apis/calendar/v4/calendars"),
    ("drive", "open-apis/drive/v1/files"),
]


def collect_old_sources():
    """采集 bitable/日历/云盘（兼容保留）"""
    for name, path in SOURCES_OLD:
        result = _run_lark("GET", path, timeout=60)
        if isinstance(result, dict) and "error" not in result:
            fd = RAW_DIR / "feishu"
            fd.mkdir(parents=True, exist_ok=True)
            out = fd / f"{name}_{today_str()}.json"
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            logger.info(f"{name}: collected")


def main():
    _seen_message_ids.clear()
    logger.info("=== Feishu all collector v3 start ===")
    n = collect_all()
    logger.info(f"Feishu all collector done: {n} new msgs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
