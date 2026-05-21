# CLAUDE.md — Shadowblade Worker

## What is this

Shadowblade is a self-hosted FastAPI worker that automates short video creation for local service businesses. It runs on edge devices and produces publish-ready videos with voiceover, subtitles, and brand watermarks.

## Project layout

- `app/worker.py` — FastAPI application (6 endpoints)
- `app/services/` — reusable service modules (LLM, TTS, ASR, video mixing, captioning)
- `config/config.py` — YAML config loader (copy `config.example.yml` → `config.yml`)
- `tools/` — utility functions (ffmpeg wrappers, file ops)
- `project/` — upstream fork (Electron + Web + Backend), not part of the Worker

## Running the Worker

```bash
pip install -r requirements.txt
cp config/config.example.yml config/config.yml  # edit: add API keys
python -m uvicorn app.worker:app --host 0.0.0.0 --port 8000 --reload
```

Or: `make worker`

## Prerequisites

- Python 3.11+
- ffmpeg 6+ in PATH
- CJK font (Noto Sans CJK or Microsoft YaHei) for subtitles

## Key conventions

- Default language: respond in 简体中文
- No streamlit imports anywhere in app/, tools/, or config/
- All service classes accept explicit constructor params, never read st.session_state
- Use absolute file paths in ffmpeg commands
- Worker writes temp files to `app/work/`, final output to `app/final/`

## Verification

```bash
# Health check
curl http://localhost:8000/health

# Swagger UI
open http://localhost:8000/docs
```

## Docker

```bash
docker compose up shadowblade-worker
```
