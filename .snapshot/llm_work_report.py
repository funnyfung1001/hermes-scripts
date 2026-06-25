#!/usr/bin/env python3
"""llm_work_report.py — 本地32B工作报告

由 cron 每3小时调度，统计：
- 32B 进程运行时长、CPU/内存、闲置率
- 各管道产出（digest、batch_recovery、intel）
- 产出文件数和字符数
- 超时/错误统计
- 闲置率 = 最近3小时空闲时间 / 3小时 * 100%
"""
import sys, json, os, subprocess, time
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import setup_logger

logger = setup_logger("llm_report", "llm_report.log")

HOME = Path.home()
RAW_DIR = HOME / "hermes-business" / "第二大脑" / "raw"
SECOND_BRAIN = HOME / "hermes-business" / "第二大脑"
LOGS_DIR = HOME / ".hermes" / "logs"


def get_llama_stats():
    """获取 llama-server 进程统计"""
    try:
        r = subprocess.run(
            ["ps", "aux"],
            capture_output=True, text=True, timeout=10
        )
        for line in r.stdout.split("\n"):
            if "llama-server" in line and "Qwen" in line:
                parts = line.split()
                cpu = float(parts[2])  # CPU%
                mem_mb = float(parts[5]) / 1024  # MEM in MB
                start_time = parts[10] if len(parts) > 10 else "?"
                pid = parts[1]
                
                # 计算运行时长
                uptime_seconds = 0
                try:
                    with open(f"/proc/{pid}/stat") as f:
                        stat_parts = f.read().split()
                        start_jiffies = int(stat_parts[21])
                        with open("/proc/stat") as f2:
                            for line2 in f2:
                                if line2.startswith("btime "):
                                    boot_time = int(line2.split()[1])
                                    break
                        uptime_seconds = time.time() - (boot_time + start_jiffies / 100)
                except:
                    pass
                
                # 计算闲置率（CPU空闲百分比 ≈ 100% - 单核百分比）
                # 假设 32 核，利用率 = cpu / 32
                cpu_util_pct = cpu / os.cpu_count()
                idle_pct = max(0, 100 - cpu_util_pct * 100)
                
                return {
                    "running": True,
                    "pid": pid,
                    "cpu_pct": cpu,
                    "mem_gb": round(mem_mb / 1024, 1),
                    "uptime_hours": round(uptime_seconds / 3600, 1),
                    "uptime_seconds": uptime_seconds,
                    "idle_pct": round(idle_pct, 1),
                    "cpu_util_pct": round(cpu_util_pct * 100, 1)
                }
    except Exception as e:
        logger.error(f"get_llama_stats: {e}")
    
    return {"running": False, "uptime_hours": 0, "idle_pct": 100}


def count_recent_outputs(hours=3):
    """统计最近 N 小时的产出文件"""
    cutoff = time.time() - hours * 3600
    results = {}
    
    # digest 分析文件
    digest_dir = RAW_DIR / "digest"
    if digest_dir.exists():
        files = [f for f in digest_dir.glob("*_analysis.md") 
                 if f.stat().st_mtime > cutoff]
        total_chars = sum(len(f.read_text(errors="replace")) for f in files)
        results["digest"] = {
            "count": len(files),
            "chars": total_chars,
            "files": [f.name for f in files[:5]]
        }
    
    # intel 数据
    intel_dir = RAW_DIR / "intel"
    if intel_dir.exists():
        files = [f for f in intel_dir.glob("intel_*.md") 
                 if f.stat().st_mtime > cutoff]
        total_chars = sum(len(f.read_text(errors="replace")) for f in files)
        results["intel"] = {
            "count": len(files),
            "chars": total_chars,
            "files": [f.name for f in files[:5]]
        }
    
    # email 采集数
    email_dir = RAW_DIR / "email"
    if email_dir.exists():
        files = [f for f in email_dir.glob("*2026-06-25*") 
                 if f.stat().st_mtime > cutoff]
        results["email"] = {
            "count": len(files),
            "files": [f.name for f in files[:3]]
        }
    
    # batch_recovery 日志
    batch_log = LOGS_DIR / "batch_recovery.log"
    if batch_log.exists():
        content = batch_log.read_text(errors="replace")
        recent_lines = [l for l in content.split("\n") if " OK " in l or " FAIL " in l]
        recent_ok = sum(1 for l in recent_lines if " OK " in l)
        recent_fail = sum(1 for l in recent_lines if " FAIL " in l)
        results["batch_recovery"] = {
            "ok": recent_ok,
            "fail": recent_fail,
            "total": recent_ok + recent_fail
        }
    
    # daemon_worker ticks
    worker_log = LOGS_DIR / "daemon_worker.log"
    if worker_log.exists():
        content = worker_log.read_text(errors="replace")
        ticks = [l for l in content.split("\n") if "tick done" in l.lower()]
        results["daemon_ticks"] = {"count": len(ticks)}
    
    return results


