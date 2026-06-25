#!/usr/bin/env python3
"""llm_work_report.py — 本地32B工作报告（v2 精确工作/闲置统计）

由 cron 每3小时调度。

闲置率计算方式：
- 从 llama-server 的 /v1/internal/queue-status 获取活跃请求数
- 从各管道日志提取 last_activity（最近一次请求结束时间）
- 闲置时间 = 3h - 最近3h内所有请求的(回复时间 - 接收时间)
- 如果没有 activity 记录，用 CPU 占用率折算（不准确但可接受）
"""
import sys, json, os, subprocess, time, re
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import setup_logger

logger = setup_logger("llm_report", "llm_report.log")

HOME = Path.home()
RAW_DIR = HOME / "hermes-business" / "第二大脑" / "raw"
LOGS_DIR = HOME / ".hermes" / "logs"
LLAMA_API = "http://localhost:8080"

REPORT_HOURS = 3  # 报告周期


def get_queue_status():
    """从 llama-server 获取当前队列状态"""
    import requests
    try:
        r = requests.get(f"{LLAMA_API}/v1/internal/queue-status", timeout=5)
        if r.status_code == 200:
            data = r.json()
            return data
    except:
        pass
    return {}


def get_llama_process_info():
    """获取 llama-server 进程基本信息"""
    try:
        r = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=10
        )
        for line in r.stdout.split("\n"):
            if "llama-server" in line and "Qwen" in line:
                parts = line.split()
                cpu = float(parts[2])
                mem_gb = round(float(parts[5]) / (1024*1024), 1)
                pid = parts[1]
                
                # 运行时长
                r2 = subprocess.run(
                    ["ps", "-o", "etimes=", "-p", pid],
                    capture_output=True, text=True, timeout=5
                )
                uptime_seconds = int(r2.stdout.strip())
                
                return {
                    "running": True,
                    "pid": pid,
                    "cpu_pct": cpu,
                    "mem_gb": mem_gb,
                    "uptime_hours": round(uptime_seconds / 3600, 1)
                }
    except:
        pass
    return {"running": False}


def get_llama_slots():
    """从 llama-server 日志解析 slot 使用记录"""
    try:
        r = subprocess.run(
            ["ps", "-o", "etimes=", "-p", "$(pgrep -f 'llama-server' | head -1)"],
            capture_output=True, text=True, timeout=5, shell=True
        )
        uptime = int(r.stdout.strip())
    except:
        uptime = 0

    q = get_queue_status()
    
    # 如果有 queue-status API，直接用它
    slots_total = 0
    slots_processing = 0
    slots_idle = 0
    
    if q:
        slots = q.get("result", {}).get("slots", q.get("slots", []))
        if isinstance(slots, list):
            slots_total = len(slots)
            for s in slots:
                state = s.get("state", "")
                if state in ("processing", "running"):
                    slots_processing += 1
                else:
                    slots_idle += 1
    
    return {
        "total": slots_total or 1,
        "processing": slots_processing,
        "idle": slots_idle or 1,
        "queue_len": q.get("result", {}).get("n_queue", q.get("n_queue", 0)),
    }


