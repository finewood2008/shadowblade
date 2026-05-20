# 店铺视频助手 -- 商家端交互原型 v1.0

> 产出日期: 2026-05-20
> 适用端: 微信小程序 (H5 兼容)
> 目标读者: 前端开发 / 后端对接
> 内部代号: 火花 (对外不露出)

---

## 1. 用户旅程总览

```
[启动页] ──微信授权──> [店铺信息填写] ──保存──> [首页/任务列表]
                                                    │
                              ┌─────────────────────┤
                              v                     v
                        [创建任务]            [历史记录]
                              │                     │
                    ┌─────────┤                     v
                    v         v              [数据填报]
              [选模板]   [上传素材]
                    │         │
                    v         v
                [填写信息/标签]
                        │
                        v
                  [提交确认]
                        │
                        v
                [等待处理/进度]
                        │
                        v
                  [审核成片]
                        │
                  ┌─────┴─────┐
                  v           v
            [修改信息]   [确认通过]
                              │
                              v
                        [导出发布]
                              │
                        ┌─────┼─────┐
                        v     v     v
                    下载MP4 复制文案 跳转抖音
```

---

## 2. 逐屏详细设计

### Screen 01: 启动授权页

| 项目 | 内容 |
|------|------|
| **屏幕名称** | `launch` |
| **用户看到** | 品牌 Logo ("店铺视频助手") + 一句话 slogan "3 分钟出片，到店客流翻倍" + "微信快捷登录" 按钮 |
| **用户操作** | 点击 "微信快捷登录" 按钮 |
| **提交数据** | 无 (触发微信 `wx.login` 获取 code) |
| **系统反馈** | 静默授权, 无弹窗; 授权成功后自动跳转 |
| **跳转逻辑** | 已有店铺信息 -> `Screen 03 (首页)`; 无店铺信息 -> `Screen 02 (店铺信息)` |

**前端备注:**
- ⚠️ `wx.getUserProfile` 已于 2022 年废弃, 不可用
- 使用 `wx.login` 获取 code → 后端 `code2Session` 换 openid + session_key
- 头像/昵称不再由微信授权获取, 改为在 Screen 02 店铺信息页由商家自填
- 登录态用 token 存 `wx.setStorageSync`

---

### Screen 02: 店铺信息填写

| 项目 | 内容 |
|------|------|
| **屏幕名称** | `shop-setup` |
| **用户看到** | 标题 "完善店铺信息" + 表单字段 (见下) + "开始制作视频" 按钮 (底部固定) |
| **用户操作** | 逐项填写表单 -> 点击提交 |

**表单字段:**

| 字段名 | 字段 key | 类型 | 必填 | 说明 |
|--------|----------|------|------|------|
| 店铺名称 | `shop_name` | `string` | Y | 最大 30 字 |
| 业务类型 | `biz_type` | `enum` | Y | 单选: `hair` 美发 / `nail` 美甲 / `spa` SPA / `other` 其他 |
| 所在城市 | `city` | `string` | Y | 调用微信定位自动填充, 可手动修改; 用于标签推荐 |
| 店铺地址 | `address` | `string` | N | 详细地址, 用于视频水印 (可选) |
| 联系电话 | `phone` | `string` | Y | 手机号, 11 位校验 |
| 店铺 Logo | `logo_url` | `string (url)` | N | 上传图片, 压缩至 200x200, 用于视频片尾水印 |

**系统反馈:**
- 校验不通过: 对应字段下方红色提示文字
- 提交成功: `wx.showToast("保存成功")` -> 自动跳转

**跳转:** -> `Screen 03 (首页)`

**前端备注:**
- 城市字段: 先调用 `wx.getLocation` + 逆地理编码自动填充, 失败时展示手动输入
- Logo 上传: `wx.chooseImage` -> 压缩 -> 上传 OSS -> 回填 url
- 所有信息后续可在 "我的 > 店铺设置" 修改

---

### Screen 03: 首页 / 任务列表

| 项目 | 内容 |
|------|------|
| **屏幕名称** | `home` |
| **用户看到** | 顶部: 店铺名 + 头像; 中部: 任务卡片列表 (按创建时间倒序); 底部: TabBar [首页 / 历史 / 我的]; 空状态: 插画 + "还没有视频, 点击下方按钮开始" |
| **用户操作** | (1) 点击 "+" 悬浮按钮 -> 创建新任务; (2) 点击任务卡片 -> 进入对应状态的详情页; (3) 切换底部 Tab |

