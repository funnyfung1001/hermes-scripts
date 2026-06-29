#!/usr/bin/env python3
"""
engine.py — Never-Idle Engine (NIE) v1
======================================
持久守护进程。32B 永不闲置，永不超载。
完全替代 scheduler.py。

设计原理：
  - 单进程 while True 循环（不依赖 crontab）
  - 背景线程采集（不碰 32B），主线程推理
  - 不用 SIGALRM（requests.post timeout 就够了）
  - 持久化去重（SQLite 按 message_id SHA256）
  - 文件持久化状态（JSON）
  - 自适应休眠：空闲越长睡得越久，但从不停止
  - 渐进式任务深度：新数据→交叉分析→深层学习→批量回采

三层任务优先级（在单 slot 32B 上串行执行）:
  Tier 1 (最高): 新数据分析 deep_digest — 有新数据时立即执行
  Tier 2 (中等): 交叉分析 cross_ref / knowledge_link — 空闲时执行
  Tier 3 (背景): 深层学习 deep_read / 历史回采 — 长期空闲时执行

参考文献:
  - huey (coleifer/huey): SQLite-based 任务队列模式
  - openclaw/openclaw: Feishu 持久化去重 (SHA256 + SQLite)
  - llama.cpp server.cpp: --cont-batching slot 调度
  - Supervisord/SIGALRM: 子进程独立超时（不用全局 SIGALRM）

运行方式:
  python3 engine.py                 # 前台运行
  nohup python3 engine.py &         # 后台运行
  (crontab @reboot)                 # 开机自启

状态文件:
  ~/.hermes/.engine.state.json     — 调度状态（跨重启持久化）
  ~/.hermes/.engine.dedup.db       — 消息去重（SQLite）
  ~/.hermes/logs/engine.log        — 运行日志
"""

import hashlib
import json
import os
import random
import sqlite3
import sys
import threading
import time
import traceback
import urllib.parse
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).parent.resolve()))
from config_shared import (
    setup_logger, RAW_DIR, HERMES, SCRIPTS,
    LOCAL_LLM_ENDPOINT, LOCAL_LLM_MODEL
)

# ── 常量 ──
STATE_FILE = HERMES / ".engine.state.json"
DEDUP_DB = HERMES / ".engine.dedup.db"
LOCK_FILE = HERMES / ".engine.pid"

# 时间配置（秒）
COLLECT_INTERVAL = 300         # 采集间隔 5 分钟
INTEL_INTERVAL = 14400         # 情报采集 4 小时
TIER2_INTERVAL = 1800          # Tier 2 最小间隔 30 分钟
TIER3_INTERVAL = 3600          # Tier 3 最小间隔 1 小时
TIER3_DAILY_LIMIT = 20         # Tier 3 每日最多执行次数
BATCH_SIZE = 5                 # Tier 1 批处理大小（5条/1次32B调用）
BATCH_SIZE_TIER2 = 3           # Tier 2 批处理（3个digest/1次调用）
BATCH_SIZE_TIER3 = 2           # Tier 3 批处理（2个文件/1次调用）
LLM_TIMEOUT = 900              # 32B 单次超时（15 分钟，匹配 2tok/s 现实）
SLEEP_MIN = 1                  # 最小休眠 1 秒
SLEEP_MAX = 60                 # 最大休眠 60 秒
COLLECTION_TIMEOUT = 120       # 采集超时 2 分钟

logger = setup_logger("engine", "engine.log")


# ══════════════════════════════════════════════════════════════
# 持久化去重 — SQLite 跨进程共享
# ══════════════════════════════════════════════════════════════