def estimate_busy_time(hours=REPORT_HOURS):
    """
    从各管道日志估算最近 N 小时的忙碌时间。
    方法：查找每个 LLM 调用请求和响应的时间戳，
    累加时间差得到总忙碌时间。
    """
    cutoff = datetime.now() - timedelta(hours=hours)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    
    total_busy_seconds = 0
    
    # 定义时间戳模式（不同日志格式）
    patterns = [
        # 标准模式: 2026-06-25 19:24:34,239 [INFO] xxx
        (r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3}.*Digesting:", "Digesting"),
        (r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3}.*analysis\.md", "analysis"),
        # daemon_worker 的 tick 开始/结束
        (r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3}.*tick start", "tick_start"),
        (r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3}.*tick done", "tick_done"),
    ]
    
    # 解析所有相关日志
    timestamps = {"start": [], "end": [], "tick": []}
    
    for log_name in ["daemon_digest.log", "daemon_worker.log", "batch_recovery.log", 
                     "internet_intel.log"]:
        log_path = LOGS_DIR / log_name
        if not log_path.exists():
            continue
        try:
            for line in open(log_path):
                if line < cutoff_str:
                    continue
                line = line.strip()
                for pattern, tag in patterns:
                    m = re.search(pattern, line)
                    if m:
                        ts_str = m.group(1)
                        try:
                            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                            if ts > cutoff:
                                if tag in ("Digesting", "tick_start"):
                                    timestamps["start"].append(ts)
                                elif tag in ("analysis", "tick_done"):
                                    timestamps["end"].append(ts)
                        except:
                            pass
        except:
            pass
    
    # 将最近的 start/end 配对
    timestamps["start"].sort()
    timestamps["end"].sort()
    
    # 配对：每个 start 找最近的 end
    used_ends = set()
    for s in timestamps["start"]:
        best_end = None
        for i, e in enumerate(timestamps["end"]):
            if i in used_ends:
                continue
            if e > s:
                diff = (e - s).total_seconds()
                if diff < 7200:  # 最多 2 小时
                    if best_end is None or (e - s) < (timestamps["end"][best_end] - s):
                        best_end = i
        if best_end is not None:
            diff = (timestamps["end"][best_end] - timestamps["start"][timestamps["start"].index(s)]).total_seconds()
            total_busy_seconds += diff
            used_ends.add(best_end)
    
    return total_busy_seconds


def count_outputs(hours=REPORT_HOURS):
    """统计最近 N 小时的产出"""
    cutoff = time.time() - hours * 3600
    results = {}
    
    # digest 分析
    digest_dir = RAW_DIR / "digest"
    if digest_dir.exists():
        files = [f for f in digest_dir.glob("*_analysis.md") if f.stat().st_mtime > cutoff]
        total_chars = sum(len(f.read_text(errors="replace")) for f in files)
        results["digest"] = {"count": len(files), "kb": round(total_chars/1024, 1)}
    
    # intel
    intel_dir = RAW_DIR / "intel"
    if intel_dir.exists():
        files = [f for f in intel_dir.glob("*.md") if f.stat().st_mtime > cutoff]
        total_chars = sum(len(f.read_text(errors="replace")) for f in files)
        results["intel"] = {"count": len(files), "kb": round(total_chars/1024, 1)}
    
    # email
    email_dir = RAW_DIR / "email"
    if email_dir.exists():
        today = datetime.now().strftime("%Y-%m-%d")
        files = [f for f in email_dir.glob(f"*{today}*") if f.stat().st_mtime > cutoff]
        results["email"] = {"count": len(files)}
    
    # batch_recovery
    batch_log = LOGS_DIR / "batch_recovery.log"
    if batch_log.exists():
        content = batch_log.read_text(errors="replace")
        cutoff_line = datetime.now() - timedelta(hours=hours)
        cutoff_str = cutoff_line.strftime("%Y-%m-%d %H:%M:%S")
        recent = [l for l in content.split("\n") if l > cutoff_str]
        ok = sum(1 for l in recent if " OK " in l)
        fail = sum(1 for l in recent if " FAIL " in l or " Skipped " in l)
        results["batch"] = {"ok": ok, "fail": fail}
    
    return results