**任务卡片展示字段:**

| 展示项 | 来源字段 | 说明 |
|--------|----------|------|
| 封面缩略图 | `task.cover_url` | 未生成前显示第一个素材首帧 |
| 任务标题 | `task.title` | 最多显示 1 行, 超出省略 |
| 模板类型 | `task.template_name` | 标签样式, 如 "发型对比" |
| 状态标签 | `task.status` | 见状态机定义 (Section 4) |
| 创建时间 | `task.created_at` | 相对时间: "3 分钟前" / "昨天" |

**跳转逻辑 (点击卡片):**
| 任务状态 | 跳转目标 |
|----------|----------|
| `draft` | `Screen 05 (上传素材)` |
| `processing` | `Screen 07 (等待处理)` |
| `review` | `Screen 08 (审核成片)` |
| `approved` | `Screen 10 (导出发布)` |
| `exported` | `Screen 10 (导出发布)` |
| `failed` | `Screen 07 (等待处理)` 显示失败原因 + 重试按钮 |

---

### Screen 04: 选择模板

| 项目 | 内容 |
|------|------|
| **屏幕名称** | `template-select` |
| **用户看到** | 顶部: 分类 Tab (全部 / 发型改造 / 美甲展示 / SPA 氛围 / 活动促销); 主体: 模板卡片网格 (2 列); 每张卡片: 预览封面 + 模板名 + 时长标签 + "使用" 按钮 |
| **用户操作** | (1) 切换分类 Tab 筛选; (2) 点击卡片预览 (全屏播放示例视频); (3) 点击 "使用" 选定模板 |

**模板卡片字段:**

| 展示项 | 来源字段 | 说明 |
|--------|----------|------|
| 预览封面 | `template.cover_url` | 16:9 竖版缩略图 |
| 模板名称 | `template.name` | 如 "发型改造前后对比" |
| 预估时长 | `template.duration_range` | 如 "15-30 秒" |
| 目标时长 | `template.target_duration` | 整数秒, 如 `30`; 混剪引擎据此控制成片总时长 |
| 素材要求 | `template.slot_count` | 如 "需要 3-5 段视频" |
| 分类标签 | `template.category` | `hair_compare` / `nail_showcase` / `spa_mood` / `promo` |

**提交数据:** 选中的 `template_id: string`

**系统反馈:** 选中后底部出现 "下一步: 上传素材" 按钮 (带模板名回显)

**跳转:** -> `Screen 05 (上传素材)`

**美业模板示例:**

| 模板名称 | category | slot_count | 说明 |
|----------|----------|------------|------|
| 发型改造前后对比 | `hair_compare` | 2-4 段 | 前后对比分屏, BGM 节奏卡点 |
| 美甲作品合集 | `nail_showcase` | 3-6 段 | 多图轮播 + 放大特写 + 标注色号 |
| SPA 环境氛围 | `spa_mood` | 2-3 段 | 慢镜头 + 暖色调滤镜 + 舒缓 BGM |
| 新客优惠活动 | `promo` | 1-3 段 | 大字幕 + 价格标注 + 倒计时动效 |
| 技师作品集 | `stylist_portfolio` | 3-5 段 | 带技师名字条 + 作品标注 |

---

### Screen 05: 上传素材

| 项目 | 内容 |
|------|------|
| **屏幕名称** | `upload-assets` |
| **用户看到** | 顶部: 步骤条 (1.模板 **2.素材** 3.信息 4.提交); 已选模板回显 (小卡片); 素材上传区: "视频素材" 区域 + "图片素材" 区域; 底部: "下一步" 按钮 |
| **用户操作** | (1) 点击 "+" 上传视频 (从相册选 / 现场拍摄); (2) 点击 "+" 上传图片; (3) 长按拖拽调整素材顺序; (4) 点击素材缩略图预览; (5) 点击 "x" 删除素材 |

**上传约束:**

| 素材类型 | 数量 | 单个大小 | 格式 | 说明 |
|----------|------|----------|------|------|
| 视频 | 2-8 个 | 最大 500MB | mp4 / mov | 建议竖屏 9:16; 横屏系统自动裁切 |
| 图片 | 0-5 张 | 最大 10MB | jpg / png | 产品图 / 价目图 / Logo; 可选 |

**提交数据:**

