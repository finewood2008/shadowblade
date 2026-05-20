#!/usr/bin/env bash
# 火花 dmg smoke test —— 验证打包产物 metadata 是否正确
# 用法: ./scripts/smoke_test.sh [arm64|x64]
set -euo pipefail

ARCH="${1:-arm64}"
DMG="$(dirname "$0")/../project/aitoearn-electron/release/0.8.0/火花-0.8.0-${ARCH}.dmg"

[[ -f "$DMG" ]] || { echo "❌ 找不到 $DMG"; exit 1; }

echo "📦 挂载 $DMG ..."
# hdiutil attach -plist 输出挂载点，无论卷名带不带 -arch 后缀都能拿到
VOL=$(hdiutil attach "$DMG" -nobrowse -plist | sed -n 's:.*<string>\(/Volumes/[^<]*\)</string>.*:\1:p' | head -1)
[[ -n "$VOL" ]] || { echo "❌ 挂载失败"; exit 1; }
echo "   → 卷: $VOL"

trap 'hdiutil detach "$VOL" -quiet 2>/dev/null || true' EXIT

APP="$VOL/火花.app"
[[ -d "$APP" ]] || { echo "❌ 找不到 $APP"; exit 1; }

echo "🔍 校验 Info.plist ..."
EXPECTED=(
  "CFBundleName:火花"
  "CFBundleDisplayName:火花"
  "CFBundleIdentifier:cn.huohua.pc"
  "CFBundleIconFile:icon.icns"
)

PLIST=$(plutil -p "$APP/Contents/Info.plist")
fail=0
for kv in "${EXPECTED[@]}"; do
  k="${kv%%:*}"; v="${kv##*:}"
  if echo "$PLIST" | grep -q "\"$k\" => \"$v\""; then
    echo "  ✅ $k = $v"
  else
    echo "  ❌ $k ≠ $v"; fail=1
  fi
done

[[ -f "$APP/Contents/Resources/icon.icns" ]] && echo "  ✅ icon.icns 存在" || { echo "  ❌ 缺 icon.icns"; fail=1; }

if [[ $fail -eq 0 ]]; then
  echo "✨ 火花 ${ARCH} smoke test 通过"
else
  echo "❌ 火花 ${ARCH} smoke test 失败"
  exit 1
fi
