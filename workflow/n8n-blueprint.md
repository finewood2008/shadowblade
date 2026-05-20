# 火花 - 美业自动化视频混剪工作流架构

> 半人马 AI 旗下 | 基于 n8n 自托管 + FastAPI Worker

---

## 1. 系统架构总览

```
 [商家小程序]
      |
      | POST /webhook/spark-video
      v
 [n8n Server :5678]
      |
      |--- HTTP Request ---> [FastAPI Worker :8000]
      |                         /generate-script
      |                         /generate-audio
      |                         /generate-subtitle
      |                         /mix-video
      |                         /generate-cover
      |
      |--- Wait (人工审核) ---> [小程序回调]
      |
      v
 [最终发布包输出]
```

### 组件说明

| 组件 | 技术栈 | 端口 | 职责 |
|------|--------|------|------|
| n8n Server | Node.js / Docker | 5678 | 工作流编排、状态管理、Webhook |
| FastAPI Worker | Python + FastAPI | 8000 | LLM文案/TTS/混剪/字幕/封面 |
| 商家小程序 | 微信小程序 | - | 素材提交 + 审核确认 |

---

## 2. n8n 能力确认（基于 2025-2026 文档）

### 2.1 HTTP Request 节点
- 支持 GET / POST / PUT / PATCH / DELETE
- 支持 JSON body、form-data、multipart 上传
- 内置 Retry on Fail（可配置最大重试次数）
- 支持超时设置（毫秒级）
- 支持 Batching（限速控制）
- 参考: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest/

### 2.2 Wait 节点
- 支持三种恢复模式：定时、Webhook 回调、表单提交
- Webhook 模式下生成 `$execution.resumeUrl`，外部系统调用该 URL 即可恢复执行
- 暂停期间执行数据持久化到数据库，服务重启后自动恢复
- typeVersion 1.1，支持 `onError: continueErrorOutput`
- 参考: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.wait/

### 2.3 Webhook 节点
- 支持自定义路径和 HTTP 方法
- 自动生成 Test URL 和 Production URL
- 最大 payload 16MB（自托管可通过 `N8N_PAYLOAD_SIZE_MAX` 调整）
- 支持 Basic Auth / Header Auth / JWT Auth
- 参考: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/

### 2.4 文件处理
- HTTP Request 节点支持 binary data 下载/上传
- 通过 `responseFormat: file` 接收二进制文件
- 可在节点间传递 binary data（视频/音频/图片）

### 2.5 错误处理
- 节点级 Retry on Fail
- Error Trigger 节点 (`n8n-nodes-base.errorTrigger`) 捕获全局错误
- `onError: continueErrorOutput` 可将错误路由到备用分支
- 节点级 `continueOnFail` 选项

---

## 3. 完整 Workflow 节点设计

### 3.1 数据流概览

```
[1. Webhook 接收任务]
  -> [2. Respond to Webhook (立即回复202)]
  -> [3. 验证输入数据]
  -> [4. HTTP: POST /generate-script 生成文案]
  -> [5. HTTP: POST /generate-audio 生成配音]
  -> [6. HTTP: POST /mix-video 视频混剪]
  -> [7. HTTP: POST /generate-subtitle 生成字幕]
  -> [8. HTTP: POST /generate-cover 生成封面]
  -> [9. 组装发布包]
  -> [10. HTTP: 推送审核通知到小程序后端]
  -> [11. Wait: 等待商家审核回调]
  -> [12. 判断审核结果]
       |-- 通过 -> [13. 输出最终发布包]
       |-- 修改 -> [回到步骤4重新生成]
```

---

### 3.2 节点详细设计

#### 节点 1: Webhook - 接收任务

| 属性 | 值 |
|------|-----|
| n8n 节点类型 | `n8n-nodes-base.webhook` |
| typeVersion | 2 |
| HTTP Method | POST |
| Path | `spark-video` |
| Response Mode | `responseNode`（由下游 Respond to Webhook 节点响应） |
| Authentication | Header Auth（`X-API-Key`） |