| 字段 | key | 类型 | 说明 |
|------|-----|------|------|
| 视频素材列表 | `video_assets` | `Array<{ asset_id, url, duration, width, height, order }>` | 上传后由 OSS 返回 url |
| 图片素材列表 | `image_assets` | `Array<{ asset_id, url, width, height, order }>` | 同上 |
| 素材排序 | (含在上述数组的 `order` 字段) | `number` | 用户拖拽确定 |

**系统反馈:**
- 上传中: 每个素材显示上传进度条 (百分比)
- 上传失败: 素材缩略图右上角红色感叹号 + 点击重试
- 视频过大: toast "视频超过 200MB, 请压缩后上传"
- 数量不足: "下一步" 按钮灰色不可点 + 提示 "至少上传 N 段视频"(N 取自模板 slot_count 最小值)

**跳转:** -> `Screen 06 (填写信息)`

**前端备注:**
- 使用 `wx.chooseMedia` (type: ['video']) 选择视频
- 上传走分片上传 (视频文件大), 断点续传
- 上传期间用户可继续添加其他素材 (并行上传)
- 素材列表本地暂存 `wx.setStorageSync`, 防止中途退出丢失

---

### Screen 06: 填写信息 / 标签

| 项目 | 内容 |
|------|------|
| **屏幕名称** | `task-info` |
| **用户看到** | 顶部: 步骤条 (1.模板 2.素材 **3.信息** 4.提交); 表单区域 (见下); 底部: "预览并提交" 按钮 |
| **用户操作** | 填写表单 -> 点击底部按钮 |

**表单字段:**

| 字段名 | key | 类型 | 必填 | 说明 |
|--------|-----|------|------|------|
| 视频标题 | `title` | `string` | Y | 最大 30 字; 占位符: "输入吸引人的标题, 如: 黑长直改造慵懒卷" |
| 视频描述 | `description` | `string` | N | 最大 200 字; 用于生成发布文案 |
| 核心卖点 | `selling_points` | `Array<string>` | Y (至少 1 条) | 最多 3 条, 每条最大 20 字; 如 "烫染套餐 199 元" "总监亲自操刀" |
| 标签 | `tags` | `Array<string>` | Y (至少 3 个) | 最多 10 个; 带 "#" 前缀; 支持手动输入 + 系统推荐 |
| BGM 偏好 | `bgm_preference` | `enum` | N | `auto` 自动匹配 (默认) / `energetic` 动感 / `chill` 舒缓 / `trendy` 热门流行 |
| 片尾信息 | `outro_text` | `string` | N | 默认自动填充店铺名 + 电话; 可修改; 最大 50 字 |

**标签自动推荐逻辑:**
系统根据 `biz_type` + `city` + `template.category` 自动生成推荐标签, 用户点击即添加:

| 条件 | 推荐标签示例 |
|------|-------------|
| biz_type = hair | #美发 #发型设计 #发型改造 #染发 #烫发 |
| biz_type = nail | #美甲 #美甲款式 #手绘美甲 #甲片 |
| biz_type = spa | #SPA #养生 #肩颈按摩 #放松 |
| city = 上海 | #上海美发 #上海探店 #魔都美业 |
| template = promo | #优惠活动 #新客福利 #限时特惠 |

标签展示: 推荐标签以气泡形式展示在输入框下方, 已选中的高亮, 点击切换选中/取消。

**系统反馈:**
- 标题为空: 字段高亮 + "请输入视频标题"
- 标签不足: "请至少选择 3 个标签"
- 卖点超长: 实时字数计数, 超出部分标红

**跳转:** -> `Screen 06b (提交确认弹窗)`

---

### Screen 06b: 提交确认 (半屏弹窗)

| 项目 | 内容 |
|------|------|
| **屏幕名称** | `task-confirm` (半屏弹窗, 非独立页面) |
| **用户看到** | 半屏弹窗, 内容: 模板名称 + 素材数量 + 标题 + 标签列表 + 预估处理时间 (如 "约 3-5 分钟") |
| **用户操作** | (1) "确认提交" 按钮; (2) "返回修改" 文字链接 |

**提交数据 (完整任务创建请求):**

