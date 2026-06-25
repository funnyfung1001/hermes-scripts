#!/usr/bin/env python3
"""feishu_raw_collector.py — 飞书群消息/私聊采集

通过 lark-cli 以 user 身份采集飞书群消息和私聊消息。
由 daemon_worker.py 或 cron 调度。
"""
import sys, json, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import setup_logger, RAW_DIR, HERMES

logger = setup_logger("feishu_raw", "feishu_raw_collector.log")

# lark-cli 完整路径（cron/daemon 环境可能没有这个 PATH）
_LARK_CLI = str(Path.home() / ".npm-global/bin/lark-cli")

def _lark_api(method, path, params=None):
    import subprocess, shlex
    cmd = [_LARK_CLI, "api", method, path]
    if params:
        cmd.extend(["--params", shlex.quote(json.dumps(params))])
    cmd.extend(["--as", "user"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return {"error": r.stderr.strip()[:200]}
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except Exception as e:
        return {"error": str(e)}

def collect_group_messages(chat_id=None, page_size=20):
    """采集指定群的消息"""
    params = {"container_id_type": "chat", "page_size": page_size}
    if chat_id:
        params["container_id"] = chat_id
    
    result = _lark_api("GET", "im/v1/messages", params)
    if not isinstance(result, dict) or not result.get("ok"):
        err_msg = str(result.get("error")) if isinstance(result, dict) else str(result)
        logger.warning(f"Group message collect failed: {err_msg}")
        return []
    
    items = result.get("data", {}).get("items", [])
    if not isinstance(items, list):
        fd = RAW_DIR / "feishu"
        fd.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        out = fd / f"feishu_messages_{ts}.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        logger.info(f"Collected {len(items)} msgs → {out.name}")
    return items

def collect_all_groups():
    """采集所有可见群的列表"""
    result = _lark_api("GET", "im/v1/chats", {"page_size": 50})
    if isinstance(result, dict) and result.get("ok"):
        items = result.get("data", {}).get("items", [])
        fd = RAW_DIR / "feishu"
        fd.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        out = fd / f"chats_{ts}.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        logger.info(f"Collected {len(items)} chats → {out.name}")
        return items
    return []

def main():
    logger.info("Feishu raw collector start")
    collect_all_groups()
    collect_group_messages()
    logger.info("Feishu raw collector done")
    return 0

if __name__ == "__main__":
    sys.exit(main())
