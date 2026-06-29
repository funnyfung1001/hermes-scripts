#!/usr/bin/env python3
"""
healing_agent.py — 32B 自愈探针 (30分钟循环)
=============================================
不依赖本地 32B，只做三件事：
1. 采集系统健康数据 (PID/日志/内存/产出)
2. 输出结构化 JSON（供 downstream agent 决策）
3. 自动执行已知修复（重启 engine/32B）

用法:
  python3 healing_agent.py                  # 检查+输出JSON
  python3 healing_agent.py --auto-fix       # 检查+自动修复
  python3 healing_agent.py --status-json    # 仅输出JSON（供 cron agent 消费）

与 Hermes cron agent 配合:
  1. cron agent 先执行 `python3 healing_agent.py --status-json`
  2. 将输出注入 agent prompt
  3. Agent 用 DeepSeek（非本地32B）决策修复方案
  4. 执行修复

不限制不卡死: 总超时 60 秒，所有 HTTP 调用 timeout ≤ 15 秒
"""

import json, os, subprocess, sys, time
from pathlib import Path

HOME = Path.home()
HERMES = HOME / ".hermes"
SCRIPTS = HERMES / "scripts"
RAW_DIR = HOME / "hermes-business" / "第二大脑" / "raw"
ENGINE_PID_FILE = HERMES / ".engine.pid"
ENGINE_STATE_FILE = HERMES / ".engine.state.json"
ENGINE_DEDUP_DB = HERMES / ".engine.dedup.db"
ENGINE_LOG = HERMES / "logs" / "engine.log"
LLAMA_LOG = Path("/tmp/llama-server.log")
DIGEST_DIR = RAW_DIR / "digest"

CHECK_TIMEOUT = 5     # 单检查超时（秒）
HTTP_TIMEOUT = 10     # HTTP 请求超时


def check_pid(pid_file: Path) -> dict:
    """检查 PID 文件 + 进程存活"""
    result = {"pid": None, "alive": False, "uptime_sec": None}
    if not pid_file.exists():
        result["error"] = "PID file not found"
        return result
    try:
        pid = int(pid_file.read_text().strip())
        result["pid"] = pid
        # 用 /proc 检查进程存活+uptime
        if (Path(f"/proc/{pid}/status")).exists():
            result["alive"] = True
            try:
                stat = Path(f"/proc/{pid}/stat").read_text().split()
                # jiffies since boot (field 21) / CLK_TCK ≈ uptime_sec
                clk_tck = os.sysconf(os.sysconf_names['SC_CLK_TCK'])
                start_jiffies = int(stat[21])
                with open("/proc/stat") as f:
                    for line in f:
                        if line.startswith("btime "):
                            boot_time = int(line.split()[1])
                            break
                result["uptime_sec"] = int(time.time() - (boot_time + start_jiffies / clk_tck))
            except (IndexError, ValueError, OSError):
                pass
        else:
            result["alive"] = False
            result["error"] = "Process not found"
    except (ValueError, OSError) as e:
        result["error"] = str(e)
    return result


def check_llama_server() -> dict:
    """检查 32B 是否存活且可推理"""
    import urllib.request, urllib.error
    result = {"health": None, "loaded": False, "inference_ok": False}
    
    # health endpoint
    try:
        resp = urllib.request.urlopen("http://localhost:8080/health", timeout=CHECK_TIMEOUT)
        body = resp.read().decode()
        if '"ok"' in body:
            result["health"] = "ok"
            result["loaded"] = True
        elif 'Loading model' in body:
            result["health"] = "loading"
        else:
            result["health"] = "unknown"
    except urllib.error.URLError as e:
        result["health"] = f"error: {e.reason}"
        return result
    except Exception as e:
        result["health"] = f"error: {e}"
        return result
    
    # 真实推理探针 (max_tokens=1, 短超时)
    if result["loaded"]:
        try:
            req = urllib.request.Request(
                "http://localhost:8080/v1/chat/completions",
                data=json.dumps({
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                    "temperature": 0
                }).encode(),
                headers={"Content-Type": "application/json"}
            )
            resp = urllib.request.urlopen(req, timeout=HTTP_TIMEOUT)
            body = json.loads(resp.read().decode())
            if body.get("choices"):
                result["inference_ok"] = True
        except Exception as e:
            result["inference_ok"] = False
            result["inference_error"] = str(e)[:100]
    
    # 内存使用
    try:
        import subprocess
        r = subprocess.run(
            ["ps", "-o", "rss=", "-C", "llama-server"],
            capture_output=True, text=True, timeout=CHECK_TIMEOUT
        )
        if r.stdout.strip():
            rss_kb = sum(int(x) for x in r.stdout.strip().split("\n") if x.strip())
            result["rss_mb"] = round(rss_kb / 1024, 1)
    except Exception:
        pass
    
    return result