```
POST /api/task/create

{
  "template_id": "string",
  "title": "string",
  "description": "string",
  "selling_points": ["string"],
  "tags": ["string"],
  "bgm_preference": "auto|energetic|chill|trendy",
  "outro_text": "string",
  "video_assets": [
    {
      "asset_id": "string",
      "url": "string",
      "duration": "number (秒)",
      "width": "number",
      "height": "number",
      "order": "number"
    }
  ],
  "image_assets": [
    {
      "asset_id": "string",
      "url": "string",
      "width": "number",
      "height": "number",
      "order": "number"
    }
  ]
}
```

**系统反馈:**
- 提交成功: toast "任务已提交, 正在为您制作视频" -> 自动跳转
- 提交失败: toast "提交失败, 请重试" + 按钮恢复可点击

**跳转:** -> `Screen 07 (等待处理)`

---

### Screen 07: 等待处理 / 进度

| 项目 | 内容 |
|------|------|
| **屏幕名称** | `task-progress` |
| **用户看到** | 顶部: 任务标题; 中部: 环形进度动画 + 当前步骤文案 + 预估剩余时间; 下方: 步骤列表 (带状态); 底部: "返回首页" 按钮 |
| **用户操作** | (1) 等待 (页面自动轮询刷新); (2) 点击 "返回首页" 回到任务列表; (3) 失败状态下点击 "重新处理" |

**处理步骤展示:**

| 步骤 | 显示文案 | 对应后端阶段 |
|------|----------|-------------|
| 1 | 素材分析中... | `analyzing` |
| 2 | 智能剪辑中... | `editing` |
| 3 | 特效渲染中... | `rendering` |
| 4 | 生成成片中... | `compositing` |
| 5 | 完成 | `done` |

**轮询机制:**
- 接口: `GET /api/task/{task_id}/progress`
- 返回: `{ status, step, progress_percent, estimated_remaining_seconds }`
- 轮询间隔: 3 秒
- 页面在后台时暂停轮询, 回到前台时立即请求一次
- 处理完成: 自动跳转到审核页

**失败状态:**
- 显示: 红色感叹号 + 失败原因文案 (如 "素材格式不支持, 请更换后重试")
- 操作: "重新处理" 按钮 (保留原素材, 重新提交任务) / "返回修改" (回到素材上传页)

**跳转:**
- 处理完成 -> `Screen 08 (审核成片)`
- 返回首页 -> `Screen 03 (首页)`
- 重新处理 -> 触发 `POST /api/task/{task_id}/retry` -> 留在本页

**前端备注:**
- 用户离开此页面后, 处理完成时发送微信服务通知 (模板消息): "您的视频已制作完成, 点击查看"
- 通知点击跳转到 `Screen 08`

---

### Screen 08: 审核成片

| 项目 | 内容 |
|------|------|
| **屏幕名称** | `review-video` |
| **用户看到** | 顶部: 全屏视频播放器 (竖屏, 带播放/暂停/进度条); 视频下方: 可编辑字段区域; 底部固定: "通过并导出" 主按钮 + "重新生成" 次按钮 |
| **用户操作** | (1) 播放/暂停视频预览; (2) 修改标题; (3) 修改标签; (4) 更换封面; (5) 点击 "通过" 或 "重新生成" |

**可编辑字段:**

| 字段名 | key | 类型 | 说明 |
|--------|-----|------|------|
| 视频标题 | `title` | `string` | 回显创建时填写的标题, 可修改 |
| 标签 | `tags` | `Array<string>` | 回显已选标签, 可增删 |
| 封面图 | `cover_url` | `string (url)` | 默认系统截取; 点击 "更换封面" 进入封面选择 |
| 发布文案 | `copy_text` | `string` | 系统自动生成 (由后端 n8n 工作流的 LLM 节点根据标题+卖点+标签生成, 存入 Task.copy_text); 商家可在此页编辑; 最大 500 字 |

**封面选择 (Screen 08b, 半屏弹窗):**
- 系统自动截取 6 张关键帧作为候选
- 用户也可从素材图片中选择
- 选中后回到审核页, 封面更新

**按钮行为:**

| 按钮 | 动作 |
|------|------|
| 通过并导出 | `POST /api/task/{task_id}/approve` body: `{ title, tags, cover_url, copy_text }` -> 跳转导出页 |
| 重新生成 | 弹出确认弹窗 "重新生成将覆盖当前视频, 确定?" -> 确定后 `POST /api/task/{task_id}/regenerate` -> 跳转回进度页 |

**跳转:**
- 通过 -> `Screen 10 (导出发布)`
- 重新生成 -> `Screen 07 (等待处理)`

---

