# 火花 · Huohua

> 让一束火花，点燃创作 → 分发 → 互动 → 变现的全链路。

<p>
  <img src="assets/brand/huohua-logo.svg" alt="火花 logo" width="120"/>
</p>

`火花` 是面向「一人公司 / 创作者」的 AI 内容营销桌面端，覆盖：

- **Create** —— AI 生成文案 / 图片 / 视频 / 标签
- **Publish** —— 一键多平台分发（抖音 / 小红书 / 快手 / 视频号 / B站 / TikTok / YouTube / Instagram / Threads / X / Pinterest / LinkedIn / Facebook）
- **Engage** —— 评论、私信、互动自动化
- **Monetize** —— 内容任务市场（CPS / CPE / CPM 三种结算模式）

---

## 🌱 项目缘起

火花是基于 **[AiToEarn](https://github.com/yikart/AiToEarn)**（yikart 团队，14.9k stars，MIT 协议）的二次开发版本。
本项目仅做品牌替换、本地化与个人化改造，**核心架构、Agent 能力、各平台对接均归属上游 AiToEarn**。

如需官方版本 / 商业支持 / 最新功能，请使用 yikart 团队维护的原版：
- 官网: https://aitoearn.ai
- 源码: https://github.com/yikart/AiToEarn

---

## 📦 项目结构

```
project/
├── aitoearn-electron/   # Electron 桌面端 (React + Vite + Ant Design)
│   ├── electron/        # 主进程：托盘、自动更新、IPC、平台 SDK 调用
│   ├── server/          # 内嵌 NestJS 服务（账号体系、任务、媒体处理）
│   └── src/             # 渲染进程 UI
├── aitoearn-web/        # 配套 Web 端 (Next.js 14 + Ant Design + Radix UI)
└── aitoearn-backend/    # NX monorepo · 服务端（AI Agent、内容市场）
```

> 目录名沿用上游，避免脚本/路径牵连。展示层品牌名已替换为「火花」。

---

## 🚀 本地启动

需要 Node.js **20.18.x**（见 `package.json` engines）。

### Electron 桌面端

```bash
cd project/aitoearn-electron
npm install
npm run dev        # Windows
npm run dev:mac    # macOS
```

### Web 端

```bash
cd project/aitoearn-web
npm install
npm run dev        # http://localhost:6060
```

### 打包桌面端

```bash
cd project/aitoearn-electron
npm run build
```

> ⚠️ 打包前先把 `public/assets/favicon.ico` / `favicon.icns` 替换成你自己的图标
> （可用 `assets/brand/huohua-logo.svg` 通过 Inkscape / iconutil / 在线工具导出）。

---

## 🎨 品牌资源

- 主 logo: [`assets/brand/huohua-logo.svg`](assets/brand/huohua-logo.svg)
- 主色：紫色系（`#a78bfa → #8b5cf6 → #6d28d9`），浅色主题底（`#f5f3ff`）

---

## 🔧 火花 fork 已改 / 未改 清单

✅ **已改**
- 全仓库展示文案：`AiToEarn` / `哎哟赚AiToEarn` / `哎哟赚` → `火花`
- `aiToEarn`（package name）→ `huohua`
- `electron-builder.json`：`productName` → `火花`，`appId: cn.aitoearn.pc` → `cn.huohua.pc`
- 关闭上游更新服务器（`publish: null`），避免误拉 / 误推 yikart 的资源
- LICENSE 保留 yikart 团队原版权 + 追加火花 fork 声明
- 紫色火花 SVG logo

⚠️ **未改（动了会出问题）**
- 目录名 `project/aitoearn-electron/` 等（牵连脚本和绝对路径）
- 全小写域名/标识 `aitoearn.ai`、`yikart.cn`、`cn.aitoearn.pc` 在 URL / scope 里的引用（外部资源真实存在）
- `@yikart/source` NX scope（workspace 内部引用太多）
- 第三方 SDK key（Locize i18n、Google OAuth、地图等）—— 都是 yikart 的账号，跑业务前你需要换成自己的

要做更彻底的剥离，按这份未改清单逐项处理即可。

---

## 📜 License

[MIT](LICENSE.txt) · 上游 AiToEarn © yikart team · 本 fork © qiu, 2026
