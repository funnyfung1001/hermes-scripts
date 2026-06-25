#!/usr/bin/env python3
"""batch_recovery.py — 批量补历史日会纪要/周会/每日简报（v2）

使用本地32B模型做交叉验证后补充，超时降级到 DeepSeek。

流程：
1. 从云文档读取已有内容
2. 从第二大脑raw/中查找关联数据源
3. 本地32B做交叉验证：对比多源一致性、修正日期、补充缺失
4. 生成结构化内容写入云文档

用法：
  python3 batch_recovery.py --phase daily_meeting   # 补日会
  python3 batch_recovery.py --phase weekly           # 补周会
  python3 batch_recovery.py --phase briefing_cn      # 补日报中文
  python3 batch_recovery.py --phase briefing_en      # 补日报英文
  python3 batch_recovery.py --phase all              # 全部
"""
import sys, json, datetime, time, os, subprocess, requests, signal
from pathlib import Path
from datetime import timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import setup_logger, today_wat, RAW_DIR

logger = setup_logger("batch_recovery", "batch_recovery.log")

# -- 文档配置 --
DAILY_MEETING_DOC = "AkoGdGuBjovKoMxf3Qwc26FLnJg"
WEEKLY_DOC = "EYdqdDtfxoSvKGxcmfhcI2zdn2f"
BRIEFING_CN_DOC = "IltidiIKDosnuSxBuiscyuapnng"
BRIEFING_EN_DOC = "CrsSdqt6cored0xXeEhciXhcnsd"

# -- 日期范围 --
PHASE_CONFIG = {
    "daily_meeting": {
        "doc": DAILY_MEETING_DOC,
        "start": "2026-05-16",
        "end": "2026-06-23",
        "label": "日会纪要"
    },
    "weekly": {
        "doc": WEEKLY_DOC,
        "start": "2026-05-22",
        "end": "2026-06-19",
        "label": "周会"
    },
    "briefing_cn": {
        "doc": BRIEFING_CN_DOC,
        "start": "2026-05-16",
        "end": "2026-06-23",
        "label": "日报中文版"
    },
    "briefing_en": {
        "doc": BRIEFING_EN_DOC,
        "start": "2026-05-16",
        "end": "2026-06-23",
        "label": "日报英文版"
    }
}

# -- API 辅助 --
def _lark(method, path, params=None, data=None, timeout=30):
    lark_cli = str(Path.home() / ".npm-global/bin/lark-cli")
    cmd = [lark_cli, "api", method, path]
    if params:
        cmd.extend(["--params", json.dumps(params)])
    if data is not None:
        cmd.extend(["--data", json.dumps(data)])
    cmd.extend(["--as", "user"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            return {"error": r.stderr.strip()[:200]}
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except Exception as e:
        return {"error": str(e)}

def get_doc_content(doc_token):
    """读取云文档已有内容"""
    result = _lark("GET", f"docx/v1/documents/{doc_token}/raw_content")
    if isinstance(result, dict) and result.get("ok"):
        return result.get("data", {}).get("content", "")
    return ""

def doc_append(doc_token, content):
    """追加内容到云文档"""
    lark_cli = str(Path.home() / ".npm-global/bin/lark-cli")
    try:
        r = subprocess.run(
            [lark_cli, "docs", "+update", "--api-version", "v2",
             "--doc", doc_token, "--command", "append",
             "--content", content, "--as", "user"],
            capture_output=True, text=True, timeout=30
        )
        return r.returncode == 0
    except Exception:
        return False

# -- 本地32B + DeepSeek 降级 --
def call_llm(prompt, timeout=600):
    """调用本地32B模型，超时降级到 DeepSeek"""
    # 先试本地32B
    try:
        resp = requests.post(
            "http://localhost:8080/v1/chat/completions",
            json={"messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.1, "max_tokens": 4096},
            timeout=timeout
        )
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if content:
            return content
    except Exception as e:
        logger.debug(f"32B call failed: {e}")

    # 降级到 DeepSeek
    try:
        # 从环境变量或 .env 读取 key
        ds_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not ds_key:
            env_path = Path.home() / ".hermes" / ".env"
            if env_path.exists():
                for line in open(env_path):
                    if "DEEPSEEK_API_KEY" in line:
                        raw_val = line.split("=", 1)[1].strip()
                        ds_key = raw_val.strip("'").strip('"')
                        break
        if not ds_key:
            return ""
        resp = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt[:3000]}],
                "max_tokens": 2000,
                "temperature": 0.2
            },
            headers={"Authorization": f"Bearer {ds_key}"},
            timeout=60
        )
        return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        logger.error(f"DeepSeek fallback failed: {e}")
    return ""

