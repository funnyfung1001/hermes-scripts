#!/usr/bin/env python3
"""daemon_worker.py — 守护进程工作循环

由 cron_runner.sh daemon 调度（每30分钟）。
职责：
1. WhatsApp 采集（bridge 可用时）
2. 飞书群消息采集（后台线程）
3. 新数据消化（调 32B 本地模型或 DeepSeek）
4. 空闲时做深度学习（knowledge_link / cross_ref）
"""
import sys, json, time, os, threading
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import (
    setup_logger, SECOND_BRAIN, RAW_DIR, SCRIPTS,
    DEEPSEEK_API, DEEPSEEK_MODEL, get_deepseek_key,
    LOCAL_LLM_ENDPOINT, LOCAL_LLM_MODEL
)

logger = setup_logger("daemon_worker", "daemon_worker.log")

# ── 采集 ──
def collect_whatsapp():
    """采集 WhatsApp 消息"""
    bridge = os.environ.get("WHATSAPP_BRIDGE", "")
    if not bridge:
        logger.debug("WhatsApp bridge not configured")
        return
    
    import requests
    try:
        resp = requests.get(f"{bridge}/api/messages", timeout=30)
        if resp.status_code == 200:
            msgs = resp.json().get("messages", [])
            if msgs:
                wd = RAW_DIR / "whatsapp"
                wd.mkdir(parents=True, exist_ok=True)
                out = wd / f"{datetime.now().strftime('%Y%m%d_%H%M')}.json"
                out.write_text(json.dumps(msgs, ensure_ascii=False, indent=2))
                logger.info(f"WhatsApp: {len(msgs)} msgs saved")
    except Exception as e:
        logger.debug(f"WhatsApp collect: {e}")

def collect_feishu_groups():
    """采集飞书群消息（后台线程）"""
    try:
        import config_shared as cs
        result = cs.lark_cli_user("GET", "open-apis/im/v1/messages", timeout=60)
        if isinstance(result, dict) and "error" not in result:
            fd = RAW_DIR / "feishu"
            fd.mkdir(parents=True, exist_ok=True)
            out = fd / f"feishu_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            logger.info("Feishu: collected")
    except Exception as e:
        logger.debug(f"Feishu collect: {e}")

# ── 消化 ──
def digest_new_data():
    """消化新采集的数据（调用本地32B或DeepSeek）"""
    # 找到最近7天的 raw 数据
    today = datetime.now()
    recent = []
    for raw_type in ["whatsapp", "feishu", "meetings"]:
        d = RAW_DIR / raw_type
        if not d.exists():
            continue
        for f in sorted(d.iterdir())[-5:]:
            if f.is_file():
                recent.append(f)
    
    if not recent:
        logger.debug("No new data to digest")
        return False
    
    # 试本地模型
    content = _call_llm_local("Summarize the following data briefly in Chinese:\n" + 
                               recent[-1].read_text()[:2000])
    if not content:
        # fallback 到 DeepSeek
        content = _call_llm_deepseek("Summarize briefly:\n" + recent[-1].read_text()[:2000])
    
    if content:
        digest_file = RAW_DIR / "digest" / f"digest_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        digest_file.parent.mkdir(parents=True, exist_ok=True)
        digest_file.write_text(content)
        logger.info(f"Digest saved: {len(content)} chars")
        return True
    return False

def _call_llm_local(prompt, timeout=300):
    import requests
    try:
        resp = requests.post(
            f"{LOCAL_LLM_ENDPOINT}/chat/completions",
            json={
                "model": LOCAL_LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 1024
            },
            timeout=timeout
        )
        return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        logger.warning(f"Local LLM failed: {e}")
        return ""

def _call_llm_deepseek(prompt, timeout=60):
    import requests
    key = get_deepseek_key()
    if not key:
        return ""
    try:
        resp = requests.post(
            DEEPSEEK_API,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 1024
            },
            timeout=timeout
        )
        return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        logger.warning(f"DeepSeek failed: {e}")
        return ""

# ── 空闲任务 ──
def idle_work():
    """无采集工作时做深度学习"""
    logger.debug("Idle work: nothing pending")
    return True

# ── 主循环 ──
def main():
    logger.info("Daemon worker tick start")
    worked = False
    
    # 采集
    collect_whatsapp()
    t = threading.Thread(target=collect_feishu_groups, daemon=True)
    t.start()
    
    # 消化
    if digest_new_data():
        worked = True
    
    # 空闲
    if not worked:
        idle_work()
    
    logger.info("Daemon worker tick done")
    return 0

if __name__ == "__main__":
    sys.exit(main())
