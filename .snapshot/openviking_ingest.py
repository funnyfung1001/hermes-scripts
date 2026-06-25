#!/usr/bin/env python3
"""
openviking_ingest.py — 将第二大脑（hermes-business）最新内容写入 OpenViking 向量库

由 daemon_worker.py 在 digest 阶段后调用，或由 cron 定时运行。
只写入 digest 后的新文件（基于文件时间戳）。
"""
import json, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import setup_logger, RAW_DIR

logger = setup_logger("openviking_ingest", "openviking_ingest.log")

OV_API = "http://127.0.0.1:1933/api/v1/search/upsert"
COLLECTION = "context"

# 已处理文件标记（增量）
PROCESSED_FILE = Path.home() / ".hermes" / ".openviking_processed.txt"

def load_processed():
    if PROCESSED_FILE.exists():
        return set(PROCESSED_FILE.read_text().strip().splitlines())
    return set()

def save_processed(ids):
    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROCESSED_FILE.write_text("\n".join(sorted(ids)))

def ingest_new_content():
    processed = load_processed()
    new_count = 0

    # 扫描 raw/digest/ 目录（消化后的产物）
    digest_dir = RAW_DIR / "digest"
    if digest_dir.exists():
        for f in sorted(digest_dir.glob("*")):
            if f.name in processed or not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="replace")[:3000]
                if not content.strip():
                    continue
                doc_id = f"digest:{f.name}"
                payload = {
                    "collection": COLLECTION,
                    "documents": [{
                        "id": doc_id,
                        "uri": str(f),
                        "name": f.name,
                        "type": "digest",
                        "context_type": "knowledge",
                        "abstract": content[:500],
                        "description": content[:2000],
                        "tags": "digest,second-brain",
                        "level": 1
                    }]
                }
                import requests
                r = requests.post(OV_API, json=payload, timeout=30)
                if r.status_code == 200:
                    processed.add(f.name)
                    new_count += 1
                    logger.info(f"Ingested: {f.name}")
                else:
                    logger.warning(f"OV upsert failed for {f.name}: {r.text[:200]}")
            except Exception as e:
                logger.debug(f"OV ingest {f.name}: {e}")

    # 扫描 raw/intel/ 目录（互联网情报）
    intel_dir = RAW_DIR / "intel"
    if intel_dir.exists():
        for f in sorted(intel_dir.glob("*.md")):
            if f.name in processed or not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="replace")[:3000]
                if not content.strip():
                    continue
                doc_id = f"intel:{f.name}"
                payload = {
                    "collection": COLLECTION,
                    "documents": [{
                        "id": doc_id,
                        "uri": str(f),
                        "name": f.name,
                        "type": "intel",
                        "context_type": "intelligence",
                        "abstract": content[:500],
                        "description": content[:2000],
                        "tags": "intel,intelligence,second-brain",
                        "level": 1
                    }]
                }
                import requests
                r = requests.post(OV_API, json=payload, timeout=30)
                if r.status_code == 200:
                    processed.add(f.name)
                    new_count += 1
                    logger.info(f"Ingested: {f.name}")
            except Exception as e:
                logger.debug(f"OV ingest {f.name}: {e}")

    # 扫描 raw/meetings/ 目录（会议纪要）
    meetings_dir = RAW_DIR / "meetings"
    if meetings_dir.exists():
        for f in sorted(meetings_dir.glob("*.md")):
            if f.name in processed or not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="replace")[:3000]
                if not content.strip():
                    continue
                doc_id = f"meeting:{f.name}"
                payload = {
                    "collection": COLLECTION,
                    "documents": [{
                        "id": doc_id,
                        "uri": str(f),
                        "name": f.name,
                        "type": "meeting",
                        "context_type": "knowledge",
                        "abstract": content[:500],
                        "description": content[:2000],
                        "tags": "meeting,standup,second-brain",
                        "level": 1
                    }]
                }
                import requests
                r = requests.post(OV_API, json=payload, timeout=30)
                if r.status_code == 200:
                    processed.add(f.name)
                    new_count += 1
                    logger.info(f"Ingested: {f.name}")
            except Exception as e:
                logger.debug(f"OV ingest {f.name}: {e}")

    save_processed(processed)
    logger.info(f"OV ingest done: {new_count} new documents")
    return new_count

if __name__ == "__main__":
    n = ingest_new_content()
    print(f"Ingested {n} new documents into OpenViking")
