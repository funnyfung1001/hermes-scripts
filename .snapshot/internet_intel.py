#!/usr/bin/env python3
"""internet_intel.py — 互联网情报采集（v2：全量无跳过）

由 cron_runner.sh internet-intel 调度（每3小时）。
采集尼日利亚和新市场（加纳/南非）的工商储行业情报，
全部用本地32B模型分析后存入第二大脑。
"""
import sys, json, requests, warnings
warnings.filterwarnings("ignore", message=".*renamed to `ddgs`")
from pathlib import Path
from urllib.parse import urlparse
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

# ── 可信来源列表（高权重） ──
TRUSTED_DOMAINS = [
    "reuters.com", "bloomberg.com", "ft.com", "bbc.com", "bbc.co.uk",
    "cnbc.com", "wsj.com", "economist.com", "theguardian.com",
    "techpoint.africa", "nairametrics.com", "businessday.ng",
    "punchng.com", "guardian.ng", "thisdaylive.com", "vanguardngr.com",
    "premiumtimesng.com", "dailytrust.com", "thecable.ng",
    "solarquarter.com", "pv-magazine.com", "energy-storage.news",
    "esi-africa.com", "africa-energy.com", "renewableenergyworld.com",
    "cleantechnica.com", "electrive.com", "greentechmedia.com",
    "iea.org", "irena.org", "worldbank.org", "afdb.org"
]

KNOWLEDGE_SOURCES = {
    "reuters.com": "Reuters (国际通讯社，专业能源报道)",
    "bloomberg.com": "Bloomberg (彭博社，金融+能源数据)",
    "ft.com": "Financial Times (金融时报，深度分析)",
    "bbc.com": "BBC News",
    "cnbc.com": "CNBC (财经新闻)",
    "wsj.com": "Wall Street Journal",
    "economist.com": "The Economist (经济学人)",
    "techpoint.africa": "Techpoint Africa (尼日利亚本土科技媒体)",
    "nairametrics.com": "Nairametrics (尼日利亚财经媒体)",
    "businessday.ng": "Business Day NG (尼日利亚商业日报)",
    "punchng.com": "The Punch (尼日利亚主流媒体)",
    "guardian.ng": "The Guardian Nigeria",
    "thisdaylive.com": "This Day (尼日利亚主流媒体)",
    "pv-magazine.com": "PV Magazine (光伏行业权威)",
    "energy-storage.news": "Energy Storage News (储能行业权威)",
    "esi-africa.com": "ESI Africa (非洲能源行业)",
    "iea.org": "IEA (国际能源署，权威数据)",
    "irena.org": "IRENA (国际可再生能源署)",
    "worldbank.org": "World Bank (世界银行)",
    "solarquarter.com": "Solar Quarter (太阳能行业)",
}


def score_result(result):
    """对搜索结果进行可信度和时效性评分"""
    import re
    from datetime import datetime

    title = result.get("title", "")
    content = result.get("content", "")
    url = result.get("url", "")
    score = 0
    reasons = []

    # 1. 来源域名权重
    domain = ""
    try:
        domain = urlparse(url).netloc.replace("www.", "")
    except:
        pass

    if domain in TRUSTED_DOMAINS:
        score += 40
        src_name = KNOWLEDGE_SOURCES.get(domain, domain)
        reasons.append(f"高权重来源: {src_name}")
    elif domain:
        score += 20
        reasons.append(f"来源: {domain}")

    # 2. 时效性 — 从内容中找日期
    date_patterns = [
        r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})",
        r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})",
    ]
    found_date = None
    for pat in date_patterns:
        m = re.search(pat, content)
        if m:
            found_date = m.group(0)
            break

    if found_date:
        score += 20
        reasons.append(f"有日期: {found_date}")
    else:
        score -= 10
        reasons.append("无明确日期(可能旧消息)")

    # 3. 内容质量 — 有实际数字/金额的加分
    has_numbers = bool(re.search(r"\d+[,.]?\d*\s*(MW|MWh|kW|kWh|\$|₦|million|billion)", content))
    if has_numbers:
        score += 20
        reasons.append("有具体数字/金额")
    else:
        score -= 5
        reasons.append("无具体数字(可能泛泛而谈)")

    # 4. 正文长度
    if len(content) > 200:
        score += 10
    elif len(content) < 50:
        score -= 10
        reasons.append("内容过短")

    return {"score": score, "reasons": reasons, "domain": domain, "found_date": found_date}


