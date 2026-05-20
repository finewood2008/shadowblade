# Changelog · 火花

## v0.8.0 — 2026-05-20

### 🌱 首个公开 fork 版本

**Build**
- Fork from [yikart/AiToEarn](https://github.com/yikart/AiToEarn) @ MIT
- 全局展示文案：`AiToEarn` / `哎哟赚AiToEarn` / `哎哟赚` → `火花`
- `package.json` name `aiToEarn` → `huohua`
- `electron-builder.json`: `productName=火花`、`appId=cn.huohua.pc`、`publish=null`
- macOS dmg/zip × {arm64, x64} 四件套打包就位

**品牌**
- 紫色四角星火花 SVG logo（`#a78bfa → #8b5cf6 → #6d28d9` 渐变）
- 全尺寸 ICNS / ICO / PNG 资源
- 浅色主题底（`#f5f3ff`）

**安全 / 合规**
- LICENSE 保留 yikart 原版权 + 追加 fork 声明（MIT 合规）
- 关闭上游更新通道避免误连 yikart 服务器

**工具链**
- `scripts/smoke_test.sh` — dmg metadata 验证
- `scripts/check_brand_residue.sh` — 品牌残留守门
- `scripts/prepare_release.sh` — release 打包 + SHA256
- `scripts/install_mac.sh` — 一键 curl 安装
- `Makefile` — `make install / build / smoke / check / release / clean`

**CI**
- `.github/workflows/smoke.yml` — push 触发 dmg smoke test
- `.github/workflows/release.yml` — push tag `v*` 自动 GitHub Release

**文档**
- `README.md` · `LICENSE.txt` · `CHANGELOG.md`
- `docs/PITCH.md` — 产品介绍
- `docs/RELEASE_NOTES.md` — 发布说明
- `docs/landing/index.html` — 紫色风格下载页
- `docs/social/xhs_launch.md` — 小红书发布文案

### 未做（按需）

- Windows / Linux 安装包
- Apple Developer 代码签名 + 公证
- 第三方 SDK Key 替换（i18n / OAuth / 地图仍属 yikart）
- backend 子项目（NX + NestJS）的依赖剥离
