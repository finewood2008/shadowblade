# 火花架构概览

> 基于 yikart/AiToEarn 的二次开发版本 · MIT

## 整体拓扑

```
┌─────────────────────────────────────────────────────────────┐
│  火花·Huohua (this fork)                                     │
│                                                              │
│  ┌───────────────────┐   ┌──────────────────────────────┐   │
│  │ aitoearn-electron │   │  aitoearn-web                │   │
│  │ React + Vite      │   │  Next.js 14 + Radix + AntD   │   │
│  │ 桌面端工作台      │   │  配套 Web 端 / Dashboard     │   │
│  └─────────┬─────────┘   └──────────────┬───────────────┘   │
│            │                            │                    │
│            │  Electron 主进程 (server/)  │                    │
│            │  ▸ 13+ 平台 SDK            │                    │
│            │  ▸ 账号/Cookie 管理         │                    │
│            │  ▸ better-sqlite3 本地存储  │                    │
│            │  ▸ ffmpeg 媒体处理          │                    │
│            └──────────────┬─────────────┘                    │
│                           │                                  │
│                           ▼                                  │
│            ┌──────────────────────────────┐                  │
│            │ aitoearn-backend (NX)        │                  │
│            │ NestJS 服务端                │                  │
│            │ ▸ AI Agent 调度              │                  │
│            │ ▸ 内容市场撮合 (CPS/CPE/CPM) │                  │
│            └──────────────────────────────┘                  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────┐
    │  外部接入 (13+ 平台 SDK)                         │
    │  抖音 · 小红书 · 快手 · 视频号 · B站 · TikTok    │
    │  YouTube · IG · Threads · X · Pinterest · LI    │
    └─────────────────────────────────────────────────┘
```

## 关键技术栈

| 层 | 技术 |
|---|---|
| Electron 渲染 | React 18 + Vite 6 + Ant Design + Zustand |
| Electron 主进程 | Node 20 + better-sqlite3 + fluent-ffmpeg + electron-store |
| Web 端 | Next.js 14 + Radix UI + Ant Design + TanStack + i18next |
| Backend | NX monorepo + NestJS 11 + (上游服务) |
| 打包 | electron-builder 26 (dmg / zip / nsis) |
| 国际化 | 7 种语言（zh-CN / en / ja / de / ko / fr 等） |

## 火花 fork 的修改边界

### ✅ 改了

| 类别 | 内容 |
|---|---|
| 展示文案 | `AiToEarn` / `哎哟赚AiToEarn` / `哎哟赚` → `火花`（全 7 语言 i18n + README + UI 字符串） |
| 包元数据 | `name: aiToEarn → huohua`、`appId: cn.aitoearn.pc → cn.huohua.pc`、`productName → 火花` |
| 品牌资源 | 紫色四角星 SVG + ICNS + ICO + 各尺寸 PNG |
| 安全 | 关闭上游更新通道（`publish: null`） |
| 合规 | LICENSE 保留 yikart 原版权 + 追加 fork 声明 |
| Build 适配 | web 端 `eslint.ignoreDuringBuilds` + `typescript.ignoreBuildErrors` |

### ❌ 故意不改

| 类别 | 内容 | 原因 |
|---|---|---|
| 目录名 | `project/aitoearn-electron/` 等 | 牵涉脚本/绝对路径 |
| 全小写域名 | `aitoearn.ai` `yikart.cn` `cn.aitoearn.pc` 在 URL | 指向真实运行的上游服务 |
| NX scope | `@yikart/source` | workspace 内部引用太多 |
| 第三方 SDK key | Locize i18n、Google OAuth | 是上游账号，业务化前需自换 |

## 数据流（创作 → 发布）

```
用户输入提示 ──→ AI Agent 生成内容 (文/图/视频/标签)
                       │
                       ▼
              [Electron 渲染层 UI]
                       │
                       ▼ (IPC)
              [Electron 主进程]
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
     平台 A SDK    平台 B SDK    平台 N SDK
        │              │              │
        ▼              ▼              ▼
     [抖音 API]   [小红书 API]   [...]
        │              │              │
        └──────────────┴──────────────┘
                       │
                       ▼
              [本地 SQLite 任务表]
                       │
                       ▼
              [数据回收: 评论/转化/收益]
                       │
                       ▼
              [Web Dashboard 展示]
```

## 进一步剥离上游的路径

如要做更彻底的独立化：

1. **替换目录名**: `aitoearn-{electron,web,backend}` → `huohua-{electron,web,backend}`，更新 nx.json / tsconfig.paths / 所有相对路径引用
2. **自建后端服务**: 起一个 huohua-backend 替换 yikart 的 API，业务逻辑需重新实现
3. **替换 SDK key**: Locize 项目、Google OAuth client、各平台开发者账号
4. **图标商标**: 设计独立的火花标识（当前为 SVG 占位）
5. **自有更新通道**: 接入自家 release server（GitHub Releases 是免费方案）

---

火花当前定位：**致敬上游 + 个人视觉/品牌偏好**，不打算与上游分叉演进。
