#!/usr/bin/env python3
"""daemon_worker.py — 守护进程工作循环（v3：全量无跳过）

由 cron_runner.sh daemon 调度（每30分钟）。
全量采集所有数据源，全部交给本地32B做详细分析。

采集：WhatsApp群+私聊、飞书群+私聊、邮件
消化：每条数据都用32B仔细盘
空闲：knowledge_link / deep_read / cross_ref 循环
"""
import sys, json, time, os, threading, requests, random, subprocess
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import (
    setup_logger, SECOND_BRAIN, RAW_DIR, SCRIPTS,
    DEEPSEEK_API, DEEPSEEK_MODEL, get_deepseek_key,
    LOCAL_LLM_ENDPOINT, LOCAL_LLM_MODEL, HERMES
)

logger = setup_logger("daemon_worker", "daemon_worker.log")

# ── 本地32B（自动分段） ──
def call_llm(prompt, timeout=600):
    """调用本地32B模型，大内容自动分段"""
    import requests

    if len(prompt) > 2500:
        paragraphs = prompt.split("\n\n")
        chunks = []
        current = ""
        for para in paragraphs:
            if len(current) + len(para) < 2000:
                current += para + "\n\n"
            else:
                if current:
                    chunks.append(current.strip())
                current = para + "\n\n"
        if current:
            chunks.append(current.strip())
        if len(chunks) <= 1:
            chunks = [prompt[:2000]]

        results = []
        for i, chunk in enumerate(chunks):
            ctx = "分析第一部分。" if i == 0 else ("汇总前面分析，输出综合结论。" if i == len(chunks)-1 else "继续分析中间部分。")
            try:
                resp = requests.post(
                    LOCAL_LLM_ENDPOINT,
                    json={
                        "messages": [
                            {"role": "system", "content": f"你是C&I Nigeria业务分析师。{ctx}"},
                            {"role": "user", "content": f"[{i+1}/{len(chunks)}]\n{chunk}"}
                        ],
                        "max_tokens": 800,
                        "temperature": 0.1
                    },
                    timeout=timeout
                )
                if resp.status_code == 200:
                    part = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    if part:
                        results.append(part)
            except Exception:
                pass
        if results:
            return "\n\n---\n".join(results)
        return ""

    try:
        resp = requests.post(
            LOCAL_LLM_ENDPOINT,
            json={"messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.1, "max_tokens": 4096},
            timeout=timeout
        )
        return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        logger.error(f"LLM failed: {e}")
        return ""

# ── 1. WhatsApp 全量采集 ──
def collect_whatsapp():
    """采集 WhatsApp 消息"""
    # 从 .env 加载 Bridge 配置
    env_path = Path.home() / ".hermes" / ".env"
    if env_path.exists():
        for line in open(env_path):
            line = line.strip()
            if "WHATSAPP_BRIDGE" in line:
                raw = line.split("=", 1)[1].strip()
                os.environ["WHATSAPP_BRIDGE"] = raw.strip("\"'").strip("'")
                break
    bridge = os.environ.get("WHATSAPP_BRIDGE", "")
    if not bridge:
        logger.debug("WhatsApp bridge not configured")
        return

    # 读取 api_key
    env_path = Path.home() / ".hermes" / ".env"
    api_key = ""
    if env_path.exists():
        for line in open(env_path):
            line = line.strip()
            if "WHATSAPP_API_KEY" in line:
                raw = line.split("=", 1)[1].strip()
                api_key = raw.strip("'").strip('"')
                break

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        # 获取群列表
        r = requests.get(f"{bridge}/api/groups", headers=headers, timeout=30)
        if r.status_code != 200:
            return
        groups = r.json().get("groups", [])
        
        wd = RAW_DIR / "whatsapp"
        wd.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        
        # 全量采集每个群的消息
        for g in groups[:10]:  # 最多10个群
            gid = g.get("id", "")
            gname = g.get("name", "unknown")
            try:
                r2 = requests.get(f"{bridge}/api/groups/{gid}/messages?limit=50", headers=headers, timeout=30)
                if r2.status_code == 200:
                    msgs = r2.json().get("messages", r2.json())
                    if isinstance(msgs, list) and msgs:
                        import json
                        out = wd / f"wa_group_{gname}_{ts}.json"
                        out.write_text(json.dumps(msgs, ensure_ascii=False, indent=2))
                        logger.info(f"WA group {gname}: {len(msgs)} msgs")
            except Exception as e:
                logger.debug(f"WA group {gname}: {e}")
        
        # 私聊消息
        try:
            r3 = requests.get(f"{bridge}/api/chats?type=private&limit=50", headers=headers, timeout=30)
            if r3.status_code == 200:
                pmsgs = r3.json().get("messages", r3.json())
                if isinstance(pmsgs, list) and pmsgs:
                    out = wd / f"wa_private_{ts}.json"
                    out.write_text(json.dumps(pmsgs, ensure_ascii=False, indent=2))
                    logger.info(f"WA private: {len(pmsgs)} msgs")
        except Exception as e:
            logger.debug(f"WA private: {e}")
    except Exception as e:
        logger.debug(f"WhatsApp collect: {e}")

# ── 2. 飞书全量采集（群消息+私聊） ──
def collect_feishu_all():
    try:
        import feishu_raw_collector as frc
        frc.collect_all_groups()
        frc.collect_group_messages()
        logger.info("Feishu: groups + messages collected")
    except Exception as e:
        logger.debug(f"Feishu collect: {e}")

def collect_feishu_groups():
    """原后台线程辅助，保留兼容"""
    collect_feishu_all()

# ── 3. 邮件采集 ──
def collect_email():
    try:
        import mail_reader
        n = mail_reader.collect_today_email()
        if n > 0:
            logger.info(f"Email: {n} files")
    except Exception as e:
        logger.debug(f"Email: {e}")

# ── 4. 互联网情报 ──
def collect_internet_intel():
    """调用 internet_intel.py 采集"""
    try:
        import internet_intel
        internet_intel.main()
    except Exception as e:
        logger.debug(f"Internet intel: {e}")

# ── 5. 深度消化（每条数据都用32B仔细分析） ──
def deep_digest():
    """用32B仔细分析每一条新采集的raw数据"""
    cutoff = datetime.now() - timedelta(hours=2)
    raw_types = {
        "feishu": "飞书消息",
        "whatsapp": "WhatsApp消息",
        "email": "邮件",
        "meetings": "会议纪要"
    }
    
    digested = 0
    for dir_name, label in raw_types.items():
        d = RAW_DIR / dir_name
        if not d.exists():
            continue
        for f in sorted(d.iterdir(), reverse=True):
            if not f.is_file() or f.suffix in (".digested",):
                continue
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                continue
            
            try:
                content = f.read_text(encoding="utf-8", errors="replace")[:5000]
            except Exception:
                continue
            
            prompt = f"""你是一个C&I Nigeria业务分析师。请仔细分析以下{label}数据，提取所有有价值的信息。

数据来源：{f.parent.name}/{f.name}
数据大小：{len(content)}字符

请按以下格式输出分析报告：

## 📊 信息提取
- 关键人物
- 关键公司/项目
- 数字/金额/时间线
- 待办事项

## 🔗 业务关联
- 与C&I储能业务的关联
- 涉及的市场动态或竞争情报

## ⚠️ 异常标记
- 前后矛盾的描述
- 需要进一步确认的信息
- 时间线冲突

## 📝 综合摘要
（200字以内）

{content[:4000]}"""
            
            result = call_llm(prompt)
            if result:
                digest_dir = RAW_DIR / "digest"
                digest_dir.mkdir(parents=True, exist_ok=True)
                out = digest_dir / f"{dir_name}_{f.stem}_analysis.md"
                out.write_text(f"# {label}分析\n\n来源: {f}\n时间: {datetime.now().isoformat()}\n\n{result}")
                logger.info(f"Deep digest: {out.name}")
                digested += 1
    
    if digested:
        logger.info(f"Deep digest done: {digested} files")
    return digested > 0

# ── 6. idle_work（空闲深度学习） ──
def idle_work():
    """无采集工作时做深度学习：knowledge_link / deep_read / cross_ref"""
    try:
        resp = requests.get(
            LOCAL_LLM_ENDPOINT.replace("/v1/chat/completions", "/v1/internal/queue-status"),
            timeout=3
        )
        if resp.json().get("running", False):
            logger.debug("LLM busy, skip idle work")
            return False
    except Exception:
        pass
    
    task_type = random.choice(["knowledge_link", "deep_read", "cross_ref"])
    logger.info(f"Idle: {task_type}")
    
    if task_type == "knowledge_link":
        return _idle_knowledge_link()
    elif task_type == "deep_read":
        return _idle_deep_read()
    elif task_type == "cross_ref":
        return _idle_cross_ref()
    return False

def _get_raw_files(days=7):
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
    return files[:15]

def _idle_knowledge_link():
    """连接不同来源的知识片段"""
    files = _get_raw_files(7)
    if len(files) < 2:
        return False
    
    srcs = set(f.parent.name for f in files)
    if len(srcs) < 2:
        return False
    
    f1, f2 = files[0], files[-1]
    try:
        c1, c2 = f1.read_text()[:2000], f2.read_text()[:2000]
    except Exception:
        return False
    
    prompt = f"""请仔细分析以下两段来自不同来源的信息，找出关联和矛盾：

来源1 ({f1.parent.name}/{f1.name[:40]}):
{c1}

来源2 ({f2.parent.name}/{f2.name[:40]}):
{c2}

请逐项分析：
1. 业务关联度（高/中/低 + 理由）
2. 时间线交叉点
3. 矛盾点（如有）
4. 综合推论：这些信息组合在一起说明了什么业务现象？
5. 建议下一步行动"""
    
    result = call_llm(prompt, timeout=300)
    if result:
        out = RAW_DIR / "digest" / f"knowledge_link_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"# knowledge_link\n\n{f1}\n{f2}\n\n{result}")
        logger.info(f"knowledge_link done: {out.name}")
        return True
    return False

def _idle_deep_read():
    """深度阅读一个raw文件"""
    files = _get_raw_files(3)
    if not files:
        return False
    f = files[0]
    try:
        content = f.read_text()[:5000]
    except Exception:
        return False
    
    prompt = f"""请深度阅读以下内容，进行360度分析：

来源: {f.parent.name}/{f.name[:40]}

{content[:4000]}

请输出详细分析：
## 1. 核心主题
## 2. 关键人物与角色
## 3. 关键事件与时间线
## 4. 隐含的业务信息（未明说但可推断的）
## 5. 对C&I Nigeria业务的影响
## 6. 建议行动项
## 7. 与其他已知信息的关联假设"""
    
    result = call_llm(prompt, timeout=300)
    if result:
        out = RAW_DIR / "digest" / f"deep_read_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"# deep_read\n\n{f}\n\n{result}")
        logger.info(f"deep_read done: {out.name}")
        return True
    return False

def _idle_cross_ref():
    """多源交叉验证"""
    files = _get_raw_files(5)
    if len(files) < 2:
        return False
    
    contents = []
    for f in files[:4]:
        try:
            c = f.read_text()[:1500]
            contents.append(f"=== {f.parent.name}/{f.name} ===\n{c}")
        except Exception:
            pass
    if len(contents) < 2:
        return False
    
    prompt = f"""请交叉验证以下多个数据源的信息：

{"".join(contents)}

请详细分析：
1. 各源对同一事件描述的**一致程度**（完全一致/基本一致/有矛盾/完全矛盾）
2. **具体矛盾点**（列出矛盾的双方说法）
3. **可信度排序**（哪个来源更可信，理由）
4. **修正后的统一叙事**（综合所有源的最可能版本）
5. **信息缺口**（哪些关键信息缺失）"""
    
    result = call_llm(prompt, timeout=300)
    if result:
        out = RAW_DIR / "digest" / f"cross_ref_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"# cross_ref\n\n{result}")
        logger.info(f"cross_ref done: {out.name}")
        return True
    return False

# ── 主循环 ──
def main():
    logger.info("=== Daemon worker tick start ===")
    worked = False
    
    # 1. WhatsApp 全量采集
    collect_whatsapp()
    
    # 2. 飞书全量采集
    t = threading.Thread(target=collect_feishu_all, daemon=True)
    t.start()
    
    # 3. 邮件采集
    collect_email()
    
    # 4. 互联网情报
    collect_internet_intel()
    
    # 等待飞书采集完成（最多30秒）
    t.join(timeout=30)
    
    # 5. 深度消化（32B仔细分析每条数据）
    if deep_digest():
        worked = True

    # 6. 写入 OpenViking 向量库
    try:
        import openviking_ingest
        n = openviking_ingest.ingest_new_content()
        if n:
            logger.info(f"OpenViking ingest: {n} documents")
    except Exception as e:
        logger.debug(f"OpenViking ingest: {e}")

    # 7. 空闲深度学习
    if not worked:
        idle_work()
    
    logger.info("=== Daemon worker tick done ===")
    return 0

if __name__ == "__main__":
    sys.exit(main())