**输入数据格式（小程序 POST body）：**
```json
{
  "task_id": "task_20260520_001",
  "shop_name": "艾美丽美发沙龙",
  "service_type": "hair_coloring",
  "selling_points": ["日系挂耳染", "不伤发质", "总监亲自操刀"],
  "video_urls": [
    "https://oss.example.com/素材1.mp4",
    "https://oss.example.com/素材2.mp4",
    "https://oss.example.com/素材3.mp4"
  ],
  "callback_url": "https://miniapp-api.example.com/spark/callback",
  "style_preference": "trendy",
  "target_duration": 30
}
```

**输出：** 透传上述 JSON 到后续节点

**错误处理：** Webhook 自身不会失败；输入校验在下游节点处理

**预估耗时：** <100ms

---

#### 节点 2: Respond to Webhook - 立即回复

| 属性 | 值 |
|------|-----|
| n8n 节点类型 | `n8n-nodes-base.respondToWebhook` |
| typeVersion | 1.1 |
| respondWith | `json` |
| responseCode | 202 |

**输出 body：**
```json
{
  "status": "accepted",
  "task_id": "{{ $json.body.task_id }}",
  "message": "任务已接收，处理中"
}
```

**设计理由：** 视频混剪是长流程（3-5分钟），必须先回复 202 Accepted，避免小程序端超时。

**预估耗时：** <50ms

---

#### 节点 3: IF - 验证输入数据

| 属性 | 值 |
|------|-----|
| n8n 节点类型 | `n8n-nodes-base.if` |
| typeVersion | 2 |
| 条件 | `video_urls` 数组长度 >= 1 且 `shop_name` 非空 |

**True 分支：** 继续正常流程
**False 分支：** 连接到错误通知节点（可选扩展）

**预估耗时：** <10ms

---

#### 节点 4: HTTP Request - 生成文案

| 属性 | 值 |
|------|-----|
| n8n 节点类型 | `n8n-nodes-base.httpRequest` |
| typeVersion | 4.2 |
| Method | POST |
| URL | `http://localhost:8000/generate-script` |
| Body Type | JSON |
| Timeout | 30000ms |
| Retry on Fail | Yes, max 2 |

**请求 body：**
```json
{
  "task_id": "{{ task_id }}",
  "shop_name": "{{ shop_name }}",
  "service_type": "{{ service_type }}",
  "selling_points": ["日系挂耳染", "不伤发质"],
  "style_preference": "trendy",
  "target_duration": 30
}
```

**响应格式：**
```json
{
  "task_id": "task_20260520_001",
  "script": "走进艾美丽，遇见最美的自己...",
  "hashtags": ["#日系挂耳染", "#不伤发质", "#总监操刀"],
  "title": "这家店的挂耳染绝了"
}
```

**错误处理：** Retry on Fail x2，间隔 5s；失败后走 error output

**预估耗时：** 5-15s（取决于 LLM 响应速度）

---

#### 节点 5: HTTP Request - 生成配音

| 属性 | 值 |
|------|-----|
| n8n 节点类型 | `n8n-nodes-base.httpRequest` |
| typeVersion | 4.2 |
| Method | POST |
| URL | `http://localhost:8000/generate-audio` |
| Body Type | JSON |
| Timeout | 60000ms |
| Retry on Fail | Yes, max 2 |

**请求 body：**
```json
{
  "task_id": "{{ task_id }}",
  "script": "{{ 上一节点输出的 script }}"
}
```

**响应格式：**
```json
{
  "task_id": "task_20260520_001",
  "audio_url": "http://localhost:8000/files/task_20260520_001/voiceover.mp3",
  "duration_seconds": 28.5
}
```

**错误处理：** Retry on Fail x2；TTS 服务偶尔超时，timeout 设置较长

**预估耗时：** 10-30s

---

#### 节点 6: HTTP Request - 视频混剪

| 属性 | 值 |
|------|-----|
| n8n 节点类型 | `n8n-nodes-base.httpRequest` |
| typeVersion | 4.2 |
| Method | POST |
| URL | `http://localhost:8000/mix-video` |
| Body Type | JSON |
| Timeout | 300000ms（5分钟） |
| Retry on Fail | Yes, max 1 |

