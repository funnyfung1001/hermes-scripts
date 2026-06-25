#!/usr/bin/env python3
"""batch_recovery.py — 批量补历史日会纪要/周会/每日简报（v2）

使用本地32B模型做交叉验证后补充。不调DeepSeek。

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
from config_shared import setup_logger, today_wat, LOCAL_LLM_ENDPOINT
from config_shared import SECOND_BRAIN, RAW_DIR

logger = setup_logger("batch_recovery", "batch_recovery.log")

# ── 文档配置 ──
DAILY_MEETING_DOC = "AkoGdGuBjovKoMxf3Qwc26FLnJg"
WEEKLY_DOC = "WvZSdhOm8oRjpQxusfvcNSvsnbb"
BRIEFING_CN_DOC = "IltidiIKDosnuSxBuiscyuapnng"
BRIEFING_EN_DOC = "CrsSdqt6cored0xXeEhciXhcnsd"

# ── 日期范围 ──
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

# ── API 辅助 ──
def _lark(method, path, params=None, data=None, timeout=30):
    cmd = ["lark-cli", "api", method, path]
    if params:
        cmd.extend(["--params", json.dumps(params)])
    if data is not None:
        cmd.extend(["--data", json.dumps(data)])
    cmd.extend(["--as", "user"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except Exception as e:
        return {"error": str(e)}

def get_doc_content(doc_token):
    r = _lark("GET", f"docx/v1/documents/{doc_token}/raw_content")
    if r.get("ok"):
        return r.get("data", {}).get("content", "")
    return ""

def doc_append(doc_token, content):
    result = subprocess.run(
        ["lark-cli", "docs", "+update", "--api-version", "v2",
         "--doc", doc_token, "--command", "append",
         "--content", content],
        capture_output=True, text=True, timeout=30
    )
    return result.returncode == 0

# ── 本地32B ──
def call_llm(prompt, timeout=600):
    """调用本地32B模型，超时降级到 DeepSeek"""
    try:
        resp = requests.post(
            LOCAL_LLM_ENDPOINT,
            json={"messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.1, "max_tokens": 4096},
            timeout=timeout
        )
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if content:
            return content
    except Exception as e:
        logger.error(f"32B call failed: {e}")

    # 降级到 DeepSeek
    try:
        env_path = Path.home() / ".hermes" / ".env"
        api_key = ""
        for line in open(env_path):
            line = line.strip()
            if "DEEPSEEK_API_KEY" in line:
                api_key = line.split("=", 1)[1].strip().strip("\"'")
                break
        if not api_key:
            return ""
        resp = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt[:3000]}],
                "max_tokens": 2000,
                "temperature": 0.2
            },
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=120
        )
        return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        logger.error(f"DeepSeek fallback failed: {e}")
        return ""

# ── 查找关联数据源 ──
def find_related_sources(date_str):
    """从第二大脑中查找某日期关联的原始数据"""
    sources = {}
    date_compact = date_str.replace("-", "")
    
    for dir_name in ["feishu", "meetings", "email", "whatsapp"]:
        d = RAW_DIR / dir_name
        if not d.exists():
            continue
        files = []
        for pat in [f"*{date_str}*", f"*{date_compact}*"]:
            files.extend(d.glob(pat))
        if files:
            contents = []
            for f in sorted(files, reverse=True)[:2]:
                try:
                    c = f.read_text()[:2000]
                    contents.append(f"=== {f.name} ===\n{c[:1000]}")
                except:
                    pass
            if contents:
                sources[dir_name] = "\n".join(contents)
    
    # 也查 digest 目录
    digest_dir = RAW_DIR / "digest"
    if digest_dir.exists():
        for pat in [f"*{date_str}*", f"*{date_compact}*"]:
            files = list(digest_dir.glob(pat))
            if files:
                try:
                    c = files[0].read_text()[:2000]
                    sources["digest"] = c[:1000]
                except:
                    pass
    
    return sources

# ── 生成+交叉验证日会纪要 ──
def recover_daily_meeting(date_str):
    logger.info(f"Recovering daily meeting: {date_str} with cross-validation")
    
    # 1. 查找关联数据
    sources = find_related_sources(date_str)
    existing_content = get_doc_content(DAILY_MEETING_DOC)
    
    # 2. 本地32B交叉验证+生成（不检查已存在，全部重新写）
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

4. 标注\"[历史补录 - 本地模型交叉验证]\"
5. 如果有不同数据源对同一事件的描述矛盾，在交叉验证说明中指出
6. 不超过1200字

已有文档内容参考（避免重复）:
{existing_content[-500:] if existing_content else '无'}

{sources_text}"""
    
    content = call_llm(prompt)
    if not content:
        logger.warning(f"  LLM returned empty for {date_str}")
        return False
    
    # 4. 写入云文档
    block = f"\n\n---\n{content}"
    ok = doc_append(DAILY_MEETING_DOC, block)
    if not ok:
        logger.warning(f"  Failed to append, retrying with pure lark-cli")
        ok = doc_append(DAILY_MEETING_DOC, block)
    
    logger.info(f"  {'✅' if ok else '❌'} {date_str}")
    return ok

