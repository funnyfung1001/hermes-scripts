#!/usr/bin/env python3
"""
WhatsApp 群消息采集器
通过 WhatsApp bridge API 采集群消息，保存到本地存储。
用法: python3 whatsapp_collector.py [群组ID]

环境变量:
  WHATSAPP_BRIDGE  - Bridge 的 base URL（例如 http://172.27.208.1:3001）
  WHATSAPP_API_KEY - API key（Bearer token）
  若不设置则尝试从 Windows 端读取
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error
import ssl
import logging
from datetime import datetime
from pathlib import Path

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("whatsapp_collector")

# ---------- 配置 ----------

# 1. Bridge URL
BRIDGE_URL = os.environ.get("WHATSAPP_BRIDGE", "")

# 2. API Key
API_KEY = os.environ.get("WHATSAPP_API_KEY", "")

# 3. 数据存储路径
STORAGE_DIR = Path(os.path.expanduser("~/hermes-business/第二大脑/raw/whatsapp"))

# 4. 默认群组（可被命令行参数覆盖）
DEFAULT_GROUP_ID = None

# ---------- 工具函数 ----------


def resolve_bridge_url():
    """解析 Bridge URL 优先级：环境变量 > 自动检测"""
    if BRIDGE_URL:
        return BRIDGE_URL.rstrip("/")

    # 自动检测 WSL 网关
    candidates = []
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                if line.startswith("nameserver"):
                    ip = line.strip().split()[1]
                    candidates.append(f"http://{ip}:3001")
    except OSError:
        pass

    # 默认网关
    import subprocess
    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=5
        )
        parts = result.stdout.split()
        if len(parts) >= 3:
            candidates.append(f"http://{parts[2]}:3001")
    except Exception:
        pass

    candidates.append("http://localhost:3001")

    # 尝试连接
    for url in candidates:
        try:
            req = urllib.request.Request(f"{url}/health", method="GET")
            req.timeout = 3
            with urllib.request.urlopen(req, context=ssl._create_unverified_context()) as resp:
                if resp.status == 200:
                    logger.info(f"自动检测到 Bridge: {url}")
                    return url
        except Exception:
            continue

    logger.warning("无法自动检测 Bridge，使用默认值")
    return candidates[0] if candidates else "http://localhost:3001"


def resolve_api_key():
    """解析 API Key：环境变量 > Windows 文件"""
    if API_KEY:
        return API_KEY

    # 尝试从 Windows 端读取
    windows_paths = [
        "/mnt/c/Users/funny/wweb-mcp/.wwebjs_auth/api_key.txt",
        "/mnt/c/Users/Administrator/wweb-mcp/.wwebjs_auth/api_key.txt",
    ]
    for path in windows_paths:
        p = Path(path)
        if p.exists():
            try:
                key = p.read_text().strip()
                if key:
                    logger.info(f"从 {path} 读取 API Key")
                    return key
            except Exception as e:
                logger.warning(f"读取 {path} 失败: {e}")

    logger.warning("未找到 API Key")
    return ""


def fetch_messages(base_url, api_key, group_id, limit=50):
    """从 Bridge API 获取群消息"""
    url = f"{base_url}/api/groups/{group_id}/messages?limit={limit}"
    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, headers=headers, method="GET")
    req.timeout = 30

    try:
        with urllib.request.urlopen(req, context=ssl._create_unverified_context()) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.error(f"HTTP {e.code} 获取消息失败: {body[:200]}")
        return None
    except urllib.error.URLError as e:
        logger.error(f"网络错误: {e.reason}")
        return None
    except Exception as e:
        logger.error(f"获取消息异常: {e}")
        return None


def list_groups(base_url, api_key):
    """列出所有群组"""
    url = f"{base_url}/api/groups"
    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, headers=headers, method="GET")
    req.timeout = 15

    try:
        with urllib.request.urlopen(req, context=ssl._create_unverified_context()) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except Exception as e:
        logger.error(f"列出群组失败: {e}")
        return None


def save_messages(messages, group_id):
    """保存消息到本地文件"""
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y%m%d")
    filename = f"group_{group_id.replace('@g.us', '').replace('@', '_')}_{today}.json"
    filepath = STORAGE_DIR / filename

    # 如果文件已存在，追加去重
    existing = []
    if filepath.exists():
        try:
            existing = json.loads(filepath.read_text())
        except Exception:
            existing = []

    # 按 id 去重
    seen_ids = {m.get("id") for m in existing if m.get("id")}
    new_count = 0
    for msg in messages if isinstance(messages, list) else messages.get("messages", messages.get("data", [])):
        msg_id = msg.get("id")
        if msg_id and msg_id not in seen_ids:
            existing.append(msg)
            seen_ids.add(msg_id)
            new_count += 1

    filepath.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
    logger.info(f"保存 {len(existing)} 条消息到 {filepath} (新增 {new_count})")
    return new_count


def health_check(base_url, api_key):
    """检测 Bridge 健康状态"""
    url = f"{base_url}/health"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, headers=headers, method="GET")
    req.timeout = 10

    try:
        with urllib.request.urlopen(req, context=ssl._create_unverified_context()) as resp:
            body = resp.read().decode("utf-8")
            logger.info(f"Bridge 健康检查通过: {body[:100]}")
            return True
    except urllib.error.HTTPError as e:
        logger.warning(f"Bridge 健康检查返回 {e.code}")
        # 某些 bridge 没有 /health 端点但仍在工作
        return True
    except Exception as e:
        logger.error(f"Bridge 健康检查失败: {e}")
        return False


# ---------- 主流程 ----------


def main():
    # 解析参数
    group_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GROUP_ID

    # 解析配置
    base_url = resolve_bridge_url()
    api_key = resolve_api_key()

    logger.info(f"Bridge URL: {base_url}")
    logger.info(f"API Key: {'已设置' if api_key else '未设置'}")

    # 健康检查
    if not health_check(base_url, api_key):
        logger.error("Bridge 不可用，采集跳过")
        return 1

    # 如果没有指定群组 ID，尝试列出群组
    if not group_id:
        logger.info("未指定群组 ID，尝试列出可用群组...")
        groups = list_groups(base_url, api_key)
        if groups:
            logger.info(f"可用群组: {json.dumps(groups, ensure_ascii=False, indent=2)[:500]}")
            # 如果是列表取第一个
            if isinstance(groups, list) and len(groups) > 0:
                g = groups[0]
                group_id = g.get("id") or g.get("groupId") or g.get("gid")
                if group_id:
                    logger.info(f"使用第一个群组: {group_id}")
        if not group_id:
            logger.error("未找到群组，请手动指定群组 ID")
            return 1

    # 采集消息
    logger.info(f"采集群组 {group_id} 的消息...")
    messages = fetch_messages(base_url, api_key, group_id)

    if messages is None:
        logger.error("采集失败，静默退出")
        return 1

    # 保存
    count = save_messages(messages, group_id)
    logger.info(f"采集完成，共保存 {count} 条新消息")
    return 0


if __name__ == "__main__":
    sys.exit(main())