def search_web(query, limit=3):
    """使用 Tavily 搜索（优先），Fallback 到 DuckDuckGo"""
    import os, sys, traceback
    import requests
    # 优先 Tavily
    try:
        # 直接从 .env 读 key（确保即使 _load_env 还没调用也能读到）
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            env_path = Path.home() / ".hermes" / ".env"
            for line in open(env_path):
                line = line.strip()
                if "TAVILY_API_KEY" in line:
                    raw = line.split("=", 1)[1].strip()
                    api_key = raw.strip("'").strip('"')
                    os.environ["TAVILY_API_KEY"] = api_key
                    break
        if api_key:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": api_key, "query": query, "search_depth": "basic", "max_results": limit},
                timeout=30
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    scored = []
                    for r in results:
                        # 裁剪 content：只保留前 500 字符，去除重复模板文字
                        raw = r.get("content", "")
                        # 去掉常见的导航/页脚文字
                        import re
                        clean = re.sub(r'(Register|Login|Sign up|Subscribe|Menu|Navigation|Cookie|Privacy|Terms).*', '', raw[:2000], flags=re.IGNORECASE)[:800]
                        item = {"title": r.get("title", ""), "content": clean, "url": r.get("url", "")}
                        s = score_result(item)
                        item["score"] = s["score"]
                        item["score_reasons"] = s["reasons"]
                        item["domain"] = s["domain"]
                        item["found_date"] = s["found_date"]
                        scored.append(item)
                    scored.sort(key=lambda x: x["score"], reverse=True)
                    logger.debug(f"Tavily: {len(results)} results")
                    return scored[:limit]
    except Exception as e:
        import traceback
        print(f"[debug] Tavily exception: {e}\n{traceback.format_exc()}", file=sys.stderr)
        logger.debug(f"Tavily failed: {e}")

    # Fallback: DuckDuckGo
    try:
        from duckduckgo_search import DDGS as DDGSLib
        with DDGSLib() as ddgs:
            results = list(ddgs.text(query, max_results=limit * 2))  # 多取些用于筛选
            if results:
                scored = []
                for r in results:
                    item = {"title": r.get("title", ""), "content": r.get("body", ""), "url": r.get("href", "")}
                    s = score_result(item)
                    item["score"] = s["score"]
                    item["score_reasons"] = s["reasons"]
                    item["domain"] = s["domain"]
                    item["found_date"] = s["found_date"]
                    scored.append(item)
                # 按分数倒序，但保留所有结果（带评分标注让 LLM 判断）
                scored.sort(key=lambda x: x["score"], reverse=True)
                logger.debug(f"DDGS: {len(results)} raw, {len(scored)} after scoring")
                return scored[:limit]
    except Exception as e:
        logger.debug(f"DDGS failed for '{query}': {e}")

    # Fallback: 精简 query
    try:
        from duckduckgo_search import DDGS as DDGSLib
        short_q = " ".join(query.split()[:5])
        with DDGSLib() as ddgs:
            results = list(ddgs.text(short_q, max_results=limit * 2))
            if results:
                scored = []
                for r in results:
                    item = {"title": r.get("title", ""), "content": r.get("body", ""), "url": r.get("href", "")}
                    s = score_result(item)
                    item["score"] = s["score"]
                    item["score_reasons"] = s["reasons"]
                    item["domain"] = s["domain"]
                    scored.append(item)
                scored.sort(key=lambda x: x["score"], reverse=True)
                if scored:
                    return scored[:limit]
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
    # 如果搜索结果带评分信息，格式化时加入
    results_lines = results_text.split("\n")
    scored_lines = []
    has_scores = any("score" in r or "found_date" in r for r in globals().values()) if False else False

    # 如果超过 1500 字符，分段处理
    if len(results_text) > 1500:
        paragraphs = results_text.split("\n")
        chunks = []
        current = ""
        for para in paragraphs:
            if len(current) + len(para) < 800:
                current += para + "\n"
            else:
                if current:
                    chunks.append(current.strip())
                current = para + "\n"
        if current:
            chunks.append(current.strip())
        if len(chunks) <= 1:
            chunks = [results_text[:800]]

        all_analyses = []
        for i, chunk in enumerate(chunks):
            ctx = "分析以下第一部分搜索结果。" if i == 0 else "继续分析剩余部分。" if i < len(chunks)-1 else "这是最后部分。汇总前面分析，输出综合报告。"
            prompt = f"""你是C&I Nigeria储能业务的市场情报分析师。{ctx}

搜索词: {query}
分类: {category}
第{i+1}/{len(chunks)}部分：

{chunk}"""
            try:
                resp = requests.post(
                    LOCAL_LLM_ENDPOINT,
                    json={"messages": [{"role": "user", "content": prompt}],
                          "temperature": 0.1, "max_tokens": 800},
                    timeout=180
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
                    timeout=180
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

请输出分析报告（注意标注每条信息的**可信度评级**和**时效性**）：

## 📰 情报摘要
（核心信息，200字以内，标注信息来源的可信度）

## 🎯 与C&I Nigeria业务的关联度
- 直接相关 / 间接相关 / 仅供参考
- 理由

## 💡 关键洞察
- 市场机会
- 竞争动态
- 政策变化
- 价格/技术趋势

## 🛡️ 可信度评估
| 信息 | 来源 | 时效 | 可信度 |
|-----|------|------|--------|

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
            timeout=180
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

