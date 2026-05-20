# Huohua Worker -- MPP Services FastAPI 改造蓝图

> 火花视频混剪 Worker -- 基于 MoneyPrinterPlus services/ 的 FastAPI HTTP Worker 改造方案
> 版本: v0.1  |  2026-05-20

---

## 一、模块逐一判断

### 1. services/llm/ -- LLM 文案生成

| 文件 | 判断 | 说明 |
|---|---|---|
| `llm_service.py` | 直接复用 | 抽象基类 `MyLLMService`，定义 `generate_content()` 接口 + prompt 模板。不含 st 依赖。 |
| `llm_provider.py` | 直接复用 | 工厂函数 `get_llm_provider(name) -> MyLLMService`。不含 st 依赖。 |
| `openai_service.py` | 直接复用 | 纯 langchain_openai 调用，配置从 `my_config` 读。不含 st 依赖。 |
| `deepseek_service.py` | 直接复用 | 纯 openai SDK 调用。不含 st 依赖。 |
| `kimi_service.py` | 直接复用 | langchain Moonshot。不含 st 依赖。 |
| `ollama_service.py` | 直接复用 | langchain ChatOllama。不含 st 依赖。 |
| `tongyi_service.py` | 直接复用 | langchain Tongyi。不含 st 依赖。 |
| `azure_service.py` | 直接复用 | langchain AzureChatOpenAI。不含 st 依赖。 |
| `baichuan_service.py` | 直接复用 | langchain BaichuanLLM。不含 st 依赖。 |
| `baidu_qianfan_service.py` | 直接复用 | langchain QianfanLLMEndpoint。不含 st 依赖。 |

**改造量: 零。** 整个 llm/ 目录直接 import 即可。`get_llm_provider()` 返回的实例的 `generate_content(topic, prompt_template, language, length)` 就是纯函数。

---

### 2. services/audio/ -- TTS + 语音识别

#### 2.1 TTS（文字转语音）

| 文件 | 判断 | 说明 |
|---|---|---|
| `audio_service.py` | 直接复用 | 抽象基类，定义 `save_with_ssml(text, file_name, voice, rate)` 接口。不含 st。 |
| `azure_service.py` (audio) | 直接复用 | Azure TTS。`save_with_ssml()` 纯文件操作。`read_with_ssml()` 播放音频（worker 不需要）。不含 st。 |
| `alitts_service.py` | 直接复用 | 阿里 TTS。同上。不含 st。 |
| `tencent_tts_service.py` | 直接复用 | 腾讯 TTS。同上。不含 st。 |
| `chattts_service.py` | **需要改造** | 构造函数大量读 `st.session_state`（`refine_text`, `audio_seed`, `audio_speed` 等 10+ 个参数）。需改为构造函数参数传入。 |
| `gptsovits_service.py` | **需要改造** | 构造函数读 `st.session_state`（`audio_temperature`, `audio_speed`, `reference_audio` 等）。同上。 |
| `cosyvoice_service.py` | **需要改造** | 构造函数读 `st.session_state`（`audio_seed`, `audio_speed`, `reference_audio_file_path` 等）。同上。 |

**ChatTTS / GPTSoVITS / CosyVoice 改造策略:**
不动原文件。Worker 中新建一个 wrapper 工厂函数，接收 API 请求参数，构造 config dict 替代 `st.session_state`，然后 monkey-patch 或直接实例化服务对象。具体做法是在 worker 中定义 `create_local_tts_service(provider, params)` 函数。

#### 2.2 语音识别（ASR）

| 文件 | 判断 | 说明 |
|---|---|---|
| `faster_whisper_recognition_service.py` | 直接复用 | `process(audioFile, language)` 纯函数。不含 st。 |
| `sensevoice_whisper_recognition_service.py` | 直接复用 | `process(audioFile, language)` 纯函数。不含 st。 |
| `tencent_recognition_service.py` | 直接复用 | 同上（待确认，大概率不含 st）。 |
| `flash_recognizer.py` | 直接复用 | 辅助类。 |
| `generate-subtitles.py` | 扔掉 | 独立脚本，非 service。 |

