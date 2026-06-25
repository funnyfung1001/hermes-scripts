---
name: feishu-docx-generator
description: 生成飞书云文档和PDF文件的完整工作流 — 创建文档、写入Markdown、上传PDF附件、在云文档中生成索引表。
tags: [feishu, docx, pdf, document, workflow]
---

# 飞书文档生成工作流

## 核心命令

### 1. 创建飞书云文档
```bash
lark-cli api POST "docx/v1/documents" \
  --data '{"folder_token":"","title":"文档标题"}' \
  --as user
# 返回 document_id
```

### 2. 写入内容（支持Markdown）
```bash
# overwrite（清空后写入，适合新文档首写）
lark-cli docs +update --api-version v2 \
  --doc "<doc_id>" \
  --command overwrite \
  --doc-format markdown \
  --as user \
  --content "# Content"

# append（追加到末尾）
lark-cli docs +update --api-version v2 \
  --doc "<doc_id>" \
  --command append \
  --doc-format markdown \
  --as user \
  --content "# More content"

# 从文件读取（需先在目标目录cd）
cd ~
lark-cli docs +update --api-version v2 \
  --doc "<doc_id>" \
  --command overwrite \
  --doc-format markdown \
  --as user \
  --content @./filename.md
```

**重要：** `--as user` 在 `docs +update` 命令上支持！以前的skill说"不支持"是错的。新文档 bot 没有编辑权限，必须用 `--as user`。

### 3. 删除Block
```bash
# 批量删除（逗号分隔）
lark-cli docs +update --api-version v2 \
  --doc "<doc_id>" \
  --command block_delete \
  --block-id "<id1>,<id2>" \
  --as user

# 获取block列表
lark-cli api GET "docx/v1/documents/<doc_id>/blocks?page_size=500" --as user
```

### 4. 文本替换
```bash
lark-cli docs +update --api-version v2 \
  --doc "<doc_id>" \
  --command str_replace \
  --pattern "旧文本" \
  --content "新文本" \
  --as user
# content为空=删除匹配文本
```

### 5. 生成PDF（HTML → WeasyPrint → PDF）
```bash
# 安装
pip3 install weasyprint --break-system-packages

# 生成
python3 -m weasyprint input.html output.pdf
```

### 6. 上传PDF到飞书
```bash
# 上传（需要size字段和相对路径的file）
SIZE=$(stat -c%s ./filename.pdf)
lark-cli api POST "drive/v1/files/upload_all" \
  --data "{\"file_name\":\"文件名.pdf\",\"parent_type\":\"explorer\",\"parent_node\":\"\",\"size\":$SIZE}" \
  --as user \
  --file ./filename.pdf
# 返回 file_token 和 url
```

### 7. 获取文档内容
```bash
lark-cli api GET "docx/v1/documents/<doc_id>/raw_content" --as user
```

## HTML→PDF排版要点

- **@page size**: A4（标准文档）或 A5 landscape（保修卡双面）
- **weasyprint** 支持 CSS3 基本排版：flex、gradient、border、@page
- 中文字体用 `Arial` 或 `sans-serif`（WSL环境够用）
- 边框、背景色、渐变都支持
- HTML 里面的 `page-break-before:always` 控制分页

## 生成PDF的完整流程（参考）
```python
# 1. 写HTML
write_file('/tmp/doc.html', html_content)
# 2. 转PDF
terminal('python3 -m weasyprint /tmp/doc.html /tmp/doc.pdf')
# 3. 上传
SIZE = $(stat -c%s /tmp/doc.pdf)
lark-cli api POST "drive/v1/files/upload_all" \
  --data '{"file_name":"name.pdf","parent_type":"explorer","parent_node":"","size":$SIZE}' \
  --as user --file ./name.pdf
```

## 文档清单与维护

### 售后服务体系文档（编写于2026-06-25）