### Screen 10: 导出发布

| 项目 | 内容 |
|------|------|
| **屏幕名称** | `export` |
| **用户看到** | 顶部: 视频封面缩略图 + 标题; 三个操作卡片 (纵向排列): (1) 下载视频 (2) 复制文案 (3) 复制标签; 底部: "去抖音发布" 按钮 (大, 醒目); 最底部: "返回首页" 文字链 |
| **用户操作** | 依次完成三步操作, 然后跳转抖音 |

**三步操作详情:**

| 步骤 | 操作 | 技术实现 | 反馈 |
|------|------|----------|------|
| 1. 下载视频 | 点击 "保存到相册" | `wx.saveVideoToPhotosAlbum({ filePath })` | toast "视频已保存到相册"; 按钮变为 "已保存" (勾选图标, 置灰) |
| 2. 复制文案 | 点击 "复制发布文案" | `wx.setClipboardData({ data: copy_text })` | toast "文案已复制"; 按钮变为 "已复制" |
| 3. 复制标签 | 点击 "复制标签" | `wx.setClipboardData({ data: tags.join(' ') })` | toast "标签已复制"; 按钮变为 "已复制" |

**"去抖音发布" 按钮:**
- 技术: 尝试 URL Scheme 唤起抖音 App (`snssdk1128://`); 此 Scheme 可能失效, 需要运行时验证
- 唤起失败 (兜底): toast "请手动打开抖音 App, 选择相册中刚保存的视频, 粘贴已复制的文案和标签即可发布"
- 唤起成功: 用户离开小程序, 在抖音完成发布
- ⚠️ 抖音多次更换 Scheme, MVP 不强依赖唤起成功; 核心体验是"保存到相册+复制文案"三步流程

**导出后数据记录:**
- 触发 `POST /api/task/{task_id}/export` 记录导出时间
- 状态变更: `approved` -> `exported`

**跳转:**
- 返回首页 -> `Screen 03`
- 去抖音发布 -> 离开小程序

**前端备注:**
- 下载视频前需检查相册权限 `wx.authorize({ scope: 'scope.writePhotosAlbum' })`
- 视频文件先缓存到本地 `wx.downloadFile` 再保存
- 文案格式示例: "{title}\n\n{description}\n\n{selling_points 逐条换行}\n\n到店咨询: {phone}"
- 标签格式: "#美发 #发型改造 #上海美发" (空格分隔)

---

### Screen 11: 历史记录

| 项目 | 内容 |
|------|------|
| **屏幕名称** | `history` |
| **用户看到** | 底部 TabBar 第二个 Tab; 视频卡片列表 (仅显示 `approved` / `exported` 状态); 每张卡片: 封面 + 标题 + 导出时间 + 数据指标; 顶部: 按月份分组 |
| **用户操作** | (1) 点击卡片 -> 进入详情; (2) 点击 "填报数据" 按钮 |

**卡片展示字段:**

| 展示项 | 来源字段 | 说明 |
|--------|----------|------|
| 封面 | `video.cover_url` | 圆角缩略图 |
| 标题 | `video.title` | 单行省略 |
| 导出时间 | `video.exported_at` | "5月18日 导出" |
| 播放量 | `video.stats.play_count` | 商家手动填报; 未填报显示 "--" |
| 点赞数 | `video.stats.like_count` | 同上 |

**点击卡片进入详情:**
- 展示完整视频 (可播放) + 所有信息 (标题/文案/标签)
- 操作: 重新导出 (回到 Screen 10) / 填报数据 / 删除任务

**跳转:** 卡片点击 -> `Screen 12 (数据填报)` 或 `Screen 10 (导出发布, 重新导出)`

---

### Screen 12: 数据填报

| 项目 | 内容 |
|------|------|
| **屏幕名称** | `stats-report` |
| **用户看到** | 顶部: 视频封面 + 标题 (只读); 表单区域: 数据字段; 底部: "保存" 按钮 |
| **用户操作** | 填写在抖音上的实际数据 -> 保存 |

**表单字段:**

| 字段名 | key | 类型 | 说明 |
|--------|-----|------|------|
| 播放量 | `play_count` | `number` | 正整数, 手动输入 |
| 点赞数 | `like_count` | `number` | 正整数, 手动输入 |
| 评论数 | `comment_count` | `number` | 正整数, 手动输入 |
| 转发数 | `share_count` | `number` | 正整数, 手动输入 |
| 新增到店 | `visit_count` | `number` | 正整数, 可选; 商家估算因视频到店人数 |
| 数据截图 | `stats_screenshot_url` | `string (url)` | 可选; 上传抖音后台数据截图作为凭证 |
| 填报日期 | `report_date` | `date` | 默认当天, 可修改 |

