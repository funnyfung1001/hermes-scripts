#!/usr/bin/env python3
"""config_shared.py — 共享配置与常量"""
import os, datetime, json
from pathlib import Path

# ── 时间 ──
_OVERRIDE_NOW = None

def set_now(dt=None):
    global _OVERRIDE_NOW
    _OVERRIDE_NOW = dt

def now():
    if _OVERRIDE_NOW is not None:
        return _OVERRIDE_NOW
    return datetime.datetime.now(datetime.timezone.utc)

def today_str():
    return now().astimezone().strftime("%Y-%m-%d")

def today_wat():
    t = now() + datetime.timedelta(hours=1)
    return t.strftime("%Y-%m-%d")

# ── 路径 ──
HOME = Path.home()
HERMES = HOME / ".hermes"
SCRIPTS = HERMES / "scripts"
SECOND_BRAIN = HOME / "hermes-business" / "第二大脑"
RAW_DIR = SECOND_BRAIN / "raw"
WIKI_DIR = SECOND_BRAIN / "wiki"
DAILY_DIR = SECOND_BRAIN / "daily"
WEEKLY_DIR = SECOND_BRAIN / "weekly"
CRON_OUTPUT = HERMES / "cron" / "output"
LOGS = HERMES / "logs"

# ── API ──
DEEPSEEK_API = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
LOCAL_LLM_ENDPOINT = "http://localhost:8080/v1/chat/completions"
LOCAL_LLM_MODEL = "qwen2.5-32b-instruct-q4_K_M"

# ── Token ──
def get_deepseek_key():
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        # Try reading from .env
        env_file = HOME / ".hermes" / ".env"
        if env_file.exists():
            for line in env_file.read_text().split('\n'):
                if line.startswith("DEEPSEEK_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not key:
        kf = HOME / ".hermes" / ".deepseek_key"
        if kf.exists():
            key = kf.read_text().strip()
    return key

def get_bot_token():
    try:
        fp = HOME / ".hermes" / "feishu_sangou_tenant_token.json"
        data = json.loads(fp.read_text())
        return data.get("tenant_token") or data.get("token")
    except Exception:
        return None

# ── 日志 ──
import logging

def setup_logger(name, log_file=None):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    if log_file:
        LOGS.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(LOGS / log_file), encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger

# ── lark-cli ──
import subprocess, shlex
from pathlib import Path
_LARK_CLI = str(Path.home() / ".npm-global/bin/lark-cli")

def lark_cli_user(method="GET", path="", params=None, data=None, timeout=30):
    """以 user 身份调用 lark-cli API
    
    path: API 路径（如 \"im/v1/chats\"），lark-cli 1.0.57 自动加 /open-apis/ 前缀
    params: dict 或 None
    """
    # 兼容旧版 path 带 open-apis/ 前缀的情况
    path = path.removeprefix("open-apis/").removeprefix("/open-apis/")
    
    cmd = [_LARK_CLI, "api", method, path]
    if params:
        cmd.extend(["--params", shlex.quote(json.dumps(params))])
    if data is not None:
        cmd.extend(["--data", shlex.quote(json.dumps(data))])
    cmd.extend(["--as", "user"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            return {"error": r.stderr.strip()}
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    except Exception as e:
        return {"error": str(e)}
