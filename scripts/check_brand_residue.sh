#!/usr/bin/env bash
# 检查源码/产物里是否有未替换的上游品牌字符串
# 豁免规则：
#   - 行内含 "yikart" 或 "基于" 的致谢/出处引用允许保留
#   - 路径/scope (aitoearn.ai / @yikart) 不在扫描范围（只扫大小写敏感的展示字符串）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

echo "🔍 扫描源码品牌残留（豁免致谢/出处引用）..."

# grep -n 行号 + 大小写敏感
grep -rnE --include="*.ts" --include="*.tsx" --include="*.js" --include="*.json" \
     --include="*.md" --include="*.html" --include="*.vue" \
     "AiToEarn|aiToEarn|哎哟赚" "$ROOT" 2>/dev/null \
  | grep -v node_modules \
  | grep -v package-lock.json \
  | grep -v ".next/" \
  | grep -v "release/" \
  | grep -v "dist-electron/" \
  | grep -v "dist/" \
  | grep -vE "yikart|基于|上游|fork|Fork|FROM:|参见|致敬|致谢|原版本|原项目|原作者|参考|reference|copyright|Copyright" \
  > "$TMP" || true

count=$(wc -l < "$TMP" | tr -d ' ')

if [[ $count -gt 0 ]]; then
  echo "❌ 发现 $count 处真品牌残留："
  cat "$TMP" | sed 's/^/   /'
  echo "⚠️  请清理或加豁免词后再发布"
  exit 1
else
  echo "✅ 源代码干净（已豁免致谢类引用）"
  echo "✨ 品牌替换 100% 通过"
  exit 0
fi