---

### 3. services/captioning/ -- 字幕生成

| 文件 | 判断 | 说明 |
|---|---|---|
| `captioning_service.py` | **需要改造** | `generate_caption()` 函数通过 `st.session_state` 获取 `recognition_audio_type`, `audio_output_file`, `audio_language`。`add_subtitles()` 纯函数（已经参数化），直接复用。 |
| `common_captioning_service.py` | 直接复用 | `Captioning` 类核心逻辑。不直接用 st（间接通过 user_config_helper）。 |
| `caption_helper.py` | 直接复用 | 纯算法（字幕分行/时间戳计算）。不含 st。 |
| `helper.py` | 直接复用 | 工具函数（时间转换等）。 |
| `user_config_helper.py` | **需要改造** | `user_config_from_args()` 大量调用 `get_session_option()` 即 `st.session_state.get()`。需改为参数传入版本。 |

**改造策略:**
Worker 中新建 `generate_caption_from_params(audio_file, language, recognition_type, output_file, ...)` 函数，直接构造 `user_config` dict 传给 `Captioning` 对象，绕过 `user_config_from_args()`。

---

### 4. services/video/ -- 视频合成

| 文件 | 判断 | 说明 |
|---|---|---|
| `video_service.py` | **需要改造** | 核心文件。问题: `VideoService.__init__()` 和 `VideoMixService.__init__()` 从 `st.session_state` 读取 `video_fps`, `video_size`, `video_segment_min/max_length`, `enable_background_music`, `background_music`, `enable_video_transition_effect` 等全部参数。底层 ffmpeg 调用（`normalize_video()`, `generate_video_with_audio()`, `get_audio_duration()`, `add_music()`, `add_background_music()`）全部可复用。 |
| `merge_service.py` | **需要改造** | 同上，`VideoMergeService.__init__()` 读 `st.session_state`。`merge_generate_subtitle()` 读 st。底层 ffmpeg 操作可复用。 |
| `texiao_service.py` | **需要改造 (轻微)** | `gen_filter()` 函数签名干净，纯算法。但文件顶部 `import streamlit as st`（实际函数体没用到 st）。改造 = 删掉这个 import 即可。 |

**改造策略:**
Worker 中定义包装类，将 `st.session_state` 的参数改为构造函数参数:

```python
class WorkerVideoService(VideoService):
    def __init__(self, video_list, audio_file, video_config: dict):
        # 不调用 super().__init__()
        self.video_list = video_list
        self.audio_file = audio_file
        self.fps = video_config["fps"]
        self.seg_min_duration = video_config["segment_min_length"]
        self.seg_max_duration = video_config["segment_max_length"]
        self.target_width = video_config["width"]
        self.target_height = video_config["height"]
        self.enable_background_music = video_config.get("enable_background_music", False)
        self.background_music = video_config.get("background_music", "")
        self.background_music_volume = video_config.get("background_music_volume", 0.5)
        self.enable_video_transition_effect = video_config.get("enable_video_transition_effect", False)
        self.video_transition_effect_duration = video_config.get("video_transition_effect_duration", 1)
        self.video_transition_effect_type = video_config.get("video_transition_effect_type", "xfade")
        self.video_transition_effect_value = video_config.get("video_transition_effect_value", "fade")
        self.default_duration = max(5, self.seg_min_duration)
```

这样 `normalize_video()` 和 `generate_video_with_audio()` 都不需要改，因为它们只读 `self.*` 属性。

---

### 5. services/hunjian/ -- 混剪服务

| 文件 | 判断 | 说明 |
|---|---|---|
| `hunjian_service.py` | **需要改造** | `get_session_video_scene_text()` 100% 依赖 st.session_state。`get_audio_and_video_list()` 依赖 st.session_state + `st.toast` + `st.stop`。`concat_audio_list()` 纯 ffmpeg，直接复用。 |

**改造策略:**
Worker 不使用 `get_session_video_scene_text()`（那是 UI 层读场景列表的）。混剪的输入由 API 请求直接提供场景列表。`concat_audio_list()` 原样调用。