| # | 文档 | 类型 | 文档ID / FileToken | 排版来源 |
|---|------|------|-------------------|----------|
| 1 | **主方案** `尼日利亚工商储售后服务执行方案 v1.0` | 飞书云文档 | `E2SIduWxtod4dSxeJJlc0VVtnYg` | Markdown直接写入 |
| 2 | **保修卡模板** | PDF + 云文档 | PDF: `KYpjbIBm8olfBXx4LdqcVl2KnJc`<br>云文档: `DDaedkbPwoFuwXxYAm5cTd0Znne` | HTML→WeasyPrint→PDF |
| 3 | **技术交底协议模板** | PDF + 云文档 | PDF: `EOjsbRl1Aoypg4xDwfQccY9Pn6c`<br>云文档: `L8KqdgRhyoRby3xcNG6c5kKvnqg` | HTML→WeasyPrint→PDF |
| 4 | **质量安全免责协议模板** | PDF + 云文档 | PDF: `IyKabG71AoJHEIxz9ptc0g8LnT7`<br>云文档: `RphFdnSzJo3WN9xhUqrcvdkunuh` | HTML→WeasyPrint→PDF |
| 5 | **国包-EPC MOU模板** | PDF + 云文档 | PDF: `GCvMbq7p8oLA4hxvbJWcVwMdnnd`<br>云文档: `GnlsdWrDZoHPdGx5DqmcbUddn7d` | HTML→WeasyPrint→PDF |
| 6 | **IHY-50KH3S安装质量控制清单** | PDF + 云文档 | PDF: `EOlfbBHiqo4FhUxyTlyctvomnWc`<br>云文档: `VmSgdMLMsoUgz5xFbTgcwhVPnnf` | HTML→WeasyPrint→PDF |

### 源文件位置
所有 HTML 源文件（排版模板）和生成脚本存在：
```
~/hermes-business/第二大脑/wiki/system/after_sales_src/
├── warranty_card.html        # 保修卡HTML排版模板
├── tech_handover.html        # 技术交底协议HTML排版模板
├── liability_waiver.html     # 质量安全免责协议HTML排版模板
├── mou.html                  # MOU模板HTML排版模板
├── checklist.html            # 安装检查清单HTML排版模板
├── main_doc.md               # 主方案文档Markdown源
└── generate_all.sh           # 一键生成全部PDF
```

### 更新流程

**如果只改文字内容（不改排版）：**
1. 直接在飞书云文档编辑（最方便）
2. 在 HTML 源文件中同步修改对应内容
3. 重新生成 PDF：`cd ~/hermes-business/第二大脑/wiki/system/after_sales_src/ && bash generate_all.sh`

**如果改排版结构（增删章节）：**
1. 修改 HTML 源文件
2. 重新生成 PDF：`python3 -m weasyprint input.html output.pdf`
3. 重新上传覆盖：用 `upload_all` API 同名文件覆盖
4. 同步更新飞书云文档（如果云文档也要改）

**如果增删文档（整套方案迭代）：**
1. 创建新 HTML 源文件
2. 生成 PDF 并上传
3. 创建对应的飞书云文档（可选）
4. 更新主方案文档的附录A索引表

### 生成脚本参考
```bash
# 单文档PDF生成
python3 -m weasyprint /tmp/input.html /tmp/output.pdf

# 上传
SIZE=$(stat -c%s /tmp/output.pdf)
cp /tmp/output.pdf ./output.pdf
lark-cli api POST "drive/v1/files/upload_all" \
  --data "{\"file_name\":\"文件名.pdf\",\"parent_type\":\"explorer\",\"parent_node\":\"\",\"size\":$SIZE}" \
  --as user --file ./output.pdf
rm ./output.pdf

# 更新主方案文档的索引表（用str_replace替换附录表格）
lark-cli docs +update --api-version v2 \
  --doc "<主方案doc_id>" \
  --command str_replace \
  --pattern "旧表格" --content "新表格" --as user
```

### 参考文档（已上传的原始资料）
- `TranESS After-Sales Service Agreement v1.0`（PDF版）
- `SLA OEM-EPC-Client v1.0`（docx版）
- `IHY-50KH3S Installation SOP v1.0`（docx版）

| 问题 | 原因 | 解决 |
|------|------|------|
| 3380004 (无权限) | docs +update 默认用bot | 加 `--as user` |
| @file 读取失败 | 只支持相对路径 | `cd ~` 后再用 `@./file.md` |
| 99992402 | lark-cli 参数格式问题 | 改用主Bot HTTP API 或去掉可疑参数 |
| 409/冲突 | revision_id 冲突 | 用 `--revision-id -1` |
| PDF params error | 上传缺 `size` 字段 | 必须传 `size=$(stat -c%s file)` |