# -- 查找关联数据源 --
def find_related_sources(date_str):
    """从第二大脑中查找某日期关联的原始数据"""
    sources = {}
    raw_dirs = ["feishu", "meetings", "email", "whatsapp", "intel"]
    for dir_name in raw_dirs:
        d = RAW_DIR / dir_name
        if not d.exists():
            continue
        for f in sorted(d.glob(f"*{date_str}*"), reverse=True):
            try:
                content = f.read_text(encoding="utf-8", errors="replace")[:3000]
                if content.strip():
                    sources[f.name] = content
            except Exception:
                continue
    return sources

# -- 生成+交叉验证 --
def recover_daily_meeting(date_str):
    logger.info(f"Recovering daily meeting: {date_str} with cross-validation")
    sources = find_related_sources(date_str)
    existing_content = get_doc_content(DAILY_MEETING_DOC)
    sources_text = ""
    if sources:
        sources_text = "\n\n## 关联数据源\n" + "\n".join(
            f"### {k}\n{v[:1500]}" for k, v in sources.items()
        )
    prompt = f"""你是C&I Nigeria业务团队的会议纪要助手。请根据以下信息生成 {date_str} 的日会纪要。

要求：
1. 先交叉验证所有数据源的时间线一致性
2. 用中文输出结构化纪要
3. 严格按以下模板输出（不要调换顺序）：

## {date_str}（周X）
[交叉验证说明：数据源一致/存在矛盾已标注]

### 📋 会议摘要
（2-3句话概括会议主题和主要结论）

### 📊 项目进展
**地区名：**
- 项目名：状态描述

### ✅ 待办事项
| # | 事项 | 负责人 | 截止 |
|---|------|--------|------|

### 🔑 关键决策
- 决策内容

### ⚠️ 问题与风险
- **级别：** 描述

4. 标注"[历史补录 - 本地模型交叉验证]"
5. 如果有不同数据源对同一事件的描述矛盾，在交叉验证说明中指出
6. 不超过1200字

已有文档内容参考（避免重复）:
{existing_content[-500:] if existing_content else '无'}

{sources_text}"""
    content = call_llm(prompt)
    if not content:
        logger.warning(f"  LLM returned empty for {date_str}")
        return False
    block = f"\n\n---\n{content}"
    ok = doc_append(DAILY_MEETING_DOC, block)
    if not ok:
        ok = doc_append(DAILY_MEETING_DOC, block)
    logger.info(f"  {'OK' if ok else 'FAIL'} {date_str}")
    return ok

def recover_weekly(date_str, doc_token):
    logger.info(f"Recovering weekly: {date_str}")
    sources = find_related_sources(date_str)
    existing = get_doc_content(doc_token)
    src_txt = ""
    if sources:
        src_txt = "\n\n## 关联数据\n" + "\n".join(
            f"### {k}\n{v[:2000]}" for k, v in sources.items()
        )
    prompt = f"""你是C&I Nigeria业务团队的会议纪要助手。请根据以下信息生成 {date_str} 的周会纪要。

要求：
1. 用中文输出结构化纪要
2. 严格按以下模板输出：

## NG C&I Weekly Meeting — {date_str}
[历史补录 - 本地模型交叉验证]

### 📋 会议概要

### 📊 项目进展
**地区名：**
- 项目名：状态描述

### 💰 财务与销售

### 📈 市场情报

### ✅ 待办事项
| # | 事项 | 负责人 | 截止 |
|---|------|--------|------|

### 🔑 关键决策

### ⚠️ 问题与风险
- **级别：** 描述

3. 不超过1500字

已有内容参考:
{existing[-500:] if existing else '无'}

{src_txt}"""
    content = call_llm(prompt)
    if not content:
        logger.warning(f"  Empty from LLM for {date_str}")
        return False
    block = f"\n\n---\n{content}"
    ok = doc_append(doc_token, block)
    if not ok:
        ok = doc_append(doc_token, block)
    logger.info(f"  {'OK' if ok else 'FAIL'} {date_str}")
    return ok

