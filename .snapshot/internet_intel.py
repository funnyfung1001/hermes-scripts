#!/usr/bin/env python3
"""internet_intel.py — 互联网情报采集（v2：全量无跳过）

由 cron_runner.sh internet-intel 调度（每3小时）。
采集尼日利亚和新市场（加纳/南非）的工商储行业情报，
全部用本地32B模型分析后存入第二大脑。
"""
import sys, json, requests
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import setup_logger, RAW_DIR, LOCAL_LLM_ENDPOINT

logger = setup_logger("internet_intel", "internet_intel.log")

# ── 搜索源配置 ──
SEARCH_QUERIES = [
    # 尼日利亚工商储
    ("Nigeria C&I energy storage", "行业"),
    ("Nigeria solar battery commercial industrial", "行业"),
    ("Nigeria mini-grid ESS battery", "行业"),
    # 尼日利亚电力政策
    ("Nigeria electricity tariff hike 2026", "政策"),
    ("Nigeria NERC DISCO band A tariff", "政策"),
    # 竞争对手动态
    ("Sungrow Huawei BYD Nigeria energy storage", "竞争"),
    ("Enphase SolarEdge Africa off-grid battery", "竞争"),
    # 加纳/南非新市场
    ("Ghana commercial storage solar 2026", "新市场"),
    ("South Africa battery storage C&I 2026", "新市场"),
    # 行业趋势
    ("lithium iron phosphate battery price trend 2026", "趋势"),
    ("Africa energy storage market forecast", "趋势"),
    ("C&I energy storage ROI Africa 2026", "趋势"),
]

def _load_env():
    """加载 .env 文件到环境变量"""
    import os
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

def search_web(query, limit=3):
    """使用 DuckDuckGo 搜索（duckduckgo_search 库，模拟浏览器行为）"""
    try:
        from duckduckgo_search import DDGS as DDGSLib
        with DDGSLib() as ddgs:
            results = list(ddgs.text(query, max_results=limit))
            if results:
                logger.debug(f"DDGS: {len(results)} results")
                return [{"title": r.get("title", ""), "content": r.get("body", ""), "url": r.get("href", "")} for r in results if r.get("title") or r.get("body")]
    except Exception as e:
        logger.debug(f"DDGS failed for '{query}': {e}")

    # Fallback: 精简 query 再试
    try:
        from duckduckgo_search import DDGS as DDGSLib
        short_q = " ".join(query.split()[:5])
        with DDGSLib() as ddgs:
            results = list(ddgs.text(short_q, max_results=limit))
            if results:
                logger.debug(f"DDGS fallback: {len(results)} results")
                return [{"title": r.get("title", ""), "content": r.get("body", ""), "url": r.get("href", "")} for r in results if r.get("title") or r.get("body")]
    except Exception as e:
        logger.debug(f"DDGS fallback failed: {e}")

    logger.debug(f"No results for '{query}'")
    return []

def fetch_page(url, timeout=15):
    """获取网页内容"""
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 200:
            return resp.text[:8000]
    except Exception as e:
        logger.debug(f"Fetch failed {url}: {e}")
    return ""