def check_engine_log() -> dict:
    """检查引擎日志新鲜度 + 最近活动"""
    result = {"exists": False, "last_line_ago_sec": None, "last_action": None, "error_rate": 0}
    
    if not ENGINE_LOG.exists():
        result["error"] = "Engine log not found"
        return result
    result["exists"] = True
    
    try:
        lines = ENGINE_LOG.read_text(encoding="utf-8", errors="replace").strip().split("\n")
        if not lines:
            return result
        
        # 最近日志行的时间
        for line in reversed(lines):
            import re
            m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            if m:
                from datetime import datetime
                try:
                    last_time = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                    result["last_line_ago_sec"] = int((datetime.now() - last_time).total_seconds())
                except ValueError:
                    pass
                break
        
        # 最近30行提取关键动作
        recent = lines[-30:] if len(lines) >= 30 else lines
        key_actions = [l for l in recent if any(
            kw in l for kw in ["Tier 1", "Tier 2", "Tier 3", "Idle", "Error", "ERROR"]
        )]
        if key_actions:
            result["last_action"] = key_actions[-1][:200]
        
        # 错误率
        total_lines = len(lines)
        error_lines = sum(1 for l in lines if "ERROR" in l.upper() or "Fatal" in l)
        if "32B connection refused" in lines[-1] or "32B returned 50" in lines[-1]:
            result["last_llm_attempt"] = "failed"
        elif "Tier 1" in lines[-1] or "Tier 2" in lines[-1] or "Tier 3" in lines[-1]:
            result["last_llm_attempt"] = "in_progress"
        
        # 连续失败检测
        recent_errors = [l for l in recent if "WARNING" in l and "32B" in l]
        result["recent_32b_errors"] = len(recent_errors)
        
    except Exception as e:
        result["parse_error"] = str(e)[:100]
    
    return result