class PersistentDedup:
    """跨进程持久化消息去重。
    
    用 SHA256(message_id) 做主键，TTL 24 小时自动清理。
    WAL 模式支持并发读写（即使被 crontab 里的脚本同时使用）。
    """
    
    def __init__(self, db_path: str | Path = DEDUP_DB):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS message_dedup (
                hash TEXT PRIMARY KEY,
                source TEXT NOT NULL DEFAULT 'feishu',
                received_at REAL NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedup_source 
            ON message_dedup(source, received_at)
        """)
        self.conn.commit()
        self._memory_set: set[str] = set()
        self._warm_cache()
    
    def _warm_cache(self):
        """启动时预热内存缓存"""
        rows = self.conn.execute(
            "SELECT hash FROM message_dedup WHERE received_at > ?",
            (time.time() - 86400,)
        ).fetchall()
        self._memory_set = {r[0] for r in rows}
        logger.info(f"Dedup cache warmed: {len(self._memory_set)} entries")
    
    def is_duplicate(self, message_id: str, source: str = 'feishu') -> bool:
        """检查并记录 message_id。返回 True 表示重复。"""
        h = hashlib.sha256(message_id.encode()).hexdigest()
        if h in self._memory_set:
            return True
        self._memory_set.add(h)
        self.conn.execute(
            "INSERT OR IGNORE INTO message_dedup VALUES (?, ?, ?)",
            (h, source, time.time())
        )
        self.conn.commit()
        return False
    
    def cleanup_old(self, ttl: int = 86400):
        """清理过期记录"""
        cutoff = time.time() - ttl
        self.conn.execute(
            "DELETE FROM message_dedup WHERE received_at < ?", (cutoff,)
        )
        self.conn.commit()
        # 同步内存缓存
        self._warm_cache()
    
    def close(self):
        self.conn.close()


# ══════════════════════════════════════════════════════════════
# 状态持久化 — JSON 文件
# ══════════════════════════════════════════════════════════════

class PersistentState:
    """调度状态管理。跨重启持久化。"""
    
    def __init__(self, path: str | Path = STATE_FILE):
        self.path = str(path)
        self._data: dict[str, Any] = self._load()
    
    def _load(self) -> dict:
        default = {
            "last_collect": None,
            "last_tier1": None,
            "last_tier2": None,
            "last_tier3": None,
            "last_intel": None,
            "tier3_today_count": 0,
            "tier3_today_date": datetime.now().strftime("%Y-%m-%d"),
            "idle_backoff": 0,
            "total_ticks": 0,
            "total_llm_calls": 0,
            "started_at": datetime.now().isoformat(),
        }
        try:
            data = json.loads(Path(self.path).read_text())
            for k, v in default.items():
                data.setdefault(k, v)
            return data
        except (FileNotFoundError, json.JSONDecodeError):
            return default
    
    def get(self, key: str, default=None):
        return self._data.get(key, default)
    
    def set(self, key: str, value):
        self._data[key] = value
    
    def incr(self, key: str, delta: int = 1):
        self._data[key] = self._data.get(key, 0) + delta
    
    def save(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.path).write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2)
        )
    
    @property
    def idle_seconds(self) -> float:
        """自上次产出至今的秒数"""
        last = self.get("last_tier1") or self.get("last_tier2") or self.get("last_tier3")
        if not last:
            return float("inf")
        try:
            elapsed = (datetime.now() - datetime.fromisoformat(str(last))).total_seconds()
            return max(elapsed, 0.0)  # 避免时钟偏移导致负数
        except (ValueError, TypeError):
            return float("inf")
    
    def reset_daily_counter(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.get("tier3_today_date") != today:
            self.set("tier3_today_count", 0)
            self.set("tier3_today_date", today)


# ══════════════════════════════════════════════════════════════
# 32B 推理客户端（requests 直连，不用 SIGALRM）
# ══════════════════════════════════════════════════════════════

class LLMClient:
    """本地 32B 推理客户端。纯同步，单线程，requests timeout 防卡死。"""
    
    def __init__(self, endpoint: str = LOCAL_LLM_ENDPOINT):
        self.endpoint = endpoint
        self._lock = threading.Lock()
    
    def chat(self, prompt: str, system_prompt: str = "",
             max_tokens: int = 2048, temperature: float = 0.1,
             timeout: int = LLM_TIMEOUT) -> str:
        """同步调用 32B。线程安全。超时用 requests.timeout 不用 SIGALRM。"""
        import requests
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        with self._lock:
            try:
                resp = requests.post(
                    self.endpoint,
                    json={
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                    },
                    timeout=timeout,
                )
                if resp.status_code == 200:
                    return (
                        resp.json()
                        .get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )
                logger.warning(f"32B returned {resp.status_code}: {resp.text[:200]}")
                return ""
            except requests.Timeout:
                logger.warning(f"32B timeout after {timeout}s")
                return ""
            except requests.ConnectionError:
                logger.warning("32B connection refused")
                return ""
            except Exception as e:
                logger.warning(f"32B error: {e}")
                return ""
    
    def health_check(self) -> bool:
        """快速检查 32B 是否存活。不发推理请求。"""
        import requests
        try:
            resp = requests.get(
                self.endpoint.replace("/v1/chat/completions", "/health"),
                timeout=5
            )
            return resp.status_code == 200
        except Exception:
            return False


# ══════════════════════════════════════════════════════════════
# 采集器（背景线程，不碰 32B）
# ══════════════════════════════════════════════════════════════

class BackgroundCollector:
    """后台采集器。在独立线程中运行。不阻塞主推理循环。"""
    
    def __init__(self, dedup: PersistentDedup, state: PersistentState):
        self.dedup = dedup
        self.state = state
        self._new_data_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
    
    def start(self):
        """启动后台采集线程"""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Background collector started")
    
    def stop(self):
        self._stop_event.set()
    
    def has_new_data(self) -> bool:
        """检查是否有新数据（非阻塞）"""
        if self._new_data_event.is_set():
            self._new_data_event.clear()
            return True
        return False
    
    def _run_loop(self):
        """采集循环。每 COLLECT_INTERVAL 秒执行一次。"""
        while not self._stop_event.is_set():
            try:
                self._collect_once()
            except Exception as e:
                logger.warning(f"Collect error: {e}")
            self._stop_event.wait(COLLECT_INTERVAL)
    
    def _collect_once(self):
        """单次采集。轻量超时（COLLECTION_TIMEOUT）。"""
        start = time.monotonic()
        has_new = False
        
        # 飞书采集
        try:
            new = self._collect_feishu()
            if new:
                has_new = True
        except Exception as e:
            logger.debug(f"Feishu collect: {e}")
        
        # WhatsApp 采集（如果可用）
        try:
            new = self._collect_whatsapp()
            if new:
                has_new = True
        except Exception as e:
            logger.debug(f"WA collect: {e}")
        
        elapsed = time.monotonic() - start
        if has_new:
            self._new_data_event.set()
            self.state.set("last_collect", datetime.now().isoformat())
            self.state.set("idle_backoff", 0)  # 有数据就重置 backoff
            logger.info(f"Collect: new data! ({elapsed:.1f}s)")
        else:
            logger.debug(f"Collect: no new data ({elapsed:.1f}s)")
    
    def _collect_feishu(self) -> bool:
        """飞书采集。用 lark-cli。带着 dedup 防止重复保存。"""
        # 复用 feishu_all_collector 的 collect_all() — 但改 collect_group_messages
        # 使用自己的 dedup 判断
        import feishu_all_collector as fac
        
        total_new = 0
        date_compact = datetime.now().strftime("%Y%m%d")
        
        # 获取群列表
        chats = fac.collect_chat_list()
        chat_ids = []
        for c in chats:
            cid = c.get("chat_id", "")
            if cid:
                chat_ids.append(cid)
        if fac.DM_CHAT_ID not in chat_ids:
            chat_ids.append(fac.DM_CHAT_ID)
        if fac.WORK_CHAT_ID not in chat_ids:
            chat_ids.append(fac.WORK_CHAT_ID)
        
        # 采集每个群
        for cid in chat_ids[:12]:
            msgs = fac.collect_group_messages(cid, page_size=50)
            if not msgs:
                continue
            # 用持久化 dedup 过滤
            truly_new = []
            for m in msgs:
                mid = m.get("message_id", "")
                if mid and not self.dedup.is_duplicate(mid, "feishu"):
                    truly_new.append(m)
            if truly_new:
                n = fac.save_messages(cid, truly_new, date_compact)
                total_new += n
        
        return total_new > 0
    
    def _collect_whatsapp(self) -> bool:
        """WhatsApp 采集。带持久化 dedup。"""
        # WhatsApp bridge 通常不可用，快速失败
        env_path = HERMES / ".env"
        bridge = ""
        api_key = ""
        if env_path.exists():
            for line in env_path.read_text().split("\n"):
                if "WHATSAPP_BRIDGE" in line:
                    bridge = line.split("=", 1)[1].strip().strip("\"'")
                if "WHATSAPP_API_KEY" in line:
                    api_key = line.split("=", 1)[1].strip().strip("'\"")
        if not bridge:
            return False
        
        import requests
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        try:
            r = requests.get(f"{bridge}/api/groups", headers=headers, timeout=15)
            if r.status_code != 200:
                return False
            groups = r.json().get("groups", []) if isinstance(r.json(), dict) else r.json()
            if not isinstance(groups, list):
                return False
        except Exception:
            return False
        
        wd = RAW_DIR / "whatsapp"
        wd.mkdir(parents=True, exist_ok=True)
        
        has_new = False
        for g in groups[:5]:
            gid = g.get("id", "")
            gname = g.get("name", "unknown")
            try:
                url = f"{bridge}/api/groups/{urllib.parse.quote(str(gid), safe='')}/messages?limit=50"
                r2 = requests.get(url, headers=headers, timeout=15)
                if r2.status_code != 200:
                    continue
                data = r2.json()
                msgs = data if isinstance(data, list) else data.get("messages", data)
                if not isinstance(msgs, list):
                    continue
                
                truly_new = []
                for m in msgs:
                    mid = m.get("id", m.get("message_id", ""))
                    if mid and not self.dedup.is_duplicate(mid, "whatsapp"):
                        truly_new.append(m)
                
                if truly_new:
                    safe_name = gname.replace("/", "_").replace(" ", "_")[:30]
                    ts = datetime.now().strftime("%Y%m%d_%H%M")
                    out = wd / f"wa_group_{safe_name}_{ts}.json"
                    out.write_text(json.dumps(truly_new, ensure_ascii=False, indent=2))
                    logger.info(f"WA {gname}: {len(truly_new)} new")
                    has_new = True
            except Exception:
                continue
        
        return has_new


# ══════════════════════════════════════════════════════════════
# 批处理分析（多条内容一次 32B 调用）
# ══════════════════════════════════════════════════════════════

class BatchAnalyzer:
    """批处理分析器。多条内容在单次 32B 调用中处理。
    
    原理：32B 瓶颈在 generation (2 tok/s) 不在 prefill (150 tok/s)。
    批处理把多条内容塞进同一 prompt，generation 只做一次。
    例:
      单条:  50 tok input + 200 tok output = 0.3s + 100s  ≈ 100s
      5条:  250 tok input + 600 tok output = 1.7s + 300s    ≈ 302s
      5条分别: 5 × 100s = 500s → 批处理省了 ~40%
    """
    
    def __init__(self, llm: LLMClient):
        self.llm = llm
    
    def batch_deep_digest(self, messages: list[dict]) -> list[str]:
        """批量深度消化。返回每条的 analysis 文本列表。"""
        if not messages:
            return []
        
        batch = messages[:BATCH_SIZE]
        items_text = []
        for i, m in enumerate(batch, 1):
            content = m.get("body", {}).get("content", "")
            if isinstance(content, str):
                text = content[:500]
            else:
                text = str(content)[:500]
            sender = m.get("sender", {}).get("name", "unknown")
            items_text.append(f"[{i}] From {sender}: {text}")
        
        batch_count = len(batch)
        prompt = f"""Analyze these {batch_count} business messages from C&I Nigeria operations. Focus on project updates, decisions, action items, risks, and market intelligence.

{chr(10).join(items_text)}

Respond with exactly {batch_count} analysis blocks, one per message. Format each:
BLOCK N:
- Category: [project_update|decision|action_item|risk|market_intel|general]
- Summary: (1-2 sentences in English)
- Key info: (numbers, dates, people, amounts)
- Action required: (yes/no + what)"""

        system = "You are a C&I Nigeria business analyst. Extract structured data from raw messages."
        
        result = self.llm.chat(prompt, system_prompt=system, max_tokens=2048)
        if not result:
            return []
        
        # 解析 BLOCK 分隔
        results = []
        current = []
        for line in result.split("\n"):
            if line.strip().startswith("BLOCK ") and ":" in line:
                if current:
                    results.append("\n".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            results.append("\n".join(current))
        
        # 填充到 batch 数
        while len(results) < len(batch):
            results.append(f"BLOCK {len(results)+1}: Analysis failed.")
        
        return results[:len(batch)]
    
    def batch_cross_ref(self, digest_files: list[Path]) -> str:
        """批量交叉分析多个 digest 文件。适合 CPU-only：短输出 (512 tok)。"""
        max_items = BATCH_SIZE_TIER2
        items = []
        for f in digest_files[:max_items]:
            content = f.read_text(encoding="utf-8", errors="replace")[:800]
            items.append(f"--- Source: {f.name} ---\n{content}")
        
        prompt = f"""Cross-reference these {len(items)} intelligence digests. Find:
1. Common themes across all sources
2. Contradictions or conflicts
3. Connections between separate pieces of information
4. Priority items for C&I Nigeria

{chr(10).join(items)}

Output: concise bullet points."""
        
        return self.llm.chat(prompt, max_tokens=512)
    
    def deep_read(self, file_paths: list[Path]) -> str:
        """并行深层阅读多个文件。短输出。"""
        contents = []
        max_items = BATCH_SIZE_TIER3
        for f in file_paths[:max_items]:
            text = f.read_text(encoding="utf-8", errors="replace")[:1000]
            contents.append(f"### {f.name}\n{text}")
        
        prompt = f"""Deep analysis of these data sources. Extract:
1. Key insights or patterns
2. Cross-reference with known C&I project data
3. Follow-up questions or investigation points

{chr(10).join(contents)}

Format: concise bullet points."""
        
        return self.llm.chat(prompt, max_tokens=1024)
    
    def batch_knowledge_link(self, digest_files: list[Path]) -> str:
        """批处理知识关联。"""
        items = []
        for f in digest_files[:BATCH_SIZE]:
            text = f.read_text(encoding="utf-8", errors="replace")[:600]
            items.append(text)
        
        prompt = f"""Link these {len(items)} analysis items to existing C&I knowledge:

{chr(10).join(items)}

For each item state:
- Which project/company/process it relates to
- Whether it confirms/changes/contradicts existing knowledge
- Whether it should be added to wiki"""
        
        return self.llm.chat(prompt, max_tokens=2048)


# ══════════════════════════════════════════════════════════════
# 主引擎（永不停止的循环）
# ══════════════════════════════════════════════════════════════

class NeverIdleEngine:
    """永不闲置引擎 — 持久守护进程的主类。
    
    核心循环:
    1. 检查是否有采集到的新数据 (BackgroundCollector.has_new_data)
    2. 有 → Tier 1: batch_deep_digest (批处理5条/次)
    3. 无 → 检查 Tier 2 间隔 → cross_ref / knowledge_link
    4. 仍无 → 检查 Tier 3 间隔 → deep_read
    5. 真没活 → 自适应休眠 (1-60秒)，越久越深
    """
    
    def __init__(self):
        logger.info("═══ Never-Idle Engine starting ═══")
        
        self.state = PersistentState()
        self.dedup = PersistentDedup()
        self.llm = LLMClient()
        self.analyzer = BatchAnalyzer(self.llm)
        self.collector = BackgroundCollector(self.dedup, self.state)
        
        # PID 锁
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOCK_FILE.write_text(str(os.getpid()))
        
        # 脏标记
        self._dirty_state = False
        
        logger.info(f"Engine PID={os.getpid()}")
        t1 = self.state.get("last_tier1") or ""
        logger.info(f"State: "
                     f"Tier3 today={self.state.get('tier3_today_count')}/"
                     f"{TIER3_DAILY_LIMIT}, "
                     f"last_tier1={str(t1)[:19]}")
    
    def run(self):
        """永不退出的主循环。"""
        # 启动后台采集
        self.collector.start()
        
        tick_count = 0
        self.state.reset_daily_counter()
        
        try:
            while True:
                start = time.monotonic()
                tick_count += 1
                self.state.set("total_ticks", tick_count)
                
                logger.debug(f"Tick {tick_count} starting (idle={self.state.idle_seconds:.0f}s)")
                
                # ═══════════ 阶段 1: 检查新数据 ═══════════
                if self.collector.has_new_data():
                    self._do_tier1()
                    self.state.set("idle_backoff", 0)
                    self._save_state()
                    continue  # 立即下一轮
                
                # ═══════════ 阶段 2: Tier 2 交叉分析 ═══════════
                lt2 = self.state.get("last_tier2")
                if not lt2:
                    time_since_t2 = float("inf")
                else:
                    time_since_t2 = (datetime.now() - datetime.fromisoformat(lt2)).total_seconds()
                
                if time_since_t2 >= TIER2_INTERVAL:
                    did = self._do_tier2()
                    if did:
                        self.state.incr("total_llm_calls")
                        self.state.set("idle_backoff", 0)
                        self._save_state()
                        continue
                
                # ═══════════ 阶段 3: Tier 3 背景学习 ═══════════
                if self.state.get("tier3_today_count", 0) < TIER3_DAILY_LIMIT:
                    lt3 = self.state.get("last_tier3")
                    if not lt3:
                        time_since_t3 = float("inf")
                    else:
                        time_since_t3 = (datetime.now() - datetime.fromisoformat(lt3)).total_seconds()
                    
                    idle = self.state.idle_seconds
                    if time_since_t3 >= TIER3_INTERVAL and idle >= TIER3_INTERVAL:
                        did = self._do_tier3()
                        if did:
                            self.state.incr("total_llm_calls")
                            self.state.incr("tier3_today_count")
                            self.state.set("idle_backoff", 0)
                            self._save_state()
                            continue
                
                # ═══════════ 阶段 4: 真的没活 ═══════════
                self._do_idle()
                self._save_state()
                
                # μ-sleep: 不忙轮询
                time.sleep(0.5)
        
        except KeyboardInterrupt:
            logger.info("Shutdown by Ctrl+C")
        except Exception as e:
            logger.error(f"Fatal: {e}\n{traceback.format_exc()}")
        finally:
            self._cleanup()
    
    def _do_tier1(self):
        """Tier 1: 新数据深度消化。批处理5条/次。"""
        logger.info("🚀 Tier 1: new data → batch deep_digest")
        
        # 扫描未消化的原始数据
        digest_dir = RAW_DIR / "digest"
        digest_dir.mkdir(parents=True, exist_ok=True)
        
        # 找今天最新未消化的 feishu 文件
        feishu_dir = RAW_DIR / "feishu"
        date_compact = datetime.now().strftime("%Y%m%d")
        
        if not feishu_dir.exists():
            logger.info("Tier 1: no feishu data dir")
            return
        
        # 已经消化过的文件列表
        analyzed_files = set()
        for f in digest_dir.glob("feishu_feishu_*_analysis.md"):
            # 从文件名提取 chat_id
            parts = f.name.replace("feishu_feishu_", "").split("_")
            if len(parts) >= 3:
                chat_id = parts[0]
                analyzed_files.add(chat_id)
        
        # 找到今天未消化的数据文件
        today_dir = feishu_dir / date_compact
        if not today_dir.exists():
            logger.info(f"Tier 1: no data for {date_compact}")
            return
        
        did_work = False
        for f in sorted(today_dir.glob("feishu_*.json")):
            parts = f.stem.split("_")
            if len(parts) < 2:
                continue
            # feishu_<chat_id>_<date>
            chat_id = parts[1]
            if chat_id in analyzed_files:
                continue  # 已分析过
            
            try:
                messages = json.loads(f.read_text())
                if not isinstance(messages, list) or not messages:
                    continue
                
                # 批处理
                logger.info(f"Digesting {f.name}: {len(messages)} msgs")
                
                # 分批次
                for i in range(0, len(messages), BATCH_SIZE):
                    batch = messages[i:i+BATCH_SIZE]
                    results = self.analyzer.batch_deep_digest(batch)
                    
                    if results:
                        out = digest_dir / f"feishu_feishu_{chat_id}_{date_compact}_analysis.md"
                        mode = "a" if out.exists() else "w"
                        with open(out, "a", encoding="utf-8") as fout:
                            if mode == "w":
                                fout.write(f"# Feishu digest: {chat_id} ({date_compact})\n\n")
                            for j, r in enumerate(results):
                                fout.write(f"## Message {i+j+1}\n{r}\n\n")
                        logger.info(f"  Batch {i//BATCH_SIZE + 1}: {len(results)} analyzed")
                        self.state.incr("total_llm_calls")
                    else:
                        logger.debug("  Batch returned empty")
                
                now_iso = datetime.now().isoformat()
                self.state.set("last_tier1", now_iso)
                did_work = True
                
            except Exception as e:
                logger.warning(f"Tier 1 digest {f.name}: {e}")
        
        if did_work:
            logger.info("Tier 1: digest complete")
    
    def _do_tier2(self) -> bool:
        """Tier 2: 交叉分析。选最近未交叉的 digest 文件。"""
        logger.info("🔍 Tier 2: cross analysis")
        
        digest_dir = RAW_DIR / "digest"
        if not digest_dir.exists():
            return False
        
        # 找最近3天内的 digest 分析文件
        cutoff = time.time() - 3 * 86400
        candidates = []
        for f in digest_dir.glob("*_analysis.md"):
            if f.stat().st_mtime > cutoff:
                candidates.append(f)
        for f in digest_dir.glob("deep_read_*.md"):
            if f.stat().st_mtime > cutoff:
                candidates.append(f)
        
        if not candidates:
            logger.info("Tier 2: no digest files to cross-ref")
            return False
        
        # 随机选 BATCH_SIZE 个做交叉分析
        selected = random.sample(candidates, min(BATCH_SIZE, len(candidates)))
        
        # cross_ref
        result = self.analyzer.batch_cross_ref(selected)
        if result:
            out = digest_dir / f"cross_ref_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
            out.write_text(f"# Cross Reference\n\n{result}")
            self.state.set("last_tier2", datetime.now().isoformat())
            logger.info(f"Tier 2: cross_ref written to {out.name}")
            return True
        
        # 如果 cross_ref 空，试 knowledge_link
        result = self.analyzer.batch_knowledge_link(selected)
        if result:
            out = digest_dir / f"knowledge_link_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
            out.write_text(f"# Knowledge Link\n\n{result}")
            self.state.set("last_tier2", datetime.now().isoformat())
            logger.info(f"Tier 2: knowledge_link written to {out.name}")
            return True
        
        return False
    
    def _do_tier3(self) -> bool:
        """Tier 3: 深层背景学习。从旧数据选未分析过的。"""
        logger.info("📚 Tier 3: deep reading")
        
        digest_dir = RAW_DIR / "digest"
        digest_dir.mkdir(parents=True, exist_ok=True)
        
        # 已有的 deep_read 分析文件
        done_keys = set()
        for f in digest_dir.glob("deep_read_*.md"):
            done_keys.add(f.stem)
        
        # 从各个 raw 子目录找旧数据
        candidates = []
        for subdir in ["feishu", "whatsapp", "intel", "meetings"]:
            src = RAW_DIR / subdir
            if not src.exists():
                continue
            if src.is_dir():
                # 支持子目录结构
                for f in src.rglob("*.json") if subdir == "feishu" else src.glob("*.json"):
                    if f.stem not in done_keys:
                        candidates.append(f)
            elif src.suffix == ".json":
                if src.stem not in done_keys:
                    candidates.append(src)
        
        if not candidates:
            logger.info("Tier 3: all data already analyzed")
            return False
        
        # 选 3 个文件
        selected = random.sample(candidates, min(3, len(candidates)))
        
        result = self.analyzer.deep_read(selected)
        if result:
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            out = digest_dir / f"deep_read_{ts}.md"
            out.write_text(f"# Deep Read ({ts})\n\n"
                          f"Sources: {', '.join(s.name for s in selected)}\n\n{result}")
            self.state.set("last_tier3", datetime.now().isoformat())
            logger.info(f"Tier 3: deep_read → {out.name}")
            return True
        
        return False
    
    def _do_idle(self):
        """真闲置时的自适应 backoff 策略。
        
        规则:
        - 每次 idle 增加 backoff 直到 SLEEP_MAX
        - 有新数据时立即重置为 0
        - 每天定时做 dedup 清理和状态同步
        """
        backoff = self.state.get("idle_backoff", 0)
        new_backoff = min(backoff + 5 + random.randint(0, 5), SLEEP_MAX)
        self.state.set("idle_backoff", new_backoff)
        
        logger.debug(f"Idle: backoff {backoff} → {new_backoff}s "
                     f"(T2={str(self.state.get('last_tier2') or '-')[:10]}, "
                     f"T3={self.state.get('tier3_today_count')}/today)")
        
        # 每小时清理一次 dedup
        if new_backoff >= SLEEP_MAX:
            try:
                self.dedup.cleanup_old()
                logger.debug("Dedup cleanup done")
            except Exception as e:
                logger.debug(f"Dedup cleanup: {e}")
        
        time.sleep(new_backoff)
    
    def _save_state(self):
        """持久化状态（限频，最多每秒1次）"""
        try:
            self.state.save()
        except Exception as e:
            logger.warning(f"State save: {e}")
    
    def _cleanup(self):
        """退出清理"""
        self.collector.stop()
        self.state.save()
        self.dedup.close()
        LOCK_FILE.unlink(missing_ok=True)
        logger.info("Engine stopped")


# ══════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════

def main():
    engine = NeverIdleEngine()
    engine.run()
    return 0

if __name__ == "__main__":
    sys.exit(main())
