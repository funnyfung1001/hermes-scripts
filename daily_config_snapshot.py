#!/usr/bin/env python3
"""每天凌晨对关键配置做 git 快照并推送到 GitHub"""
import subprocess, os, json, re
from pathlib import Path
from datetime import datetime

HOME = Path.home()
HERMES = HOME / ".hermes"
BACKUP_REPO = HERMES / "scripts-backup"

# 要备份的关键文件（纯文本，不含 secrets）
SAFE_FILES = [
    ("config.yaml", True),       # (filename, clean_secrets)
    ("channel_directory.json", False),
    ("SOUL.md", False),
]

def clean_config(content):
    """替换可能的 secret 值为 REDACTED"""
    # 替换冒号后的长值（>=20 chars 且不含空格）
    lines = content.split('\n')
    cleaned = []
    for line in lines:
        if ':' in line and len(line.split(':', 1)[1].strip()) >= 20:
            key = line.split(':', 1)[0]
            cleaned.append(f"{key}: REDACTED")
        else:
            cleaned.append(line)
    return '\n'.join(cleaned)

def main():
    date = datetime.now().strftime("%Y-%m-%d")
    count = 0
    
    for fname, clean in SAFE_FILES:
        src = HERMES / fname
        if not src.exists():
            continue
        content = src.read_text()
        if clean:
            content = clean_config(content)
        dst = BACKUP_REPO / f"{fname}.snapshot"
        dst.write_text(content)
        count += 1
    
    # 把系统配置快照写入第二大脑知识库
    second_brain_config = HOME / "hermes-business" / "第二大脑" / "wiki" / "system" / "config.md"
    if second_brain_config.exists():
        content = second_brain_config.read_text()
        # 更新日期戳
        content = content.replace("{{DATE}}", f"{date} WAT")
        second_brain_config.write_text(content)
        # 也备份到 GitHub
        dst2 = BACKUP_REPO / ".snapshot" / "system-config.md"
        dst2.parent.mkdir(parents=True, exist_ok=True)
        dst2.write_text(content)
        count += 1
    
    # Commit and push
    subprocess.run(["git", "add", "."], cwd=str(BACKUP_REPO),
                   capture_output=True)
    r = subprocess.run(["git", "commit", "-m", f"snapshot {date}"],
                       cwd=str(BACKUP_REPO), capture_output=True, text=True)
    if r.returncode == 0:
        print(f"[snapshot] Committed {count} files for {date}")
        subprocess.run(["git", "pull", "--rebase"], cwd=str(BACKUP_REPO),
                       capture_output=True, text=True)
        r2 = subprocess.run(["git", "push"], cwd=str(BACKUP_REPO),
                           capture_output=True, text=True)
        if r2.returncode == 0:
            print("[snapshot] Pushed to GitHub OK")
        else:
            print(f"[snapshot] Push issue: {r2.stderr[:200]}")
    else:
        print("[snapshot] Nothing to commit")

if __name__ == "__main__":
    main()