**提交:** `POST /api/task/{task_id}/stats` body: 上述字段

**系统反馈:** toast "数据已保存" -> 返回历史列表

---

## 3. 数据模型

### 3.1 Shop (店铺)

```
Shop {
  shop_id        : string (UUID)        // 主键
  openid         : string               // 微信 openid, 唯一
  shop_name      : string               // 店铺名称, max 30
  biz_type       : enum                 // hair | nail | spa | other
  city           : string               // 所在城市
  address        : string?              // 详细地址
  phone          : string               // 联系电话
  logo_url       : string?              // 店铺 Logo URL
  created_at     : datetime             // 创建时间
  updated_at     : datetime             // 最后更新
}
```

### 3.2 Template (模板)

```
Template {
  template_id    : string (UUID)        // 主键
  name           : string               // 模板名称, 如 "发型改造前后对比"
  category       : enum                 // hair_compare | nail_showcase | spa_mood | promo | stylist_portfolio
  cover_url      : string               // 封面预览图 URL
  preview_url    : string               // 示例视频 URL
  duration_range : string               // 预估时长范围, 如 "15-30"
  target_duration: number               // 目标成片时长 (秒), 混剪引擎据此截断; 如 30
  slot_count_min : number               // 最少素材数
  slot_count_max : number               // 最多素材数
  slot_desc      : string               // 素材要求描述, 如 "需要 2 段改造前 + 2 段改造后视频"
  bgm_list       : Array<string>        // 可选 BGM ID 列表
  is_active      : boolean              // 是否上架
  sort_order     : number               // 排序权重
  created_at     : datetime
}
```

### 3.3 Task (任务)

```
Task {
  task_id              : string (UUID)        // 主键
  shop_id              : string (FK -> Shop)  // 所属店铺
  template_id          : string (FK -> Template)

  // -- 用户填写 --
  title                : string               // 视频标题, max 30
  description          : string?              // 视频描述, max 200
  selling_points       : Array<string>        // 核心卖点, 1-3 条
  tags                 : Array<string>        // 标签, 3-10 个
  bgm_preference       : enum                // auto | energetic | chill | trendy
  outro_text           : string?              // 片尾文字

  // -- 素材 --
  video_assets         : Array<Asset>         // 视频素材
  image_assets         : Array<Asset>         // 图片素材

  // -- 系统生成 --
  status               : enum                // 见状态机
  progress_step        : enum?               // analyzing | editing | rendering | compositing | done
  progress_percent     : number?             // 0-100
  estimated_seconds    : number?             // 预估剩余秒数
  output_video_url     : string?             // 成片视频 URL
  cover_url            : string?             // 封面图 URL
  cover_candidates     : Array<string>?      // 系统截取的 6 张候选封面 URL
  copy_text            : string?             // 自动生成的发布文案
  fail_reason          : string?             // 失败原因

  // -- 时间戳 --
  created_at           : datetime
  submitted_at         : datetime?           // 提交处理时间
  completed_at         : datetime?           // 处理完成时间
  approved_at          : datetime?           // 审核通过时间
  exported_at          : datetime?           // 导出时间
}
```

### 3.4 Asset (素材)

```
Asset {
  asset_id       : string (UUID)
  task_id        : string (FK -> Task)
  type           : enum                 // video | image
  url            : string               // OSS 地址
  duration       : number?              // 仅视频, 秒
  width          : number               // 像素
  height         : number               // 像素
  file_size      : number               // 字节
  order          : number               // 排序序号
  uploaded_at    : datetime
}
```

### 3.5 VideoStats (数据填报)

```
VideoStats {
  stats_id              : string (UUID)
  task_id               : string (FK -> Task)
  play_count            : number?
  like_count            : number?
  comment_count         : number?
  share_count           : number?
  visit_count           : number?             // 估算到店数
  stats_screenshot_url  : string?             // 数据截图
  report_date           : date                // 填报对应日期
  created_at            : datetime
}
```

---

## 4. 状态机

### 4.1 Task 状态流转

