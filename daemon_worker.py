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
    """无采集工作时做深度学习
    1. knowledge_link: 连接第二大脑中关联的知识片段
    2. deep_read: 深入阅读并总结一个raw文件
    3. cross_ref: 交叉验证多个数据源的同一主题
    全部使用本地32B模型，不调DeepSeek(信息安全)。
    """
    import random, requests
    
    # 检查本地模型是否空闲
    try:
        resp = requests.get(f"{LOCAL_LLM_ENDPOINT.replace('/v1/chat/completions','')}/v1/internal/queue-status", timeout=3)
        busy = resp.json().get("running", False)
        if busy:
            logger.debug("LLM busy, skip idle work")
            return False
    except Exception:
        pass
    
    # 选择空闲任务类型
    task_type = random.choice(["knowledge_link", "deep_read", "cross_ref"])
    
    if task_type == "knowledge_link":
        return _idle_knowledge_link()
    elif task_type == "deep_read":
        return _idle_deep_read()
    elif task_type == "cross_ref":
        return _idle_cross_ref()
    return False

def _get_recent_raw_files(days=3):
    """获取最近N天的raw文件"""
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(days=days)
    files = []
    for subdir in ["feishu", "whatsapp", "email", "meetings"]:
        d = RAW_DIR / subdir
        if d.exists():
            for f in sorted(d.iterdir(), reverse=True):
                if f.is_file():
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    if mtime > cutoff:
                        files.append(f)
    return files[:10]

def _idle_knowledge_link():
    """连接第二大脑中关联的知识片段"""
    logger.info("Idle: knowledge_link")
    files = _get_recent_raw_files(7)
    if len(files) < 2:
        return False
    
    # 取两个不同来源的文件
    srcs = set(f.parent.name for f in files)
    if len(srcs) < 2:
        return False
    
    f1 = files[0]
    f2 = files[-1]
    
    try:
        c1 = f1.read_text()[:1500]
        c2 = f2.read_text()[:1500]
    except Exception:
        return False
    
    prompt = f"""分析以下两段来自不同来源的信息是否存在关联和矛盾：

来源1 ({f1.parent.name}/{f1.name[:30]}):
{c1}

来源2 ({f2.parent.name}/{f2.name[:30]}):
{c2}

请回答：
1. 是否存在业务关联？
2. 是否存在时间线重叠？
3. 是否存在矛盾？
4. 综合结论（一句话）"""
    
    result = _call_llm_local(prompt, timeout=300)
    if result:
        out = RAW_DIR / "digest" / f"link_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"# knowledge_link\n\n来源1: {f1}\n来源2: {f2}\n\n{result}")
        logger.info(f"knowledge_link done: {out.name}")
        return True
    return False

def _idle_deep_read():
    """深度阅读并总结一个raw文件"""
    logger.info("Idle: deep_read")
    files = _get_recent_raw_files(3)
    if not files:
        return False
    
    f = files[0]
    try:
        content = f.read_text()[:3000]
    except Exception:
        return False
    
    prompt = f"""请深度阅读以下内容，提取关键信息：

来源: {f.parent.name}/{f.name[:40]}
内容:
{content}

请输出：
1. 核心主题（一句话）
2. 关键人物/公司
3. 待办事项或行动项
4. 时间线
5. 与C&I业务的关联"""
    
    result = _call_llm_local(prompt, timeout=300)
    if result:
        out = RAW_DIR / "digest" / f"deep_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"# deep_read\n\n来源: {f}\n\n{result}")
        logger.info(f"deep_read done: {out.name}")
        return True
    return False

def _idle_cross_ref():
    """交叉验证多个数据源的同一主题"""
    logger.info("Idle: cross_ref")
    files = _get_recent_raw_files(5)
    if len(files) < 2:
        return False
    
    contents = []
    for f in files[:3]:
        try:
            c = f.read_text()[:1000]
            contents.append(f"=== {f.parent.name}/{f.name} ===\n{c}")
        except Exception:
            pass
    
    if len(contents) < 2:
        return False
    
    prompt = f"""请交叉验证以下多个数据源的信息一致性：

{"".join(contents)}

请检查：
1. 各数据源对同一事件/人物的描述是否一致
2. 时间线是否吻合
3. 矛盾或补充信息
4. 可信度评估"""
    
    result = _call_llm_local(prompt, timeout=300)
    if result:
        out = RAW_DIR / "digest" / f"xref_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"# cross_ref\n\n{result}")
        logger.info(f"cross_ref done: {out.name}")
        return True
    return False

# ── 主循环 ──
def main():
    logger.info("Daemon worker tick start")
    worked = False
    
    # 1. WhatsApp 采集
    collect_whatsapp()
    t = threading.Thread(target=collect_feishu_groups, daemon=True)
    t.start()
    
    # 2. feishu_raw_collector（飞书群消息采集）
    try:
        import feishu_raw_collector
        feishu_raw_collector.collect_all_groups()
        feishu_raw_collector.collect_group_messages()
    except Exception as e:
        logger.debug(f"Feishu raw collect: {e}")
    
    # 3. 邮件采集
    try:
        import mail_reader
        mail_reader.collect_today_email()
    except Exception as e:
        logger.debug(f"Mail collect: {e}")
    
    # 4. 消化
    if digest_new_data():
        worked = True
    
    # 5. 空闲
    if not worked:
        idle_work()
    
    logger.info("Daemon worker tick done")
    return 0

if __name__ == "__main__":
    sys.exit(main())