---

### 6. services/resource/ -- 在线素材

| 文件 | 判断 | 说明 |
|---|---|---|
| `resource_service.py` | **扔掉** | 抽象基类，构造函数读 `st.session_state`，且美业场景用本地素材，不需要在线搜索。 |
| `pexels_service.py` | **扔掉** | Pexels API。美业不需要。 |
| `pixabay_service.py` | **扔掉** | Pixabay API。美业不需要。 |

---

### 7. services/sd/ -- Stable Diffusion 文生图

| 文件 | 判断 | 说明 |
|---|---|---|
| `sd_service.py` | **扔掉** | 半成品，`pass` 占位。美业不需要 AI 生图。 |
| `webuiapi.py` | **扔掉** | SD WebUI API 客户端。 |

---

### 8. services/publisher/ -- 社媒发布

| 文件 | 判断 | 说明 |
|---|---|---|
| 全部 (douyin/kuaishou/xiaohongshu/bilibili/shipinhao) | **扔掉** | Selenium 自动化发布。n8n 工作流有自己的发布节点。Worker 只负责视频生成。 |

---

### 9. services/alinls/ -- 阿里语音识别 SDK

| 文件 | 判断 | 说明 |
|---|---|---|
| 全部文件 | 直接复用 | 阿里 NLS 语音识别的底层 WebSocket 客户端。纯 SDK 封装，无 st 依赖。 |

---

### 10. tools/ + config/

| 文件 | 判断 | 说明 |
|---|---|---|
| `config/config.py` | **需要改造** | `load_config()` 可复用（读 YAML）。但文件中 `save_session_state_to_yaml()` / `load_session_state_from_yaml()` 依赖 st。Worker 只用 `my_config = load_config()` 即可。需注意: 该文件顶层 `import streamlit as st`，`must_have_value` 也调用 `st.toast`/`st.stop`。**Worker 启动前需 mock `st` 模块或改写 `must_have_value()`。** |
| `tools/utils.py` | **需要改造** | `get_must_session_option()`, `must_have_value()`, `get_session_option()` 都依赖 st。Worker 需要提供替代实现（改为 raise ValueError）。`run_ffmpeg_command()`, `random_with_system_time()`, `extent_audio()` 直接复用。 |
| `tools/file_utils.py` | 直接复用 | 纯文件操作（YAML 读写、临时文件名、ffmpeg 转换等）。不含 st。 |
| `tools/tr_utils.py` | 扔掉 | 翻译工具，UI 层用的。 |

---

## 二、st.session_state 依赖全景清单

以下是所有读取 `st.session_state` 的位置，Worker 改造时必须全部替换:

| 模块 | session_state key | Worker 替代方式 |
|---|---|---|
| `video_service.py` VideoService/VideoMixService | `video_fps`, `video_size`, `video_segment_min_length`, `video_segment_max_length`, `enable_background_music`, `background_music`, `background_music_volume`, `enable_video_transition_effect`, `video_transition_effect_*` | 构造函数 config dict |
| `merge_service.py` VideoMergeService | 同上 | 构造函数 config dict |
| `hunjian_service.py` | `scene_number`, `video_scene_folder_N`, `video_scene_text_N`, `audio_voice` | API 请求 body |
| `chattts_service.py` | `refine_text`, `refine_text_prompt`, `text_seed`, `audio_temperature`, `audio_top_p`, `audio_top_k`, `use_random_voice`, `audio_seed`, `audio_voice`, `audio_speed` | API 请求 body |
| `gptsovits_service.py` | `audio_temperature`, `audio_top_p`, `audio_top_k`, `audio_speed`, `use_reference_audio`, `reference_audio`, `reference_audio_text`, `reference_audio_language`, `inference_audio_language` | API 请求 body |
| `cosyvoice_service.py` | `audio_seed`, `audio_speed`, `use_reference_audio`, `reference_audio_file_path`, `reference_audio_text`, `reference_audio_language` | API 请求 body |
| `captioning_service.py` | `recognition_audio_type`, `audio_output_file`, `audio_language` | 函数参数 |
| `user_config_helper.py` | `captioning_mode`, `captioning_remainTime`, `captioning_delay`, `captioning_maxLineLength`, `captioning_lines`, `audio_language`, `captioning_output`, `audio_output_file` 等 | 函数参数构造 dict |
| `resource_service.py` | `video_layout`, `video_size`, `video_fps`, `video_segment_*`, `enable_video_transition_effect` | 扔掉 |
| `texiao_service.py` | 顶层 `import st`（函数体无用） | 删 import |
| `config/config.py` | `save_session_state_to_yaml`/`load_session_state_from_yaml` | 不调用 |
| `tools/utils.py` | `get_session_option()`, `get_must_session_option()`, `must_have_value()` | 替换实现 |

