# 火花 · 60 秒 Demo 视频脚本

> 用于 B 站 / 小红书 / 视频号短视频首发

## 节奏（60s 总）

| 时间 | 镜头 | 文案 / 旁白 | 视觉重点 |
|---|---|---|---|
| 0-5s | 紫色火花 logo 出现 + 标语 | 「一束火，点燃创作 → 分发 → 互动 → 变现」 | logo 渐入 + 粒子动画 |
| 5-12s | 痛点切镜 | 「一个人做创作者，80% 时间在搬运、改格式、抠平台规则」 | 13 个平台 logo 雨落 |
| 12-22s | Create 演示 | 「火花，AI 一键写文案、生图、生视频」 | 文字 streaming + 图片 fade in |
| 22-32s | Publish 演示 | 「一篇内容，13 个平台同步发」 | 多个平台 UI 截图同步出现 |
| 32-42s | Engage 演示 | 「评论、私信，半自动托管」 | 通知气泡涌出又被自动处理 |
| 42-50s | Monetize 演示 | 「CPS / CPE / CPM 三种结算接广告」 | 收益数字滚动上升 |
| 50-58s | 一句话总结 | 「你只管想内容，剩下都交给火花」 | logo + 下载二维码 |
| 58-60s | CTA | 「macOS 即装即用 · GitHub 搜火花」 | URL + 二维码停留 |

## 字幕标点 (用于 hyperframes captions)

```
0.0s  | 火花
0.5s  | 一束火
1.5s  | 点燃创作 → 分发 → 互动 → 变现
5.0s  | 一个人做创作者
6.5s  | 80% 时间在搬运
8.0s  | 改格式
9.0s  | 抠平台规则
12.0s | AI 一键写文案
14.0s | 生图
15.0s | 生视频
22.0s | 一篇内容
23.5s | 13 个平台同步发
32.0s | 评论
33.0s | 私信
34.0s | 半自动托管
42.0s | CPS · CPE · CPM
44.0s | 三种结算接广告
50.0s | 你只管想内容
52.0s | 剩下都交给火花
58.0s | macOS 即装即用
```

## 配乐建议

- 节奏感强的 lo-fi electronic（avoid epic 风）
- 主色调与 logo 配：紫色 + 浅色 → 慵懒、聚焦
- 推荐参考：Tycho - "Awake"、Bonobo - "Cirrus" 节奏型

## 制作方式

可用 hyperframes 直接生成（项目内已有 hyperframes-cli 工具）：

```bash
npx hyperframes init --name huohua-demo
# 把上面字幕表导入 captions.json
# 把 huohua-logo.svg / og-card-bg.png 作为基础素材
npx hyperframes preview
npx hyperframes render --duration 60
```

## 关键素材清单

- `assets/brand/huohua-logo.svg` — 主 logo
- `assets/brand/og-card-bg.png` — 1200x630 底图
- 13 个平台 icon（从 `project/aitoearn-web/src/assets/svgs/plat/` 取）
- App 截图：火花 dashboard 主界面 + 发布工作台 + 数据中心