def recover_briefing(date_str, phase):
    """补日报中文或英文"""
    config = PHASE_CONFIG[phase]
    label = config["label"]
    doc_token = config["doc"]
    lang = "中文" if "cn" in phase else "英文"
    logger.info(f"Recovering {label}: {date_str}")

    sources = find_related_sources(date_str)
    existing = get_doc_content(doc_token)
    src_txt = ""
    if sources:
        src_txt = "\n\n## 关联数据\n" + "\n".join(
            f"### {k}\n{v[:1500]}" for k, v in sources.items()
        )

    if lang == "中文":
        prompt = f"""你是C&I Nigeria业务团队的简报助手。请生成 {date_str} 的{label}。

要求：
1. 用中文输出
2. 严格按以下模板输出：

## {date_str} 每日简报

### 📋 今日概览
（整体情况介绍，2-3句话）

### 📊 项目进展
- 项目/事项：状态

### 📈 市场动态
- 行业新闻/竞争情报

### 👥 团队与行政
- 团队事项/HR/财务

### ✅ 待办事项
| # | 事项 | 负责人 |
|---|------|--------|

### 📝 综合摘要
（200字以内）

3. 标注"[历史补录]"
4. 不超过1200字

已有内容参考:
{existing[-500:] if existing else '无'}
{src_txt}"""
    else:
        prompt = f"""Generate {label} for {date_str} in English.

Template:

## {date_str} Daily Briefing

### Overview
(2-3 sentences)

### Project Updates
- (bullet points)

### Market Intelligence
- (bullet points)

### Team & Admin
- (bullet points)

### Action Items
| # | Item | Owner |
|---|------|-------|

### Summary
(100 words)

Mark as "[Historical Recovery]".
Max 1200 chars.

Reference:
{existing[-500:] if existing else 'None'}
{src_txt}"""
    content = call_llm(prompt)
    if not content:
        logger.warning(f"  Empty for {date_str}")
        return False
    block = f"\n\n---\n{content}"
    ok = doc_append(doc_token, block)
    if not ok:
        ok = doc_append(doc_token, block)
    logger.info(f"  {'OK' if ok else 'FAIL'} {date_str}")
    return ok

# -- 检查点 --
CHECKPOINT_DIR = Path(__file__).parent

def get_checkpoint(phase):
    fp = CHECKPOINT_DIR / f".batch_recovery_{phase}_checkpoint.txt"
    if fp.exists():
        return fp.read_text().strip()
    return ""

def save_checkpoint(phase, date_str):
    fp = CHECKPOINT_DIR / f".batch_recovery_{phase}_checkpoint.txt"
    fp.write_text(date_str)

# -- 主入口 --
def run_phase(phase):
    config = PHASE_CONFIG[phase]
    label = config["label"]
    doc = config["doc"]
    start_date = config["start"]
    end_date = config["end"]

    logger.info(f"\n=== Phase: {label} ===")
    start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d")
    total = (end_dt - start_dt).days + 1
    logger.info(f"Plan: {total} days")

    checkpoint = get_checkpoint(phase)
    if checkpoint:
        logger.info(f"Checkpoint found: {checkpoint}, resuming from next date")
        resume = True
    else:
        resume = False

    current = start_dt
    done = 0
    while current <= end_dt:
        ds = current.strftime("%Y-%m-%d")
        if resume:
            if ds == checkpoint:
                resume = False
            current += timedelta(days=1)
            continue

        weekday = current.weekday()
        if phase == "weekly" and weekday != 4:  # 周会只补周五
            current += timedelta(days=1)
            continue
        if "briefing" in phase and weekday >= 5:  # 日报跳过周末
            current += timedelta(days=1)
            continue
        if phase == "daily_meeting" and weekday >= 5:
            current += timedelta(days=1)
            continue

        logger.info(f"[{done+1}/{total}] {ds}")
        ok = False
        if phase == "daily_meeting":
            ok = recover_daily_meeting(ds)
        elif phase == "weekly":
            ok = recover_weekly(ds, doc)
        elif "briefing" in phase:
            ok = recover_briefing(ds, phase)

        if ok:
            done += 1
            save_checkpoint(phase, ds)
        else:
            logger.warning(f"  Skipped {ds} (failed)")
        current += timedelta(days=1)

    logger.info(f"Phase {label} done: {done} days recovered")
    return done

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default="all",
                        choices=["daily_meeting", "weekly", "briefing_cn", "briefing_en", "all"])
    args = parser.parse_args()

    phases = ["daily_meeting", "weekly", "briefing_cn", "briefing_en"] if args.phase == "all" else [args.phase]
    total = 0
    for p in phases:
        total += run_phase(p)
    logger.info(f"Batch recovery done: {total} total days")
    return 0

if __name__ == "__main__":
    sys.exit(main())
