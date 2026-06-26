# 系统配置

## 云文档索引（2026-06-25 统一框架）

| 文档 | Token | 语言 | 结构 | 状态 |
|------|-------|------|------|------|
| 日会纪要（中文） | `AkoGdGuBjovKoMxf3Qwc26FLnJg` | 中文 | `📋会议摘要 → 📊项目进展 → ✅待办 → 🔑关键决策 → ⚠️问题风险` | ✅ 已清理重复 |
| 日会纪要（英文） | `AHRkdz0TDouA7qxFTzkc36QSnEf` | 英文 | `Summary → Project Updates → Action Items → Decisions → Risks` | ✅ 新创建 |
| 周会/周报（中文） | `EYdqdDtfxoSvKGxcmfhcI2zdn2f` | 中文 | `📋会议概要 → 📊项目进展 → 💰财务销售 → 📈市场情报 → ✅待办 → 🔑决策 → ⚠️风险` | ✅ 新创建 |
| 周会/周报（英文旧） | `WvZSdhOm8oRjpQxusfvcNSvsnbb` | 英文 | — | ⚠️ 空 |
| 日报中文版 | `IltidiIKDosnuSxBuiscyuapnng` | 中文 | `今日概览 → 项目进展 → 市场动态 → 团队行政 → 待办 → 摘要` | ⚠️ 有日期空缺 |
| 日报英文版 | `CrsSdqt6cored0xXeEhciXhcnsd` | 英文 | `Overview → Project Updates → Market Intel → Team → Actions → Summary` | ⚠️ 同上 |
| 文档模板规范 | `VsPedjBJ8oXKOoxJnDocQdtRnMc` | 中英 | 所有文档模板定义 | ✅ v1.0 |

## 文档模板文件
`~/.hermes/scripts/doc_templates.xml`

## 三层分发逻辑
1. 完整详细版 → 飞书云文档（中文版）
2. 中文摘要 → 私聊冯立（union_id: `on_42429dc6344eee41ffa1d3f0858430e5`）
3. 英文筛选 → C&I Nigeria 工作群（chat_id: `oc_25258127a0401e59b0bca9fe20aee436`）