def count_errors(hours=3):
    """统计最近3小时的错误数"""
    cutoff_ts = datetime.now() - timedelta(hours=hours)
    cutoff_str = cutoff_ts.strftime("%Y-%m-%d %H:%M:%S")
    errors = {}
    
    for log_name in ["daemon_digest.log", "batch_recovery.log", "daemon_worker.log", 
                     "internet_intel.log", "feishu_collector.log"]:
        log_path = LOGS_DIR / log_name
        if not log_path.exists():
            continue
        try:
            content = log_path.read_text(errors="replace")
            # 只取最近3小时的错误
            recent = ""
            for line in content.split("\n"):
                if line > cutoff_str:
                    recent += line + "\n"
            err_count = recent.count("ERROR") + recent.count("failed") + recent.count("Failed")
            if err_count > 0:
                errors[log_name.replace(".log", "")] = err_count
        except:
            pass
    
    return errors


def format_report():
    """生成结构化工作报告"""
    llm = get_llama_stats()
    outputs = count_recent_outputs(hours=3)
    errors = count_errors(hours=3)
    
    report = []
    report.append(f"╔══ 🤖 本地32B工作报告 ══ {datetime.now().strftime('%H:%M')} ═══╗")
    report.append("")
    
    # 基础状态
    if llm["running"]:
        report.append(f"● 运行: ✅ {llm['uptime_hours']}h | PID {llm['pid']}")
        report.append(f"● 资源: CPU {llm['cpu_pct']}% / {llm['cpu_util_pct']}% 已用")
        report.append(f"        内存 {llm['mem_gb']}G")
        report.append(f"● 闲置: {llm['idle_pct']}%")
    else:
        report.append("● 状态: ❌ 未运行")
    
    report.append("")
    report.append("── 产出（最近3h）──")
    
    for key, data in outputs.items():
        if key == "digest":
            report.append(f"  digest分析: {data['count']}文件 {data['chars']//1024}KB")
        elif key == "intel":
            report.append(f"  互联网情报: {data['count']}文件 {data['chars']//1024}KB")
        elif key == "email":
            report.append(f"  邮件采集: {data['count']}文件")
        elif key == "batch_recovery":
            ok = data.get("ok", 0)
            fail = data.get("fail", 0)
            report.append(f"  历史补录: {ok}✅ / {fail}❌")
        elif key == "daemon_ticks":
            report.append(f"  守护进程: {data['count']}次")
    
    if errors:
        report.append("")
        report.append("── 异常（最近3h）──")
        for name, count in sorted(errors.items()):
            report.append(f"  {name}: {count}次错误")
    else:
        report.append("")
        report.append("── 异常 ──")
        report.append("  无")
    
    report.append("")
    report.append(f"╚═══ {datetime.now().strftime('%Y-%m-%d %H:%M')} ═══════════════════╝")
    
    return "\n".join(report)


def main():
    report = format_report()
    logger.info(f"\n{report}")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
