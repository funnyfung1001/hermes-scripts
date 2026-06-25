#!/usr/bin/env python3
"""用 lark-cli --as user 写入方案文档到各个云文档"""
import subprocess, json, os, sys
from pathlib import Path

DOCS = {
    "main": "E2SIduWxtod4dSxeJJlc0VVtnYg",
    "warranty_card": "DDaedkbPwoFuwXxYAm5cTd0Znne",
    "tech_handover": "L8KqdgRhyoRby3xcNG6c5kKvnqg",
    "liability_waiver": "RphFdnSzJo3WN9xhUqrcvdkunuh",
    "mou": "GnlsdWrDZoHPdGx5DqmcbUddn7d",
    "checklist": "VmSgdMLMsoUgz5xFbTgcwhVPnnf",
}
PAGE_ID = {}  # doc_id -> page_block_id

def lark(method, path, data=None):
    env = os.environ.copy()
    env["PATH"] = f"{Path.home()}/.npm-global/bin:{env.get('PATH','')}"
    cmd = ["lark-cli", "api", method, path]
    if data:
        cmd.extend(["--data", json.dumps(data, ensure_ascii=False)])
    cmd.extend(["--as", "user"])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
    return json.loads(r.stdout) if r.stdout.strip() else {}

def add_block(doc_id, block_json):
    pid = PAGE_ID[doc_id]
    r = lark("POST", f"docx/v1/documents/{doc_id}/blocks/{pid}/children", block_json)
    if r.get("ok"):
        return True
    err = str(r.get("error", {}).get("message", ""))
    if "block_id" in err:
        # page_id 不对，重新获取
        return False
    return False

def write_content(doc_id, content_list):
    """写入一系列 block"""
    for block in content_list:
        ok = add_block(doc_id, block)
        if not ok:
            print(f"  ❌ {block.get('block_type','?')}")

def write_main():
    """主方案文档"""
    doc_id = DOCS["main"]
    pid = PAGE_ID[doc_id]
    
    blocks = []
    # H1 title
    blocks.append({
        "children": [{
            "block_type": 2,
            "text": {"elements": [{"text_run": {"content": "日期: 2026-06-25，参考: TranESS SLA / IHY-50KH3S SOP"}}]}
        }]
    })
    
    # H2 文档总览
    blocks.append({
        "children": [{
            "block_type": 4,
            "heading2": {"elements": [{"text_run": {"content": "文档总览", "bold": True}}]}
        }]
    })
    
    blocks.append({
        "children": [{
            "block_type": 2,
            "text": {"elements": [{"text_run": {"content": "本方案包含以下子文档："}}]}
        }]
    })
    
    # 写入所有子文档引用
    docs_list = [
        "保修卡模板（Warranty Card）— 双面中英文保修卡",
        "技术交底协议模板 — EPC与客户的操作交底确认文件",
        "质量安全免责协议模板 — 施工质量与安全责任划分",
        "国包-EPC合作备忘录（MOU）— ND与EPC的框架合作协议",
        "IHY-50KH3S安装质量控制清单 — 安装施工关键检查点",
    ]
    for d in docs_list:
        blocks.append({
            "children": [{
                "block_type": 2,
                "text": {"elements": [{"text_run": {"content": f"• {d}"}}]}
            }]
        })
    
    # 节1-10 用简写
    for block in blocks:
        r = lark("POST", f"docx/v1/documents/{doc_id}/blocks/{pid}/children", block)
        status = "✅" if r.get("ok") else "❌"
        print(f"{status}: {str(block)[:60]}")
    
    # 后续内容...
    sections = [
        (4, "一、方案总览"),
        (2, "角色：品牌方(TranESS) → 国包/ND(Fundco) → EPC → 最终客户"),
        (2, "核心逻辑：保修卡随货→MOU→技术交底+质量免责→保修卡回传→质保生效"),
        (5, "二、详细执行流程"),
        (2, "Step1: 客户下单 → 品牌方发出设备+保修卡（含SN码）"),
        (2, "Step2: ND与EPC签署MOU"),
        (2, "Step3: EPC准备安装（参考IHY-50KH3S SOP）"),
        (2, "Step4: 【安装前】EPC与客户签署技术交底+质量免责协议"),
        (2, "Step5: EPC按SOP完成安装"),
        (2, "Step6: 保修卡副本→ND→品牌方→SN码激活→质保生效"),
        (4, "三、质保生效条件"),
        (2, "质保必要条件：合规渠道+技术团队审核+认证EPC安装+协议签署+保修卡回传"),
        (2, "不满足任一条件 → 品牌方不提供质保"),
        (4, "四、质保期限"),
        (2, "逆变器/高压箱/BMS: 5年 | 电池包: 5年 | 配件: 不在质保范围"),
        (2, "质保起算: 保修卡副本回传品牌方审核通过之日（如无cloud数据）"),
        (5, "五、附录文件索引"),
        (2, "见各子文档"),
    ]
    
    for bt, text in sections:
        block_type = {4: "heading2", 5: "heading3", 2: "text"}[bt]
        block = {
            "children": [{
                "block_type": bt,
                block_type: {"elements": [{"text_run": {"content": text, "bold": bt >= 4}}]}
            }]
        }
        r = lark("POST", f"docx/v1/documents/{doc_id}/blocks/{pid}/children", block)
        print(f"{'✅' if r.get('ok') else '❌'}: {text[:40]}")

def main():
    os.environ["PATH"] = f"{Path.home()}/.npm-global/bin:{os.environ.get('PATH','')}"
    
    # 获取所有文档的 page block ID
    for key, doc_id in DOCS.items():
        r = lark("GET", f"docx/v1/documents/{doc_id}/blocks?page_size=5")
        if r.get("ok"):
            items = r.get("data", {}).get("items", [])
            if items:
                PAGE_ID[doc_id] = items[0]["block_id"]
                print(f"✅ {key}: {doc_id}")
        else:
            print(f"❌ {key}: {r.get('error',{}).get('message','')}")
    
    write_main()
    print("\n✅ 主方案文档写入完成")

if __name__ == "__main__":
    main()
