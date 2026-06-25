#!/usr/bin/env python3
"""
openviking_ingest.py — 将第二大脑（hermes-business）最新内容写入 OpenViking 向量库

由 daemon_worker.py 在 digest 阶段后调用，或由 cron 定时运行。
只写入 digest 后的新文件（基于文件时间戳）。
"""
import json, os, sys, time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import setup_logger, RAW_DIR

logger = setup_logger("openviking_ingest", "openviking_ingest.log")

OV_WRITE_API = "http://127.0.0.1:1933/api/v1/content/write"
COLLECTION_URI_PREFIX = "viking://resources/second_brain/"

# 已处理文件标记（增量）
PROCESSED_FILE = Path.home() / ".hermes" / ".openviking_processed.txt"

def load_processed():
    if PROCESSED_FILE.exists():
        return set(PROCESSED_FILE.read_text().strip().splitlines())
    return set()

def save_processed(ids):
    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROCESSED_FILE.write_text("\n".join(sorted(ids)))

# 速率控制
_OV_LAST_WRITE = 0.0

def write_to_ov(uri, content):
    """通过 OpenViking content/write API 写入，速率控制：最多每5秒1条"""
    import requests, time
    global _OV_LAST_WRITE
    elapsed = time.time() - _OV_LAST_WRITE
    if elapsed < 5:
        time.sleep(5 - elapsed)
    _OV_LAST_WRITE = time.time()

    resp = requests.post(OV_WRITE_API, json={
        "uri": uri,
        "content": content[:5000],
        "mode": "create",
        "wait": False  # 异步，不等待 embedding 完成
    }, timeout=10)
    return resp.status_code == 200

def ingest_new_content():
    processed = load_processed()
    new_count = 0

    # 扫描 raw/digest/ 目录
    digest_dir = RAW_DIR / "digest"
    if digest_dir.exists():
        for f in sorted(digest_dir.glob("*")):
            if f.name in processed or not f.is_file():
                continue
            content = f.read_text(encoding="utf-8", errors="replace")[:5000]
            if not content.strip():
                continue
            uri = f"{COLLECTION_URI_PREFIX}digest/{f.name}"
            if write_to_ov(uri, content):
                processed.add(f.name)
                new_count += 1
                logger.info(f"OV write: {f.name}")
            else:
                logger.warning(f"OV write failed: {f.name}")

    # 扫描 raw/intel/
    intel_dir = RAW_DIR / "intel"
    if intel_dir.exists():
        for f in sorted(intel_dir.glob("*.md")):
            if f.name in processed or not f.is_file():
                continue
            content = f.read_text(encoding="utf-8", errors="replace")[:5000]
            if not content.strip():
                continue
            uri = f"{COLLECTION_URI_PREFIX}intel/{f.name}"
            if write_to_ov(uri, content):
                processed.add(f.name)
                new_count += 1
                logger.info(f"OV write: {f.name}")

    # 扫描 raw/meetings/
    meetings_dir = RAW_DIR / "meetings"
    if meetings_dir.exists():
        for f in sorted(meetings_dir.glob("*.md")):
            if f.name in processed or not f.is_file():
                continue
            content = f.read_text(encoding="utf-8", errors="replace")[:5000]
            if not content.strip():
                continue
            uri = f"{COLLECTION_URI_PREFIX}meetings/{f.name}"
            if write_to_ov(uri, content):
                processed.add(f.name)
                new_count += 1
                logger.info(f"OV write: {f.name}")

    save_processed(processed)
    logger.info(f"OV ingest done: {new_count} new documents")
    return new_count

if __name__ == "__main__":
    n = ingest_new_content()
    print(f"Ingested {n} new documents into OpenViking")