---

## 三、FastAPI Worker API 设计

### 基础信息
- Base URL: `http://localhost:8000`
- Content-Type: `application/json`
- 文件输出统一写到 `{MPP_ROOT}/work/` 和 `{MPP_ROOT}/final/`

---

### 3.1 `GET /health`

健康检查。

**Response 200:**
```json
{
  "status": "ok",
  "ffmpeg": true,
  "config_loaded": true
}
```

---

### 3.2 `POST /generate-script`

LLM 生成文案。

**Request Body:**
```json
{
  "topic": "夏日清爽短发推荐",
  "language": "zh-CN",
  "length": "500",
  "llm_provider": "DeepSeek"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| topic | string | Y | 主题 |
| language | string | N | 默认 zh-CN |
| length | string | N | 字数限制，默认 500 |
| llm_provider | string | N | 默认用 config.yml 中的配置。可选: OpenAI / DeepSeek / Moonshot / Ollama / Tongyi / Azure / Qianfan / Baichuan |

**Response 200:**
```json
{
  "content": "夏天到了，很多小姐姐都想换个清爽的发型...",
  "keywords": "summer haircut, short hair, fresh style"
}
```

**复用路径:** `services/llm/llm_provider.py` -> `get_llm_provider()` -> `.generate_content()`

---

### 3.3 `POST /generate-audio`

TTS 生成配音。

**Request Body:**
```json
{
  "text": "夏天到了，很多小姐姐都想换个清爽的发型...",
  "tts_type": "remote",
  "provider": "Azure",
  "voice": "zh-CN-XiaoxiaoNeural",
  "rate": "0.00",
  "output_filename": "scene1_audio.wav",
  "local_tts_params": {
    "audio_speed": "normal",
    "audio_seed": 42,
    "audio_temperature": 0.3,
    "audio_top_p": 0.7,
    "audio_top_k": 20,
    "text_seed": 42,
    "skip_refine_text": true
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| text | string | Y | 要转语音的文本 |
| tts_type | string | Y | "remote" 或 "local" |
| provider | string | Y | remote: Azure/Ali/Tencent; local: chatTTS/GPTSoVITS/CosyVoice |
| voice | string | N | 语音角色（remote 模式必填） |
| rate | string | N | 语速，默认 "0.00" |
| output_filename | string | N | 输出文件名（不含路径），默认自动生成 |
| local_tts_params | object | N | 本地 TTS 额外参数 |

**Response 200:**
```json
{
  "audio_file": "D:/GITHUB/MoneyPrinterPlus/work/1716220800123.wav",
  "duration_seconds": 32.5
}
```

**复用路径:**
- Remote: `services/audio/azure_service.py` / `alitts_service.py` / `tencent_tts_service.py` -> `.save_with_ssml()`
- Local: `services/audio/chattts_service.py` / `gptsovits_service.py` / `cosyvoice_service.py` -> `.chat_with_content()`

---

### 3.4 `POST /generate-subtitle`

语音识别生成字幕 SRT 文件。

**Request Body:**
```json
{
  "audio_file": "D:/GITHUB/MoneyPrinterPlus/work/1716220800123.wav",
  "language": "zh-CN",
  "recognition_type": "local",
  "recognition_provider": "fasterwhisper",
  "output_filename": "scene1_subtitle.srt",
  "caption_config": {
    "max_line_length": 30,
    "lines": 2,
    "delay_ms": 1000,
    "remain_time_ms": 1000
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| audio_file | string | Y | 音频文件绝对路径 |
| language | string | N | 默认 zh-CN |
| recognition_type | string | Y | "local" 或 "remote" |
| recognition_provider | string | N | local: fasterwhisper/sensevoice; remote: Azure/Ali/Tencent |
| output_filename | string | N | 输出 SRT 文件名 |
| caption_config | object | N | 字幕格式配置 |

**Response 200:**
```json
{
  "subtitle_file": "D:/GITHUB/MoneyPrinterPlus/work/1716220800123.srt"
}
```

**复用路径:**
- `services/audio/faster_whisper_recognition_service.py` -> `.process()`
- `services/audio/sensevoice_whisper_recognition_service.py` -> `.process()`
- `services/captioning/common_captioning_service.py` -> `Captioning` 类
- `services/captioning/captioning_service.py` -> `add_subtitles()`（烧录字幕到视频时复用）

---

### 3.5 `POST /mix-video`

核心混剪接口。输入素材列表 + 配音 + 字幕 + 配置，输出最终 mp4。

**Request Body:**
```json
{
  "scenes": [
    {
      "media_dir": "D:/素材/门店实拍/染发",
      "text": ""
    },
    {
      "media_dir": "D:/素材/门店实拍/洗剪吹",
      "text": ""
    }
  ],
  "audio_file": "D:/GITHUB/MoneyPrinterPlus/work/1716220800123.wav",
  "subtitle_file": "D:/GITHUB/MoneyPrinterPlus/work/1716220800123.srt",
  "video_config": {
    "fps": 30,
    "width": 1080,
    "height": 1920,
    "segment_min_length": 3,
    "segment_max_length": 8,
    "enable_background_music": true,
    "background_music": "D:/素材/bgm/light.mp3",
    "background_music_volume": 0.3,
    "enable_video_transition_effect": true,
    "video_transition_effect_type": "xfade",
    "video_transition_effect_value": "fade",
    "video_transition_effect_duration": 1
  },
  "subtitle_config": {
    "enable": true,
    "font_name": "Songti TC Bold",
    "font_size": 16,
    "color": "#FFFFFF",
    "border_color": "#000000",
    "border_width": 1,
    "position": 2
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| scenes | array | Y | 场景列表，每个场景有 media_dir（本地素材目录）和可选 text |
| audio_file | string | Y | 配音文件绝对路径 |
| subtitle_file | string | N | SRT 字幕文件路径 |
| video_config | object | Y | 视频参数 |
| subtitle_config | object | N | 字幕样式 |

**Response 200:**
```json
{
  "video_file": "D:/GITHUB/MoneyPrinterPlus/final/final-1716220800123.mp4",
  "duration_seconds": 45.2
}
```

**复用路径:**
- 素材匹配: `services/video/video_service.py` -> `VideoMixService.match_videos_from_dir()`
- 音频拼接: `services/hunjian/hunjian_service.py` -> `concat_audio_list()`
- 视频归一化: `VideoService.normalize_video()`
- 视频合成: `VideoService.generate_video_with_audio()`
- 转场特效: `services/video/texiao_service.py` -> `gen_filter()`
- 字幕烧录: `services/captioning/captioning_service.py` -> `add_subtitles()`
- 背景音乐: `video_service.py` -> `add_background_music()`

---

### 3.6 `POST /generate-cover`

从视频中截取封面图。

**Request Body:**
```json
{
  "video_file": "D:/GITHUB/MoneyPrinterPlus/final/final-1716220800123.mp4",
  "timestamp": "00:00:03",
  "width": 1080,
  "height": 1920
}
```

**Response 200:**
```json
{
  "cover_file": "D:/GITHUB/MoneyPrinterPlus/final/cover-1716220800123.jpg"
}
```

**复用路径:** 新写。一条 ffmpeg 命令:
```
ffmpeg -i {video} -ss {timestamp} -vframes 1 -q:v 2 {output}
```

---

## 四、关键改造点详解

### 4.1 st.session_state 全面去除

**原则:** Worker 中绝不 import streamlit。所有原来从 session_state 读取的值，改为:
1. API 请求 body 传入
2. config.yml 启动时加载（通过 my_config）
3. 函数/构造函数参数

**具体手段:**
- 在 worker.py 启动前，mock 掉 `streamlit` 模块，让 `import streamlit as st` 不报错但 `st.session_state` 返回空 dict，`st.toast()` / `st.stop()` 变成 no-op 或 raise
- 重写 `tools/utils.py` 中的 `must_have_value()`: 改为 raise `ValueError` 而非 `st.stop()`
- 重写 `get_session_option()` / `get_must_session_option()`: 在 worker 中这两个不应被调用，如果调用则 raise

### 4.2 config.yml 处理

保留 MPP 原有的 `config/config.yml`。Worker 启动时 `load_config()` 加载一次到全局 `my_config`。
运行时不写入 session.yml。

### 4.3 路径处理

- 所有文件路径改为绝对路径
- Worker 启动时确定 `WORK_DIR` 和 `FINAL_DIR` 两个目录
- ffmpeg 调用中的路径全部用绝对路径
- Windows 路径中的反斜杠处理（字幕烧录时已有处理逻辑）

### 4.4 ffmpeg 依赖

直接复用 MPP 的 ffmpeg 调用方式（subprocess）。确保 ffmpeg 在 PATH 中。

---

## 五、文件清单（Worker 涉及的文件）

### 直接复用（不修改）
```
services/llm/*                              -- 全部 8 个 service + provider + base
services/audio/audio_service.py             -- TTS 基类
services/audio/azure_service.py             -- Azure TTS
services/audio/alitts_service.py            -- 阿里 TTS
services/audio/tencent_tts_service.py       -- 腾讯 TTS
services/audio/faster_whisper_recognition_service.py   -- FasterWhisper ASR
services/audio/sensevoice_whisper_recognition_service.py -- SenseVoice ASR
services/audio/tencent_recognition_service.py  -- 腾讯 ASR
services/alinls/*                           -- 阿里 NLS SDK
services/captioning/common_captioning_service.py -- Captioning 核心
services/captioning/caption_helper.py       -- 字幕算法
services/captioning/helper.py               -- 时间工具
tools/file_utils.py                         -- 文件工具
config/config.yml                           -- 配置文件
```

### 需要包装/适配（Worker 中写 wrapper，不改原文件）
```
services/audio/chattts_service.py           -- 包装构造函数
services/audio/gptsovits_service.py         -- 包装构造函数
services/audio/cosyvoice_service.py         -- 包装构造函数
services/video/video_service.py             -- 包装 VideoService/VideoMixService 构造函数
services/video/merge_service.py             -- 包装 VideoMergeService 构造函数
services/video/texiao_service.py            -- gen_filter() 直接调用（忽略 st import）
services/captioning/captioning_service.py   -- 包装 generate_caption()，复用 add_subtitles()
services/captioning/user_config_helper.py   -- 用 dict 替代 user_config_from_args()
services/hunjian/hunjian_service.py         -- 直接调用 concat_audio_list()
tools/utils.py                              -- mock must_have_value/get_session_option
config/config.py                            -- 只用 load_config()，mock st 部分
```

### 扔掉（Worker 不涉及）
```
services/resource/*                         -- Pexels/Pixabay 在线素材
services/sd/*                               -- Stable Diffusion
services/publisher/*                        -- 社媒发布
services/audio/generate-subtitles.py        -- 独立脚本
tools/tr_utils.py                           -- 翻译（UI 层）
gui.py + pages/*                            -- Streamlit UI
main.py                                     -- 原入口
```

---

## 六、依赖

在 MPP 原有 requirements.txt 基础上追加:
```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
python-multipart>=0.0.9
```

可选移除（Worker 不需要）:
```
streamlit          -- 通过 mock 绕过，不需要真装
wxPython           -- GUI
selenium           -- 发布
pyaudio            -- 麦克风（worker 不录音）
```
