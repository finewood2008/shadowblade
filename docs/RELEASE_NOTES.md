# 火花 v0.8.0 · 首个公开版本

> 2026-05-20 · Fork from yikart/AiToEarn · MIT

## 下载

| 平台 | 文件 | 大小 |
|---|---|---|
| 🍎 Apple Silicon (M1/M2/M3/M4) | `火花-0.8.0-arm64.dmg` | 269MB |
| 🍎 Intel Mac | `火花-0.8.0-x64.dmg` | 273MB |
| 📦 免挂载 zip | `火花-0.8.0-{arm64,x64}.zip` | 258-263MB |

## 首次打开

```bash
xattr -cr /Applications/火花.app   # 解 Gatekeeper（个人 fork 未签名）
```

或右键 → 打开 → 强制打开一次。

## 这个版本做了什么

- 🎨 全新品牌：紫色火花标识、浅色主题底
- 🔄 全仓库展示文案 AiToEarn / 哎哟赚 → 火花
- ⚙️ `appId: cn.huohua.pc`、`productName: 火花`、`name: huohua`
- 🔒 关闭上游更新服务器（`publish: null`），避免误连 yikart
- 📜 LICENSE 保留 yikart 团队原版权 + 追加 fork 声明（MIT 合规）

## 已知限制

- 未做代码签名（个人项目，无 Apple Developer 账号）
- 自动更新通道关闭，新版本需手动下载
- 第三方 SDK Key（i18n / 登录 / 地图）仍是上游 yikart 的，跑业务前请替换为自己的
- 仅打 macOS，Windows / Linux 后续补

## 致谢

🌱 核心架构、Agent 能力、各平台对接均归属上游 [yikart/AiToEarn](https://github.com/yikart/AiToEarn)。如需官方版本 / 商业支持，请使用 https://aitoearn.ai。

---

🔥 「你只管想内容，剩下都交给火花。」