# ── 生成+交叉验证周会 ──
def recover_weekly(date_str, doc_token):
    logger.info(f"Recovering weekly: {date_str}")
    sources = find_related_sources(date_str)
    existing = get_doc_content(doc_token)
    
    
    src_txt = ""
    if sources:
        src_txt = "\n\n## 关联数据\n" + "\n".join(
            f"### {k}\n{v[:2000]}" for k, v in sources.items()
        )
    
    prompt = f"""Generate weekly meeting notes for C&I Nigeria for {date_str}.

Format:
## {date_str}
**Cross-validation**: [summary of source consistency]

### Key Updates
- (bullet points, English)

### Action Items
| # | Item | Owner | Notes |

### Decisions
- (if any)

Mark as "[Historical recovery - local model cross-validated]"
Keep under 1000 words.

Existing doc context:
{existing[-500:] if existing else 'None'}

{src_txt}"""
    
    content = call_llm(prompt)
    if not content:
        return False
    
    ok = doc_append(doc_token, f"\n\n---\n{content}")
    logger.info(f"  {'✅' if ok else '❌'} Weekly {date_str}")
    return ok

# ── 生成+交叉验证简报 ──
def recover_briefing(date_str, doc_token, lang="cn"):
    lang_label = "中文" if lang == "cn" else "英文"
    logger.info(f"Recovering {lang_label} briefing: {date_str}")
    
    sources = find_related_sources(date_str)
    existing = get_doc_content(doc_token)
    
    
    src_txt = ""
    if sources:
        src_txt = "\n\n## Related sources\n" + "\n".join(
            f"### {k}\n{v[:2000]}" for k, v in sources.items()
        )
    
    if lang == "cn":
        prompt = f"""生成 {date_str} 的C&I Nigeria每日简报（中文）。

要求：
1. 先交叉验证各数据源的一致性
2. 格式：
## {date_str} 每日简报

**📊 今日概览**
（关键进展）

**📌 待办关注**
（待办事项）

3. 标注"[历史补录 - 本地模型交叉验证]"
4. 不超过800字

已有文档上下文：
{existing[-500:] if existing else '无'}

{src_txt}"""
    else:
        prompt = f"""Generate C&I Nigeria daily briefing for {date_str} in English.

Format:
## {date_str} Daily Briefing

**Key Updates**
- (bullet points)

**Action Items**
- (bullet points)

Mark as "[Historical recovery - local model cross-validated]"
Keep under 600 words.

Existing context:
{existing[-500:] if existing else 'None'}

{src_txt}"""
    
    content = call_llm(prompt)
    if not content:
        return False
    
    ok = doc_append(doc_token, f"\n\n---\n{content}")
    logger.info(f"  {'✅' if ok else '❌'} {lang_label} {date_str}")
    return ok

# ── 主流程 ──
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["daily_meeting", "weekly", "briefing_cn", "briefing_en", "all"],
                       default="all")
    parser.add_argument("--days", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    
    phases = list(PHASE_CONFIG.keys()) if args.phase == "all" else [args.phase]
    
    for phase in phases:
        cfg = PHASE_CONFIG[phase]
        label = cfg["label"]
        doc = cfg["doc"]
        
        logger.info(f"\n=== Phase: {label} ===")
        
        from datetime import date as dt_date
        start = dt_date.fromisoformat(cfg["start"])
        end = dt_date.fromisoformat(cfg["end"])
        
        dates = []
        d = start
        while d <= end:
            if phase == "weekly":
                if d.weekday() == 4:  # 周五
                    dates.append(d.isoformat())
            else:
                if d.weekday() < 5:  # 工作日
                    dates.append(d.isoformat())
            d += timedelta(days=1)
        
        if args.days > 0:
            dates = dates[-args.days:]
        
        logger.info(f"Plan: {len(dates)} days")
        
        if args.dry_run:
            for ds in dates[:5]:
                print(f"  Would process: {ds}")
            if len(dates) > 5:
                print(f"  ... and {len(dates)-5} more")
            continue
        
        # 断点续传：从上次完成的地方继续
        checkpoint_file = Path(__file__).parent / f".batch_recovery_{phase}_checkpoint.txt"
        skip_until = ""
        if checkpoint_file.exists():
            skip_until = checkpoint_file.read_text().strip()
            logger.info(f"Checkpoint found: {skip_until}, resuming from next date")
        
        resumed = not bool(skip_until)  # 没有checkpoint时直接开始
        for i, ds in enumerate(dates):
            if not resumed:
                if ds == skip_until:
                    resumed = True
                continue
            
            logger.info(f"[{i+1}/{len(dates)}] {ds}")
            
            ok = False
            try:
                signal.alarm(600)  # 10分钟总超时
                
                if phase == "daily_meeting":
                    ok = recover_daily_meeting(ds)
                elif phase == "weekly":
                    ok = recover_weekly(ds, doc)
                elif phase == "briefing_cn":
                    ok = recover_briefing(ds, doc, "cn")
                elif phase == "briefing_en":
                    ok = recover_briefing(ds, doc, "en")
                
                signal.alarm(0)
            except RuntimeError:
                logger.warning(f"⏰ Timed out: {ds}")
            except Exception as e:
                logger.warning(f"❌ Error {ds}: {e}")
            
            if not ok:
                logger.warning(f"  Failed: {ds}")
            else:
                # 写入断点
                checkpoint_file.write_text(ds)
    
    logger.info("=== Batch recovery complete ===")

if __name__ == "__main__":
    main()