**请求 body：**
```json
{
  "task_id": "{{ task_id }}",
  "video_urls": ["url1", "url2", "url3"],
  "audio_url": "{{ audio_url }}",
  "script": "{{ script }}",
  "target_duration": 30
}
```

**响应格式：**
```json
{
  "task_id": "task_20260520_001",
  "video_url": "http://localhost:8000/files/task_20260520_001/mixed.mp4",
  "actual_duration": 29.8
}
```

**错误处理：** 仅重试 1 次（视频处理耗时长）；失败触发错误通知

**预估耗时：** 60-180s（核心瓶颈节点）

---

#### 节点 7: HTTP Request - 生成字幕

| 属性 | 值 |
|------|-----|
| n8n 节点类型 | `n8n-nodes-base.httpRequest` |
| typeVersion | 4.2 |
| Method | POST |
| URL | `http://localhost:8000/generate-subtitle` |
| Body Type | JSON |
| Timeout | 120000ms |
| Retry on Fail | Yes, max 2 |

**请求 body：**
```json
{
  "task_id": "{{ task_id }}",
  "video_url": "{{ mixed video url }}",
  "script": "{{ script }}"
}
```

**响应格式：**
```json
{
  "task_id": "task_20260520_001",
  "video_with_subtitle_url": "http://localhost:8000/files/task_20260520_001/subtitled.mp4",
  "srt_url": "http://localhost:8000/files/task_20260520_001/subtitle.srt"
}
```

**预估耗时：** 30-60s

---

#### 节点 8: HTTP Request - 生成封面

| 属性 | 值 |
|------|-----|
| n8n 节点类型 | `n8n-nodes-base.httpRequest` |
| typeVersion | 4.2 |
| Method | POST |
| URL | `http://localhost:8000/generate-cover` |
| Body Type | JSON |
| Timeout | 60000ms |
| Retry on Fail | Yes, max 2 |

**请求 body：**
```json
{
  "task_id": "{{ task_id }}",
  "video_url": "{{ subtitled video url }}",
  "title": "{{ title }}",
  "shop_name": "{{ shop_name }}"
}
```

**响应格式：**
```json
{
  "task_id": "task_20260520_001",
  "cover_url": "http://localhost:8000/files/task_20260520_001/cover.jpg"
}
```

**预估耗时：** 5-15s

---

#### 节点 9: Set - 组装发布包

| 属性 | 值 |
|------|-----|
| n8n 节点类型 | `n8n-nodes-base.set` |
| typeVersion | 3.4 |

**输出数据结构：**
```json
{
  "task_id": "task_20260520_001",
  "shop_name": "艾美丽美发沙龙",
  "publish_package": {
    "video_url": "http://localhost:8000/files/.../subtitled.mp4",
    "cover_url": "http://localhost:8000/files/.../cover.jpg",
    "title": "这家店的挂耳染绝了",
    "script": "走进艾美丽，遇见最美的自己...",
    "hashtags": ["#日系挂耳染", "#不伤发质"],
    "duration": 29.8
  },
  "status": "pending_review",
  "review_url": "{{ $execution.resumeUrl }}"
}
```

**预估耗时：** <10ms

---

#### 节点 10: HTTP Request - 推送审核通知

| 属性 | 值 |
|------|-----|
| n8n 节点类型 | `n8n-nodes-base.httpRequest` |
| typeVersion | 4.2 |
| Method | POST |
| URL | `{{ $json.body.callback_url }}` (来自节点1的原始输入) |

**请求 body：**
```json
{
  "task_id": "{{ task_id }}",
  "status": "pending_review",
  "publish_package": { "...上述发布包..." },
  "review_callback_url": "{{ $execution.resumeUrl }}"
}
```

**说明：** 将 `$execution.resumeUrl` 发送给小程序后端，商家审核后小程序后端 POST 该 URL 以恢复工作流。