def check_digest_output() -> dict:
    """检查最近的分析产出"""
    result = {"fresh_output": False, "last_file_ago_sec": None, "today_files": 0}
    
    if not DIGEST_DIR.exists():
        return result
    
    try:
        files = sorted(DIGEST_DIR.glob("*_analysis.md"), key=lambda f: f.stat().st_mtime, reverse=True)
        if files:
            last_mtime = files[0].stat().st_mtime
            result["last_file_ago_sec"] = int(time.time() - last_mtime)
            result["fresh_output"] = result["last_file_ago_sec"] < 7200  # 2h
        else:
            # 也检查 cross_ref 和 deep_read
            for prefix in ["cross_ref_", "deep_read_", "knowledge_link_"]:
                files = sorted(DIGEST_DIR.glob(f"{prefix}*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
                if files:
                    last_mtime = files[0].stat().st_mtime
                    time_ago = int(time.time() - last_mtime)
                    if not result["last_file_ago_sec"] or time_ago < result["last_file_ago_sec"]:
                        result["last_file_ago_sec"] = time_ago
                    result["fresh_output"] = True
                    break
        
        # 今日文件数
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")
        result["today_files"] = len(list(DIGEST_DIR.glob(f"*{today}*.md")))
        
    except Exception as e:
        result["error"] = str(e)[:100]
    
    return result


def check_memory() -> dict:
    """检查系统内存"""
    result = {"total_gb": 0, "used_gb": 0, "free_gb": 0, "model_rss_gb": 0, "critical": False}
    try:
        r = subprocess.run(
            ["free", "-g"], capture_output=True, text=True, timeout=CHECK_TIMEOUT
        )
        for line in r.stdout.split("\n"):
            if line.startswith("Mem:"):
                parts = line.split()
                result["total_gb"] = int(parts[1])
                result["used_gb"] = int(parts[2])
                result["free_gb"] = int(parts[3])
        # 检查模型 RSS
        r2 = subprocess.run(
            ["ps", "-o", "rss=", "-C", "llama-server"],
            capture_output=True, text=True, timeout=CHECK_TIMEOUT
        )
        if r2.stdout.strip():
            rss_kb = sum(int(x) for x in r2.stdout.strip().split("\n") if x.strip())
            result["model_rss_gb"] = round(rss_kb / (1024 * 1024), 1)
            # 32B Q4_K_M 正常 ~19GB，超过 26GB 可能异常膨胀
            if result["model_rss_gb"] > 26:
                result["critical"] = True
                result["warning"] = f"Model RSS {result['model_rss_gb']}GB exceeds 26GB threshold"
    except Exception:
        pass
    return result


def check_gateway() -> dict:
    """检查 Gateway"""
    result = {"alive": False}
    try:
        r = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=CHECK_TIMEOUT
        )
        result["alive"] = "hermes gateway run" in r.stdout
    except Exception:
        pass
    return result


def auto_fix_engine():
    """自动修复 engine（不依赖 32B）"""
    import subprocess
    pid_info = check_pid(ENGINE_PID_FILE)
    
    if not pid_info["alive"]:
        print("[FIX] Engine not running, starting...")
        subprocess.run(
            ["python3", str(SCRIPTS / "engine.py")],
            cwd=str(SCRIPTS),
            timeout=30
        )
        time.sleep(5)
        pid_info = check_pid(ENGINE_PID_FILE)
        if pid_info["alive"]:
            print(f"[FIX] Engine started (PID {pid_info['pid']})")
            return {"fixed": "engine_restarted", "pid": pid_info["pid"]}
        else:
            print("[FIX] FAILED to start engine")
            return {"fixed": False, "error": "engine_start_failed"}
    
    return {"fixed": False, "reason": "engine_already_running"}


def auto_fix_llama():
    """重启 32B（最后手段）"""
    import subprocess, signal
    
    print("[FIX] Restarting llama-server...")
    # Kill all
    subprocess.run(["pkill", "-f", "llama-server"], timeout=10)
    time.sleep(2)
    try:
        subprocess.run(["fuser", "-k", "8080/tcp"], timeout=10, capture_output=True)
    except Exception:
        pass
    time.sleep(3)
    
    # Wait for port release
    for _ in range(15):
        r = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=5)
        if "8080" not in r.stdout:
            break
        time.sleep(1)
    
    # Start
    cmds = [
        "export CUDA_VISIBLE_DEVICES=0",
        f"cd {Path.home()/ 'llama.cpp'}",
        "nohup ./build/bin/llama-server -m models/Qwen2.5-32B-Instruct-Q4_K_M.gguf "
        "--host 0.0.0.0 --port 8080 -ngl 99 -c 8192 --no-mmap --timeout 300 "
        "> /tmp/llama-server.log 2>&1 &"
    ]
    subprocess.run(["bash", "-c", "; ".join(cmds)], timeout=30)
    time.sleep(5)
    
    # Verify
    llama_status = check_llama_server()
    return {"fixed": "llama_restarted", "health": llama_status["health"]}


def collect_all() -> dict:
    """全面健康检查"""
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "engine": check_pid(ENGINE_PID_FILE),
        "llama_server": check_llama_server(),
        "engine_log": check_engine_log(),
        "digest_output": check_digest_output(),
        "memory": check_memory(),
        "gateway": check_gateway(),
    }


