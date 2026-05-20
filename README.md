# Shadowblade

> AI-powered video production pipeline for local businesses.

Shadowblade is a self-hosted FastAPI worker that automates short video creation for local service businesses (beauty salons, nail shops, spas). It runs on edge devices and produces publish-ready videos with voiceover, subtitles, and brand watermarks — no cloud dependency required.

## What it does

```
Input: business info + local video clips
  ↓
[LLM] Generate marketing script (DeepSeek)
  ↓
[TTS] Chinese voiceover (edge-tts / Azure / CosyVoice)
  ↓
[ASR] Auto-generate subtitles (faster-whisper)
  ↓
[Mix] Combine clips + audio + subtitles + transitions + brand intro
  ↓
Output: ready-to-publish MP4 (Douyin/Xiaohongshu/Kuaishou)
```

## Quick Start

```bash
# Prerequisites: Python 3.11 + ffmpeg

cd shadowblade
pip install -r requirements.txt
cp config/config.example.yml config/config.yml
# Edit config.yml: add your DeepSeek API key

python -m uvicorn app.worker:app --host 0.0.0.0 --port 8000
# Open http://localhost:8000/docs for Swagger UI
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check (ffmpeg + config status) |
| `/generate-script` | POST | LLM generates marketing copy + keywords |
| `/generate-audio` | POST | TTS voiceover from text |
| `/generate-subtitle` | POST | ASR speech-to-text → SRT file |
| `/mix-video` | POST | Core mixing: clips + audio + subtitles → MP4 |
| `/generate-cover` | POST | Extract cover image from video |

## Features

- Auto-detect source resolution (horizontal/vertical video)
- Brand intro watermark (configurable text overlay)
- Fade transitions between clips
- Chinese subtitle burn-in (Microsoft YaHei)
- Multiple LLM backends (DeepSeek / OpenAI / Moonshot / Ollama / Tongyi / Baichuan)
- Multiple TTS backends (edge-tts / Azure / Ali / Tencent / ChatTTS / GPT-SoVITS / CosyVoice)
- Local-first: runs entirely on-device except LLM API calls

## Project Structure

```
shadowblade/
├── app/
│   ├── worker.py              # FastAPI application (6 endpoints)
│   └── services/
│       ├── llm/               # 8 LLM providers
│       ├── audio/             # TTS + ASR services
│       ├── video/             # ffmpeg mixing + transitions
│       ├── captioning/        # Subtitle generation
│       └── hunjian/           # Audio concatenation
├── config/
│   ├── config.example.yml     # Template (copy to config.yml)
│   └── config.py              # Config loader
├── tools/                     # Utility functions
├── workflow/                  # n8n workflow (JSON + docs)
├── docs/                      # Product design docs
├── assets/beauty/             # Stock video library (gitignored)
├── app/work/                  # Temp files (gitignored)
└── app/final/                 # Output videos (gitignored)
```

## Designed for Edge Deployment

Shadowblade is built to run on local hardware devices (Centaur AI K1) placed in merchant stores:

- Runs offline except for LLM API calls
- Remote management via Tailscale + device agent
- OTA workflow updates via n8n API
- Merchant data never leaves the device

## Docs

- [Merchant Prototype](docs/merchant-prototype.md) — 12-screen WeChat mini-program interaction design
- [Worker Blueprint](docs/worker-blueprint.md) — Service architecture and API design
- [n8n Workflow](workflow/n8n-blueprint.md) — Orchestration architecture
- [Workflow JSON](workflow/workflow-draft.json) — Importable n8n workflow

## Tech Stack

- Python 3.11 + FastAPI + uvicorn
- ffmpeg 8.x (video processing)
- faster-whisper (local ASR)
- edge-tts (free Microsoft TTS)
- DeepSeek API (LLM, ~$0.001/video)
- n8n (workflow orchestration, optional)

## License

Proprietary. Internal use only.

---

Built by Centaur AI.