def analyze_with_llm(content, query, category):
    """用32B分析搜索到的内容（大内容自动分段）"""
    results_text = content[:6000]

    # 如果超过 2500 字符，分段处理
    if len(results_text) > 2500:
        paragraphs = results_text.split("\n")
        chunks = []
        current = ""
        for para in paragraphs:
            if len(current) + len(para) < 1500:
                current += para + "\n"
            else:
                if current:
                    chunks.append(current.strip())
                current = para + "\n"
        if current:
            chunks.append(current.strip())
        if len(chunks) <= 1:
            chunks = [results_text[:1500]]

        all_analyses = []
        for i, chunk in enumerate(chunks):
            prompt = f"""你是C&I Nigeria储能业务的市场情报分析师。

搜索词: {query}
分类: {category}
这是分析的第{i+1}/{len(chunks)}部分搜索结果：

{chunk}

请分析这部分内容的核心信息。"""
            try:
                resp = requests.post(
                    LOCAL_LLM_ENDPOINT,
                    json={"messages": [{"role": "user", "content": prompt}],
                          "temperature": 0.1, "max_tokens": 800},
                    timeout=600
                )
                part = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                if part:
                    all_analyses.append(part)
            except Exception as e:
                logger.error(f"LLM chunk {i} failed: {e}")

        if not all_analyses:
            return ""

        combined = "\n\n".join(all_analyses)

        # 如果分段了，用32B汇总
        if len(chunks) > 1:
            summary_prompt = f"""汇总以下多部分分析结果，输出综合报告：

{combined}

请按以下格式输出：

## 📰 情报摘要
（核心信息，200字以内）

## 🎯 与C&I Nigeria业务的关联度

## 💡 关键洞察
- 市场机会
- 竞争动态
- 政策变化

## ⚠️ 需要关注的风险

## 📊 建议后续动作"""
            try:
                resp = requests.post(
                    LOCAL_LLM_ENDPOINT,
                    json={"messages": [{"role": "user", "content": summary_prompt}],
                          "temperature": 0.1, "max_tokens": 800},
                    timeout=600
                )
                final = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                if final:
                    return final
            except Exception:
                pass
        return combined

    # 短内容直接处理
    prompt = f"""你是C&I Nigeria储能业务的市场情报分析师。请对以下搜索结果进行分析：

搜索词: {query}
分类: {category}

搜索结果:
{results_text}

请输出分析报告：

## 📰 情报摘要
（核心信息，200字以内）

## 🎯 与C&I Nigeria业务的关联度
- 直接相关 / 间接相关 / 仅供参考
- 理由

## 💡 关键洞察
- 市场机会
- 竞争动态
- 政策变化
- 价格/技术趋势

## ⚠️ 需要关注的风险
- 政策风险
- 竞争风险
- 市场风险

## 📊 建议后续动作
- 具体可操作的建议

输出语言：中文"""
    try:
        resp = requests.post(
            LOCAL_LLM_ENDPOINT,
            json={"messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.1, "max_tokens": 4096},
            timeout=600
        )
        return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        logger.error(f"LLM analysis failed: {e}")
        return ""

def main():
    logger.info("=== Internet intel collection start ===")
    _load_env()  # 确保 .env 已加载
    
    intel_dir = RAW_DIR / "intel"
    intel_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    
    all_reports = []
    total_searched = 0
    
    for query, category in SEARCH_QUERIES:
        logger.info(f"Searching: [{category}] {query}")
        
        # 1. 搜索
        results = search_web(query)
        if not results:
            logger.debug(f"  No results for: {query}")
            continue
        
        total_searched += 1
        logger.info(f"  Got {len(results)} results")
        
        # 2. 提取内容
        content_parts = []
        for r in results[:3]:
            title = r.get("title", "")
            snippet = r.get("content", "") or r.get("snippet", "")
            url = r.get("url", "")
            content_parts.append(f"## {title}\n{snippet}\n来源: {url}\n")
        
        combined = "\n".join(content_parts)
        
        # 3. 32B分析
        analysis = analyze_with_llm(combined, query, category)
        if not analysis:
            continue
        
        # 4. 保存
        all_reports.append(f"---\n## [{category}] {query}\n\n{analysis}\n")
        
        # 每条搜索保存单独文件
        out = intel_dir / f"intel_{category}_{ts}.md"
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"\n\n## {query}\n{analysis}\n")
        
        logger.info(f"  ✅ {query}")
    
    # 5. 综合报告
    if all_reports:
        report = f"# 互联网情报采集 — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n" + \
                 f"采集: {total_searched}/{len(SEARCH_QUERIES)} 条搜索有结果\n" + \
                 "".join(all_reports)
        
        summary_path = intel_dir / f"intel_summary_{ts}.md"
        summary_path.write_text(report)
        logger.info(f"Summary: {summary_path.name} ({len(report)} chars)")
    
    logger.info(f"=== Internet intel done: {total_searched} searches processed ===")
    return 0

if __name__ == "__main__":
    sys.exit(main())

