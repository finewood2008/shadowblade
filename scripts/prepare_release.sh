#!/usr/bin/env bash
# 准备 GitHub Release：收集 dmg/zip → 生成 SHA256 → 输出 release/dist 目录
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-0.8.0}"
SRC="$ROOT/project/aitoearn-electron/release/$VERSION"
OUT="$ROOT/dist/release-v$VERSION"

[[ -d "$SRC" ]] || { echo "❌ 找不到产物目录 $SRC，先跑 npm run build:notsc"; exit 1; }

rm -rf "$OUT" && mkdir -p "$OUT"

echo "📦 收集产物 (v$VERSION) ..."
cp "$SRC"/*.dmg "$SRC"/*.zip "$OUT/" 2>/dev/null

cd "$OUT"
echo "🔐 生成 SHA256 ..."
shasum -a 256 *.dmg *.zip > SHA256SUMS.txt

echo ""
echo "✨ Release 就绪 → $OUT"
echo ""
ls -lh "$OUT" | awk '{print "  " $9 "  " $5}'
echo ""
echo "📜 校验和:"
cat SHA256SUMS.txt | sed 's/^/  /'
echo ""
echo "👉 下一步: gh release create v$VERSION $OUT/* --title \"火花 v$VERSION\" --notes-file docs/RELEASE_NOTES.md"