def diagnose(status: dict) -> list[str]:
    """基于状态数据给出诊断结论"""
    issues = []
    
    e = status["engine"]
    if not e.get("alive"):
        issues.append("CRITICAL: Engine not running")
    elif e.get("uptime_sec", 0) < 120:
        issues.append("INFO: Engine just started (<2min ago)")
    
    l = status["llama_server"]
    if l.get("health") != "ok":
        issues.append(f"CRITICAL: 32B health={l.get('health')}")
    elif not l.get("inference_ok"):
        issues.append("WARNING: 32B health OK but inference probe failed")
    
    log = status["engine_log"]
    if log.get("last_line_ago_sec", 0) > 1800:  # >30min
        issues.append(f"CRITICAL: Engine silent for {log['last_line_ago_sec']}s")
    if log.get("recent_32b_errors", 0) > 5:
        issues.append(f"WARNING: {log['recent_32b_errors']} recent 32B errors")
    if log.get("last_llm_attempt") == "failed":
        issues.append("WARNING: Last 32B call failed")
    elif log.get("last_llm_attempt") == "in_progress":
        issues.append("INFO: 32B call in progress")
    
    d = status["digest_output"]
    if not d.get("fresh_output"):
        if d.get("last_file_ago_sec"):
            issues.append(f"WARNING: No output for {d['last_file_ago_sec']}s")
        else:
            issues.append("WARNING: No digest output files found at all")
    
    m = status["memory"]
    if m.get("critical"):
        issues.append(f"CRITICAL: Model RSS {m.get('model_rss_gb')}GB too high")
    if m.get("free_gb", 0) < 2:
        issues.append(f"CRITICAL: Only {m['free_gb']}GB free memory")
    
    if not issues:
        issues.append("HEALTHY: Everything nominal")
    
    return issues


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto-fix", action="store_true")
    parser.add_argument("--status-json", action="store_true")
    args = parser.parse_args()
    
    status = collect_all()
    issues = diagnose(status)
    status["diagnosis"] = issues
    
    if args.auto_fix:
        fixes = []
        # 按优先级修复
        for issue in issues:
            if "CRITICAL: Engine not running" in issue:
                fixes.append(auto_fix_engine())
            elif "CRITICAL: 32B health=" in issue or "CRITICAL: Model RSS" in issue:
                fixes.append(auto_fix_llama())
        if fixes:
            status["fixes"] = fixes
            # 修复后重新检查
            time.sleep(10)
            status["post_fix"] = collect_all()
            status["post_fix"]["diagnosis"] = diagnose(status["post_fix"])
    
    if args.status_json:
        # 纯 JSON 模式（供 cron agent 消费）
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return
    
    # 人类可读输出
    print(f"\n{'='*50}")
    print(f"🤖 32B 自愈探针 — {status['timestamp']}")
    print(f"{'='*50}")
    print(f"\n📊 Engine:   {'✅ Alive (PID ' + str(status['engine']['pid']) + ')' if status['engine'].get('alive') else '❌ DEAD'}")
    print(f"   Uptime:   {status['engine'].get('uptime_sec', 'N/A')}s")
    print(f"\n🖥  32B:      {'✅ Healthy' if status['llama_server'].get('inference_ok') else '⚠️ ' + str(status['llama_server'].get('health', 'unknown'))}")
    print(f"   Memory:   {status['llama_server'].get('rss_mb', '?')}MB")
    print(f"\n📝 Engine Log: {'✅ <5min' if status['engine_log'].get('last_line_ago_sec', 9999) < 300 else '⚠️ ' + str(status['engine_log'].get('last_line_ago_sec', '?')) + 's ago'}")
    print(f"   Last action: {status['engine_log'].get('last_action', 'none')[:120]}")
    print(f"\n📁 Digest:   {'✅ Fresh' if status['digest_output'].get('fresh_output') else '⚠️ No recent output'}")
    print(f"   Today:    {status['digest_output'].get('today_files', 0)} files")
    print(f"\n🧠 Memory:   {status['memory'].get('used_gb', '?')}G/{status['memory'].get('total_gb', '?')}G used")
    print(f"   32B RSS:  {status['memory'].get('model_rss_gb', '?')}GB")
    print(f"\n🌐 Gateway:  {'✅ Alive' if status['gateway'].get('alive') else '❌ DEAD'}")
    print(f"\n{'─'*50}")
    print(f"🔍 Diagnosis:")
    for issue in issues:
        icon = "🟢" if "HEALTHY" in issue else ("🔴" if "CRITICAL" in issue else "🟡")
        print(f"   {icon} {issue}")
    
    if args.auto_fix:
        print(f"\n{'─'*50}")
        print(f"🛠️  Auto-fix results:")
        for fix in status.get("fixes", []):
            print(f"   {fix}")
    
    print(f"\n{'='*50}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"error": str(e), "fatal": True}), file=sys.stderr)
        sys.exit(1)
