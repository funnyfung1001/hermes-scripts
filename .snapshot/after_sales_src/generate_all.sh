#!/bin/bash
# 一键生成全部售后文档PDF + 上传到飞书
# 用法: bash generate_all.sh

set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "=== 生成全部PDF ==="

for html in warranty_card.html tech_handover.html liability_waiver.html mou.html checklist.html; do
    pdf="${html%.html}.pdf"
    echo "生成 $pdf ..."
    python3 -m weasyprint "$html" "$pdf" 2>/dev/null
    echo "  ✅ $(ls -lh "$pdf" | awk '{print $5}')"
done

echo ""
echo "=== PDF已生成，手动上传命令 ==="
echo "如需上传到飞书，逐个执行："
for html in warranty_card.html tech_handover.html liability_waiver.html mou.html checklist.html; do
    pdf="${html%.html}.pdf"
    case $html in
        warranty_card.html) name="保修卡模板.pdf" ;;
        tech_handover.html) name="技术交底协议模板.pdf" ;;
        liability_waiver.html) name="质量安全免责协议模板.pdf" ;;
        mou.html) name="国包-EPC合作备忘录.pdf" ;;
        checklist.html) name="IHY-50KH3S安装质量控制清单.pdf" ;;
    esac
    echo "  SIZE=\$(stat -c%s ./$pdf)"
    echo "  cp ./$pdf ~/$name"
    echo "  lark-cli api POST 'drive/v1/files/upload_all' --as user --data '{\"file_name\":\"$name\",\"parent_type\":\"explorer\",\"parent_node\":\"\",\"size\":\$SIZE}' --file ~/$name"
    echo "  rm ~/$name"
done

echo ""
echo "=== 完成 ==="