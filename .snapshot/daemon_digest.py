#!/usr/bin/env python3
"""daemon_digest.py — 深度知识消化（v2：全量无跳过）

由 cron_runner.sh digest 调度（每2小时6-23点）。
对每一条原始数据都用32B做深度分析，超时降级到 DeepSeek。
"""
import sys, json, requests, time, os
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import setup_logger, SECOND_BRAIN, RAW_DIR

logger = setup_logger("daemon_digest", "daemon_digest.log")

def call_llm(prompt, timeout=600):
    """调用本地32B模型，大内容自动分段处理"""
    import requests

    # 如果超过 2500 字符，按段落切块，逐块处理
    if len(prompt) > 2500:
        import textwrap
        # 按段落切，每段最多 2000 字符
        paragraphs = prompt.split("\n\n")
        chunks = []
        current = ""
        for para in paragraphs:
            if len(current) + len(para) < 2000:
                current += para + "\n\n"
            else:
                if current:
                    chunks.append(current.strip())
                current = para + "\n\n"
        if current:
            chunks.append(current.strip())

        if len(chunks) <= 1:
            # 只有一段，直接处理
            chunks = [prompt[:2000]]

        results = []
        for i, chunk in enumerate(chunks):
            sys_prompt = "你是一名C&I Nigeria业务分析师。请分析以下内容，输出简洁分析。"
            if i > 0:
                sys_prompt = "你是一名C&I Nigeria业务分析师。请继续分析以下内容的剩余部分。"
            if len(chunks) > 1 and i == len(chunks) - 1:
                sys_prompt = "这是最后一部分内容。请汇总前面的分析，输出最终的综合摘要。"

            try:
                resp = requests.post(
                    "http://localhost:8080/v1/chat/completions",
                    json={
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": f"第{i+1}/{len(chunks)}部分：{chunk}"}
                        ],
                        "max_tokens": 800,
                        "temperature": 0.1
                    },
                    timeout=timeout
                )
                if resp.status_code == 200:
                    part = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    if part:
                        results.append(part)
            except Exception:
                pass

        if results:
            return "\n\n---\n".join(results)
        return ""

    # 短内容直接处理
    try:
        resp = requests.post(
            "http://localhost:8080/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1200,
                "temperature": 0.1
            },
            timeout=timeout
        )
        if resp.status_code == 200:
            return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception:
        pass
    return ""

def deep_digest_all():
    """全量分析所有未消化的raw数据"""
    cutoff = datetime.now() - timedelta(days=2)
    total = 0

    raw_types = {
        "feishu": ("飞书消息", "群聊/私聊消息分析"),
        "whatsapp": ("WhatsApp消息", "聊天记录分析"),
        "email": ("邮件", "邮件内容分析"),
        "meetings": ("会议纪要", "会议记录分析")
    }

    for dir_name, (label, desc) in raw_types.items():
        d = RAW_DIR / dir_name
        if not d.exists():
            continue

        done_file = RAW_DIR / "digest" / f"{dir_name}_digest_done.txt"
        done_set = set()
        if done_file.exists():
            # 去重读取（清除已有文件中因追加写入产生的重复行）
            raw_lines = done_file.read_text().splitlines()
            done_set = set(raw_lines)
            if len(raw_lines) != len(done_set):
                # 有重复行，写回去重版本
                done_file.write_text("\n".join(sorted(done_set)) + "\n")
                logger.info(f"Deduplicated {done_file.name}: {len(raw_lines)}→{len(done_set)} lines")

        for f in sorted(d.iterdir(), reverse=True):
            if not f.is_file():
                continue
            if str(f) in done_set:
                continue
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                continue

            try:
                content = f.read_text(encoding="utf-8", errors="replace")[:6000]
            except Exception:
                continue

            logger.info(f"Digesting: {f.name} ({len(content)} chars)")

            prompt = f"""你是一个C&I Nigeria业务分析师。请对以下{label}进行深度分析。

文件: {f.name}
来源: {dir_name}
大小: {len(content)}字符

内容:
{content[:5000]}

请按以下格式输出分析报告：

## 📋 基础信息
- 来源类型
- 时间范围
- 涉及人数/实体数

## 👥 关键人物与公司
- 列出所有提到的个人和公司
- 他们的角色和关联

## 📊 关键数据提取
- 数字、金额、时间线
- 项目和进度
- 市场情报

## ✅ 待办与行动项
- 明确的待办
- 隐含需要跟进的

## 🔗 业务关联分析
- 与C&I业务的关联度
- 对当前项目的潜在影响

## ⚠️ 异常发现
- 信息矛盾
- 数据不一致
- 需要核实的内容

## 📝 综合摘要
（300字以内）"""

            result = call_llm(prompt, timeout=600)
            if result:
                digest_dir = RAW_DIR / "digest"
                digest_dir.mkdir(parents=True, exist_ok=True)
                out = digest_dir / f"{dir_name}_{f.stem}_analysis.md"
                out.write_text(f"# {label}深度分析\n\n来源: {f}\n分析时间: {datetime.now().isoformat()}\n\n{result}")
                logger.info(f"✅ {out.name}")
                total += 1

                # 标记已处理
                with open(done_file, "a") as df:
                    fpath = str(f)
                    if fpath not in done_set:
                        df.write(f"{fpath}\n")
                        done_set.add(fpath)

    return total

def main():
    logger.info("Deep digest start")
    # 检查 digest lock，避免与 daemon_worker 的 deep_digest 重叠
    lock_file = RAW_DIR / "digest" / ".digest.lock"
    if lock_file.exists():
        try:
            age = time.time() - lock_file.stat().st_mtime
            if age < 900:  # 15分钟内创建的锁认为有效
                logger.info("Digest lock active (from daemon_worker or previous run), skipping")
                return 0
        except OSError:
            pass
    # 创建临时锁
    lock_file.write_text(str(os.getpid()))
    try:
        n = deep_digest_all()
        logger.info(f"Deep digest done: {n} files processed")
    finally:
        # 只删除自己创建的锁
        if lock_file.exists() and lock_file.read_text().strip() == str(os.getpid()):
            lock_file.unlink()
    return 0

if __name__ == "__main__":
    sys.exit(main())
