#!/usr/bin/env bash
# 火花 macOS 一键安装脚本
# 用法: bash <(curl -fsSL https://raw.githubusercontent.com/<your-user>/huohua/main/scripts/install_mac.sh)
set -euo pipefail

VERSION="${HUOHUA_VERSION:-0.8.0}"
ARCH="$(uname -m)"
case "$ARCH" in
  arm64) FILE="火花-${VERSION}-arm64.dmg" ;;
  x86_64) FILE="火花-${VERSION}-x64.dmg" ;;
  *) echo "❌ 不支持的架构: $ARCH"; exit 1 ;;
esac

URL="https://github.com/<your-user>/huohua/releases/download/v${VERSION}/${FILE}"
DEST="$HOME/Downloads/${FILE}"

echo "🔥 火花 v${VERSION} 安装器"
echo "📦 架构: $ARCH → $FILE"
echo "⬇️  下载到: $DEST"

if [[ ! -f "$DEST" ]]; then
  curl -L --progress-bar "$URL" -o "$DEST"
else
  echo "✓ 已存在本地缓存，跳过下载"
fi

echo "📂 挂载 dmg ..."
VOL=$(hdiutil attach "$DEST" -nobrowse -plist | sed -n 's:.*<string>\(/Volumes/[^<]*\)</string>.*:\1:p' | head -1)
trap 'hdiutil detach "$VOL" -quiet 2>/dev/null || true' EXIT

APP="$VOL/火花.app"
[[ -d "$APP" ]] || { echo "❌ dmg 内未找到 火花.app"; exit 1; }

echo "📥 拷贝到 /Applications ..."
rm -rf "/Applications/火花.app" 2>/dev/null || true
cp -R "$APP" /Applications/
xattr -cr /Applications/火花.app

echo ""
echo "✨ 安装完成 → /Applications/火花.app"
echo "👉 在 Launchpad 或 Finder Applications 中双击运行"