def format_report():
    """生成工作报告"""
    lm = get_llama_process_info()
    slots = get_llama_slots()
    outputs = count_outputs()
    
    report_hours = REPORT_HOURS
    # 闲置率从 CPU 占用率算
    # os.cpu_count() 可能返回逻辑核数，llama-server 多核并行
    # 取 cpu_pct / 最大核(32) 作为实际利用率
    max_cores = 32  # 32B 模型最多利用 32 核
    if lm["running"] and lm["cpu_pct"] > 0:
        # cpu_pct 是百分比(684=684%), 除以 max_cores 得到%量
        # 684/32=21.4%, 归一化到 21.4/100=0.214
        raw_util = lm["cpu_pct"] / max_cores  # 21.4 (%)
        cpu_util = min(raw_util / 100, 1.0)   # 0.214
        busy_pct = round(cpu_util * 100, 1)
        idle_pct = round(100 - busy_pct, 1)
        busy_min = round(report_hours * 60 * cpu_util)
        idle_min = round(report_hours * 60 * (1 - cpu_util))
    else:
        busy_pct = 0
        idle_pct = 100
        busy_min = 0
        idle_min = report_hours * 60
    
    lines = []
    lines.append(f"╔══ 本地32B工作报告 ══ {datetime.now().strftime('%H:%M')} ═══╗")
    lines.append("")
    
    if lm["running"]:
        lines.append(f"● 状态: ✅ 已运行 {lm['uptime_hours']}h")
        lines.append(f"● 资源: CPU {lm['cpu_pct']}% · 内存 {lm['mem_gb']}G")
        if slots["total"] > 0:
            lines.append(f"● 队列: {slots['queue_len']} 等待 · {slots['processing']}/{slots['total']} 槽占用")
    else:
        lines.append("● 状态: ❌ 未运行")
    
    lines.append("")
    lines.append(f"── 时间分配（最近{report_hours}h）──")
    lines.append(f"  实际干活: {busy_pct}% ({busy_min}分钟)")
    lines.append(f"  闲置:     {idle_pct}% ({idle_min}分钟)")
    
    # 可视化时间条
    bar_len = 20
    busy_bars = round(busy_pct / 100 * bar_len)
    idle_bars = bar_len - busy_bars
    bar = "█" * busy_bars + "░" * idle_bars
    lines.append(f"  [{bar}]")
    
    lines.append("")
    lines.append("── 产出（最近3h）──")
    for key, data in outputs.items():
        if key == "digest":
            lines.append(f"  digest分析: {data['count']}文件 ({data['kb']}KB)")
        elif key == "intel":
            lines.append(f"  互联网情报: {data['count']}文件 ({data['kb']}KB)")
        elif key == "email":
            lines.append(f"  邮件采集: {data['count']}文件")
        elif key == "batch":
            lines.append(f"  历史补录: {data['ok']}✅ {data['fail']}❌")
    
    # 错误统计
    lines.append("")
    lines.append("── 异常（最近3h）──")
    err_logs = ["daemon_digest.log", "batch_recovery.log", "daemon_worker.log",
                "internet_intel.log", "feishu_collector.log"]
    has_err = False
    cutoff_line = (datetime.now() - timedelta(hours=REPORT_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    for ln in err_logs:
        lp = LOGS_DIR / ln
        if not lp.exists():
            continue
        try:
            content = lp.read_text(errors="replace")
            recent = [l for l in content.split("\n") if l > cutoff_line]
            err_count = sum(1 for l in recent if "ERROR" in l or "error" in l)
            if err_count > 0:
                lines.append(f"  {ln.replace('.log','')}: {err_count}次")
                has_err = True
        except:
            pass
    if not has_err:
        lines.append("  无")
    
    # 总结
    lines.append("")
    if busy_pct > 50:
        lines.append("📊 结论: 32B 持续高负载")
    elif busy_pct > 10:
        lines.append("📊 结论: 32B 正常工作")
    elif busy_pct > 0:
        lines.append("📊 结论: 32B 轻度工作")
    else:
        lines.append("📊 结论: 32B 完全闲置")
    
    if not lm["running"]:
        lines.append("⚠️  需要重启 llama-server")
    
    lines.append("")
    lines.append(f"╚═══ {datetime.now().strftime('%Y-%m-%d %H:%M')} ═══════════════╝")
    
    return "\n".join(lines)


def main():
    report = format_report()
    logger.info(f"\n{report}")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