**预估耗时：** <2s

---

#### 节点 11: Wait - 等待商家审核

| 属性 | 值 |
|------|-----|
| n8n 节点类型 | `n8n-nodes-base.wait` |
| typeVersion | 1.1 |
| Resume | `webhook` |
| HTTP Method | POST |
| Limit Wait Time | 可选，如 72 小时 |

**恢复条件：** 小程序后端 POST 到 `$execution.resumeUrl`

**回调 body 格式：**
```json
{
  "task_id": "task_20260520_001",
  "decision": "approved",
  "modifications": null
}
```
或
```json
{
  "task_id": "task_20260520_001",
  "decision": "revision_requested",
  "modifications": {
    "new_selling_points": ["加上优惠信息"],
    "note": "文案再活泼一点"
  }
}
```

**预估耗时：** 数分钟到数天（取决于商家响应速度）

---

#### 节点 12: IF - 判断审核结果

| 属性 | 值 |
|------|-----|
| n8n 节点类型 | `n8n-nodes-base.if` |
| typeVersion | 2 |
| 条件 | `decision === "approved"` |

**True 分支：** 输出最终发布包（节点 13）
**False 分支：** 可扩展为回到步骤 4 重新生成（当前版本直接输出修改建议）

**预估耗时：** <10ms

---

#### 节点 13: Set - 输出最终发布包

| 属性 | 值 |
|------|-----|
| n8n 节点类型 | `n8n-nodes-base.set` |
| typeVersion | 3.4 |

**最终输出：**
```json
{
  "task_id": "task_20260520_001",
  "status": "approved",
  "final_package": {
    "video_url": "...",
    "cover_url": "...",
    "title": "...",
    "script": "...",
    "hashtags": ["..."],
    "duration": 29.8
  },
  "approved_at": "2026-05-20T15:30:00Z"
}
```

---

## 4. 端到端时间预估

| 阶段 | 耗时 |
|------|------|
| Webhook 接收 + 验证 | <1s |
| 文案生成 (LLM) | 5-15s |
| TTS 配音 | 10-30s |
| 视频混剪 | 60-180s |
| 字幕生成 | 30-60s |
| 封面生成 | 5-15s |
| 组装 + 推送审核通知 | <3s |
| **自动化处理总计** | **约 2-5 分钟** |
| 商家审核（人工） | 数分钟到数天 |

---

## 5. 错误处理策略

### 5.1 节点级策略

| 节点 | 重试次数 | 重试间隔 | 超时 | 失败处理 |
|------|----------|----------|------|----------|
| 生成文案 | 2 | 5s | 30s | 走 error output |
| 生成配音 | 2 | 5s | 60s | 走 error output |
| 视频混剪 | 1 | 10s | 300s | 走 error output |
| 生成字幕 | 2 | 5s | 120s | 走 error output |
| 生成封面 | 2 | 5s | 60s | 走 error output |
| 推送审核 | 3 | 5s | 10s | 走 error output |

### 5.2 全局错误处理

工作流配置 Error Trigger 节点，任何节点失败后：
1. 记录错误日志（包含 task_id + 失败节点 + 错误信息）
2. 通过 HTTP Request 回调小程序后端，通知任务失败
3. 回调 body: `{ "task_id": "...", "status": "failed", "error": "..." }`

---

## 6. n8n 部署方案（Windows 本地）

### 6.1 方案 A: npm 安装（推荐开发/测试）

```powershell
# 1. 确保已安装 Node.js 18+ LTS
node --version

# 2. 全局安装 n8n
npm install -g n8n

# 3. 启动 n8n
n8n start

# 或指定端口
N8N_PORT=5678 n8n start
```