```
                  创建任务 (选模板)
                        │
                        v
                    [ draft ]
                        │
                 提交 (素材+信息齐全)
                        │
                        v
                  [ processing ]
                   │          │
              完成成功     处理失败
                   │          │
                   v          v
              [ review ]  [ failed ]
                   │          │
              ┌────┤      重新处理
              │    │          │
          重新生成  审核通过    │
              │    │          │
              │    v     ┌────┘
              │ [ approved ]
              │    │
              │  导出操作
              │    │
              │    v
              │ [ exported ]
              │
              └──> (回到 processing)
```

### 4.2 状态定义

| 状态 | 值 | 含义 | 用户可见文案 | 颜色 |
|------|----|------|-------------|------|
| 草稿 | `draft` | 任务已创建但未提交 | "草稿" | 灰色 |
| 处理中 | `processing` | 后端正在混剪 | "制作中" | 蓝色 |
| 待审核 | `review` | 成片已生成, 等待商家确认 | "待审核" | 橙色 |
| 已通过 | `approved` | 商家确认成片, 可导出 | "可导出" | 绿色 |
| 已导出 | `exported` | 商家已下载/导出 | "已导出" | 绿色 (深) |
| 失败 | `failed` | 处理失败 | "处理失败" | 红色 |

### 4.3 状态转换触发条件

| 从 | 到 | 触发 | 接口 |
|----|----|------|------|
| (新建) | `draft` | 用户选择模板 | `POST /api/task/create` (仅 template_id) |
| `draft` | `processing` | 用户提交完整任务 | `POST /api/task/{id}/submit` |
| `processing` | `review` | 后端处理完成 | 后端回调, 非前端触发 |
| `processing` | `failed` | 后端处理失败 | 后端回调, 非前端触发 |
| `review` | `approved` | 用户审核通过 | `POST /api/task/{id}/approve` |
| `review` | `processing` | 用户要求重新生成 | `POST /api/task/{id}/regenerate` |
| `approved` | `exported` | 用户执行导出 | `POST /api/task/{id}/export` |
| `failed` | `processing` | 用户重试 | `POST /api/task/{id}/retry` |

---

## 5. API 接口清单 (前端视角)

| 方法 | 路径 | 说明 | 请求体要点 |
|------|------|------|-----------|
| POST | `/api/auth/login` | 微信登录 | `{ code }` -> `{ token, is_new_user }` |
| POST | `/api/shop/setup` | 创建/更新店铺 | Shop 全部字段 |
| GET | `/api/shop/me` | 获取当前店铺信息 | - |
| GET | `/api/template/list` | 获取模板列表 | query: `?category=hair_compare` |
| POST | `/api/asset/upload-token` | 获取 OSS 上传凭证 | `{ filename, content_type }` -> `{ upload_url, asset_id }` |
| POST | `/api/task/create` | 创建任务 (完整提交) | 见 Screen 06b |
| GET | `/api/task/list` | 获取任务列表 | query: `?status=review&page=1&size=20` |
| GET | `/api/task/{id}` | 获取任务详情 | - |
| GET | `/api/task/{id}/progress` | 轮询处理进度 | - -> `{ status, step, percent, est_seconds }` |
| POST | `/api/task/{id}/approve` | 审核通过 | `{ title, tags, cover_url, copy_text }` |
| POST | `/api/task/{id}/regenerate` | 重新生成 | - |
| POST | `/api/task/{id}/retry` | 失败重试 | - |
| POST | `/api/task/{id}/export` | 记录导出 | - |
| GET | `/api/task/{id}/download-url` | 获取视频下载链接 | - -> `{ url, expires_at }` |
| POST | `/api/task/{id}/stats` | 数据填报 | VideoStats 字段 |
| GET | `/api/tag/suggest` | 获取推荐标签 | query: `?biz_type=hair&city=上海&category=hair_compare` |

---

## 6. MVP 裁剪建议

### 第一版 (MVP) 保留: 6 个屏

| 优先级 | 屏幕 | 理由 |
|--------|------|------|
| P0 | Screen 01 启动授权 | 入口, 必须 |
| P0 | Screen 02 店铺信息 | 首次使用, 必须 |
| P0 | Screen 03 首页/任务列表 | 主界面, 必须 |
| P0 | Screen 04+05+06 创建流程 | 核心价值, 合并为一个长页面 (模板选择内嵌 + 上传 + 填信息一页到底, 减少跳转) |
| P0 | Screen 07 等待处理 | 核心流程, 必须 |
| P0 | Screen 08 审核成片 | 核心价值, "人在环中"的关键, 必须 |
| P0 | Screen 10 导出发布 | 核心流程终点, 必须 |

