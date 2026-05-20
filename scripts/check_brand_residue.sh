#!/usr/bin/env bash
# 检查源码/产物里是否有未替换的上游品牌字符串
# 已知豁免：URL/scope/目录名（aitoearn.ai / yikart / @yikart/source / aitoearn-electron 目录）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fail=0

echo "🔍 扫描源代码中的展示层品牌残留 ..."
RES=$(grep -rEl --include="*.ts" --include="*.tsx" --include="*.js" --include="*.json" \
       --include="*.md" --include="*.html" --include="*.vue" \
       "AiToEarn|aiToEarn|哎哟赚" "$ROOT" 2>/dev/null \
       | grep -v node_modules \
       | grep -v package-lock.json \
       | grep -v ".next/" \
       | grep -v "release/" \
       | grep -v "dist-electron/" || true)

if [[ -n "$RES" ]]; then
  echo "❌ 发现品牌残留："
  echo "$RES" | sed 's/^/   /'
  fail=1
else
  echo "✅ 源代码干净"
fi

if [[ $fail -eq 0 ]]; then
  echo "✨ 品牌替换 100% 通过"
  exit 0
else
  echo "⚠️  请清理残留后再发布"
  exit 1
fi