- 数据存储位置: `%USERPROFILE%\.n8n\`
- 包含 SQLite 数据库（默认）、workflow 文件、credentials
- 适合开发测试，启动快

### 6.2 方案 B: Docker Desktop（推荐生产环境）

```yaml
# docker-compose.yml
version: '3.8'
services:
  n8n:
    image: n8nio/n8n:latest
    ports:
      - "5678:5678"
    environment:
      - N8N_PAYLOAD_SIZE_MAX=50        # MB，适配视频大payload
      - WEBHOOK_URL=http://localhost:5678
      - N8N_DIAGNOSTICS_ENABLED=false
      - GENERIC_TIMEZONE=Asia/Shanghai
    volumes:
      - n8n_data:/home/node/.n8n
    restart: unless-stopped
    extra_hosts:
      - "host.docker.internal:host-gateway"

volumes:
  n8n_data:
```

```powershell
# 启动
docker compose up -d

# 查看日志
docker compose logs -f
```

**注意：** Docker 内访问宿主机的 FastAPI Worker 需要用 `host.docker.internal:8000` 替代 `localhost:8000`。

### 6.3 数据持久化

| 方案 | 存储位置 | 备份方式 |
|------|----------|----------|
| npm | `%USERPROFILE%\.n8n\` | 直接拷贝文件夹 |
| Docker | named volume `n8n_data` | `docker cp` 或 volume backup |

关键文件：
- `database.sqlite` — workflow 定义 + 执行历史 + credential（加密）
- `config` — 配置文件

### 6.4 与 FastAPI Worker 通信

```
                    localhost 网络
 +-----------+                      +----------------+
 | n8n       | --HTTP Request-----> | FastAPI Worker  |
 | :5678     |   POST /mix-video    | :8000           |
 |           | <---JSON Response--- |                 |
 +-----------+                      +----------------+
```

- **npm 方式：** 直接用 `http://localhost:8000`，两者在同一网络命名空间
- **Docker 方式：** 用 `http://host.docker.internal:8000`，或者把 FastAPI 也放入同一 docker-compose network
- **文件共享：** FastAPI 生成的视频文件通过 HTTP URL 提供下载（`http://localhost:8000/files/...`），n8n 节点通过 HTTP Request 获取

### 6.5 Webhook 外网访问（小程序触发）

小程序后端需要能访问 n8n 的 Webhook URL。方案：

1. **内网穿透（开发）：** 使用 cloudflared tunnel 或 ngrok
   ```bash
   npx cloudflared tunnel --url http://localhost:5678
   ```

2. **公网部署（生产）：** 将 n8n 部署到云服务器，配置域名 + HTTPS

3. **反向代理：** Nginx 反代 n8n 的 `/webhook/` 路径

---

## 7. FastAPI Worker 接口规范

以下是 n8n 工作流所依赖的 FastAPI 接口定义。Worker 运行在 `localhost:8000`。

### POST /generate-script
生成视频文案和标签。

### POST /generate-audio
将文案转为 TTS 配音音频。

### POST /mix-video
核心混剪接口，将多段素材 + 配音合成为一段视频。

### POST /generate-subtitle
为混剪视频生成字幕并烧录。

### POST /generate-cover
从视频截取关键帧并生成封面图。

所有接口统一返回格式：
```json
{
  "task_id": "string",
  "status": "success | error",
  "data": { ... },
  "error": "string (仅失败时)"
}
```

---

## 8. 安全考量

1. **Webhook 认证：** 使用 Header Auth (`X-API-Key`) 防止未授权触发
2. **FastAPI Worker：** 仅监听 localhost，不暴露到公网
3. **文件访问：** 生成的视频文件通过带 task_id 的 URL 访问，可选加 token 校验
4. **n8n 账号：** 设置强密码，开启 2FA（如果部署到公网）
5. **数据清理：** 定期清理已完成任务的临时文件

---

## 9. 扩展路线

1. **批量任务：** 支持商家一次提交多个视频任务，n8n 使用 SplitInBatches 节点并行处理
2. **模板系统：** 预设美发/美甲/SPA 不同风格模板，在文案生成时选用
3. **数据统计：** 接入简单数据库记录任务完成率、平均耗时
4. **修改重试：** 商家要求修改时，保留已有素材，仅重新生成文案和混剪
5. **多 Worker 负载均衡：** 任务量增大后，部署多个 FastAPI Worker 实例