### 第一版 (MVP) 简化:

| 屏幕 | 简化策略 |
|------|----------|
| Screen 02 | 去掉 Logo 上传, 只保留名称 + 类型 + 城市 + 电话 |
| Screen 04 | 模板数量缩减到 4 个, 去掉分类 Tab, 直接平铺 |
| Screen 05 | 去掉图片上传, 只支持视频; 去掉拖拽排序, 按上传顺序 |
| Screen 06 | BGM 偏好去掉, 全部用 auto; 片尾信息去掉, 用默认值 |
| Screen 08 | 封面选择简化: 只提供系统默认封面, 不支持自选; 发布文案不可编辑 |

### 第一版 (MVP) 延后:

| 屏幕 | 延后理由 |
|------|----------|
| Screen 11 历史记录 | 首页任务列表已覆盖基本需求, 独立历史 Tab 延后 |
| Screen 12 数据填报 | 非核心流程, 二期再做 |
| 底部 TabBar "我的" | MVP 用顶部入口替代, 仅含 "店铺设置" 一个功能 |

### MVP 技术裁剪:

| 项目 | MVP 方案 | 完整版方案 |
|------|----------|-----------|
| 素材上传 | 微信云开发 `cloud.uploadFile` (无大小限制) 或后端分片 5MB/chunk | OSS 分片 + 断点续传 |
| 进度轮询 | HTTP 轮询 3s | WebSocket 推送 |
| 标签推荐 | 写死在前端的静态列表 | 后端动态推荐接口 |
| 模板预览 | 静态图 | 示例视频播放 |
| 服务通知 | 不发 | 微信模板消息通知 |

### MVP 模板初始化:

MVP 第一版硬编码 4 个模板到数据库, 不做后台管理界面:

| 模板 | template_id | target_duration |
|------|-------------|-----------------|
| 发型改造前后对比 | `tpl-hair-compare` | 30 |
| 美甲作品合集 | `tpl-nail-showcase` | 25 |
| SPA 环境氛围 | `tpl-spa-mood` | 20 |
| 新客优惠活动 | `tpl-promo` | 15 |

后续通过管理后台或 API 动态增删模板。设备端模板数据通过 OTA 随工作流一起更新。

---

## 附录 A: 页面路由表

| 路由 | 页面 | 文件路径建议 |
|------|------|-------------|
| `/pages/launch/index` | 启动授权 | Screen 01 |
| `/pages/shop-setup/index` | 店铺信息 | Screen 02 |
| `/pages/home/index` | 首页 | Screen 03 |
| `/pages/create/template` | 选模板 | Screen 04 |
| `/pages/create/upload` | 上传素材 | Screen 05 |
| `/pages/create/info` | 填写信息 | Screen 06 |
| `/pages/task/progress` | 等待处理 | Screen 07 |
| `/pages/task/review` | 审核成片 | Screen 08 |
| `/pages/task/export` | 导出发布 | Screen 10 |
| `/pages/history/index` | 历史记录 | Screen 11 |
| `/pages/history/stats` | 数据填报 | Screen 12 |
| `/pages/settings/index` | 店铺设置 | 我的 -> 店铺设置 |

## 附录 B: 微信 API 依赖清单

| API | 用途 | 所在屏幕 |
|-----|------|---------|
| `wx.login` | 获取登录 code | Screen 01 |
| `wx.getUserProfile` | 获取头像昵称 | Screen 01 |
| `wx.getLocation` | 自动定位城市 | Screen 02 |
| `wx.chooseImage` | 上传 Logo / 截图 | Screen 02, 12 |
| `wx.chooseMedia` | 选择视频素材 | Screen 05 |
| `wx.uploadFile` | 上传素材文件 | Screen 05 |
| `wx.downloadFile` | 下载成片视频 | Screen 10 |
| `wx.saveVideoToPhotosAlbum` | 保存到相册 | Screen 10 |
| `wx.setClipboardData` | 复制文案/标签 | Screen 10 |
| `wx.authorize` | 请求相册权限 | Screen 10 |
| `wx.showToast` | 各类操作反馈 | 全局 |
| `wx.setStorageSync` | 登录态 + 草稿暂存 | 全局 |
