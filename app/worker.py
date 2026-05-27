"""
Shadowblade Worker -- FastAPI HTTP Worker for video mixing pipeline

Usage:
    cd D:/GITHUB/shadowblade
    python -m app.worker

    # or with custom port
    uvicorn app.worker:app --host 0.0.0.0 --port 8000 --reload
"""

import os
import sys
import re
import json
import shutil
import asyncio
import subprocess
import logging
from pathlib import Path
from typing import Optional, List

# ---------------------------------------------------------------------------
# 1. PATH SETUP -- make sure project root is on sys.path
# ---------------------------------------------------------------------------

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Also keep app/ on sys.path so internal "from services.xxx" imports
# within the services package continue to resolve.
APP_DIR = os.path.join(PROJECT_ROOT, "app")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

WORK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "work")
FINAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "final")
STOCK_DIR = os.path.join(WORK_DIR, "stock")
os.makedirs(WORK_DIR, exist_ok=True)
os.makedirs(FINAL_DIR, exist_ok=True)
os.makedirs(STOCK_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# 2. Import project modules
# ---------------------------------------------------------------------------

from config.config import my_config
from app.services.llm.llm_provider import get_llm_provider
from app.services.audio.azure_service import AzureAudioService
from app.services.audio.alitts_service import AliAudioService
from app.services.audio.tencent_tts_service import TencentAudioService
from app.services.audio.edgetts_service import EdgeTTSAudioService
from app.services.audio.faster_whisper_recognition_service import FasterWhisperRecognitionService
from app.services.audio.sensevoice_whisper_recognition_service import SenseVoiceRecognitionService
from app.services.video.video_service import (
    VideoService, VideoMixService, get_audio_duration, get_video_duration,
    add_music, add_background_music, get_video_length_list,
)
from app.services.video.texiao_service import gen_filter
from app.services.captioning.captioning_service import add_subtitles
from app.services.hunjian.hunjian_service import concat_audio_list
from app.services.stock.stock_service import fetch_stock_footage, StockProviderError
from tools.utils import random_with_system_time, run_ffmpeg_command, extent_audio
from tools.file_utils import generate_temp_filename

# ---------------------------------------------------------------------------
# 4. FASTAPI APP
# ---------------------------------------------------------------------------

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

logger = logging.getLogger("shadowblade")

app = FastAPI(
    title="Shadowblade Worker",
    description="AI video production worker for local businesses",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/files/work", StaticFiles(directory=WORK_DIR), name="work-files")
app.mount("/files/final", StaticFiles(directory=FINAL_DIR), name="final-files")

# ---------------------------------------------------------------------------
# Front-end: 影刀短视频工作台 (static SPA under app/web/)
# ---------------------------------------------------------------------------

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
if os.path.isdir(WEB_DIR):
    app.mount("/web", StaticFiles(directory=WEB_DIR, html=True), name="web")

    @app.get("/", include_in_schema=False)
    def _root():
        return RedirectResponse(url="/web/")


# ---------------------------------------------------------------------------
# /file?path=...   safe read-only file serving for produced artifacts
# only paths inside WORK_DIR or FINAL_DIR are allowed
# ---------------------------------------------------------------------------

from fastapi.responses import FileResponse

_ALLOWED_FILE_ROOTS = (
    os.path.realpath(WORK_DIR),
    os.path.realpath(FINAL_DIR),
)

@app.get("/file", include_in_schema=False)
def serve_artifact(path: str):
    """Serve a produced artifact (audio / video / srt / cover) by absolute path,
    restricted to WORK_DIR / FINAL_DIR."""
    try:
        resolved = os.path.realpath(path)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid path")

    if not any(resolved.startswith(root + os.sep) or resolved == root
               for root in _ALLOWED_FILE_ROOTS):
        raise HTTPException(status_code=403, detail="path not allowed")

    if not os.path.isfile(resolved):
        raise HTTPException(status_code=404, detail="file not found")

    return FileResponse(resolved)


@app.on_event("startup")
def on_startup():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Shadowblade Worker starting up")
    logger.info(f"WORK_DIR={WORK_DIR}  FINAL_DIR={FINAL_DIR}")

# ========================== SCHEMAS ==========================

# --- /generate-script ---

class GenerateScriptRequest(BaseModel):
    topic: str
    language: str = "zh-CN"
    length: str = "500"
    llm_provider: Optional[str] = None  # override config.yml
    # 如果填了下面 3 个，会临时盖掉 config.yml 里对应 provider 的配置
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model_name: Optional[str] = None
    # 脚本结构模板 id：general / promo / testimonial / promotion / tutorial / event
    template_id: Optional[str] = None
    # 用户当前已经有的 scene 目录名（kebab-case），交给分镜 LLM 优先匹配
    available_scenes: List[str] = []

class ScriptSegment(BaseModel):
    """脚本的一句话 + 它应该配什么场景的画面"""
    text: str
    scene_hint: str  # kebab-case 目录名（可能在 available_scenes 里，也可能是 LLM 推荐的新名）

class GenerateScriptResponse(BaseModel):
    content: str
    keywords: str
    template_id: str = "general"
    # 把脚本按口播节奏切成 6-12 段，每段绑一个 scene_hint，由 mix 阶段按段挑素材
    segments: List[ScriptSegment] = []
    # LLM 觉得这条脚本还需要哪些场景目录（用户参考，不一定真的去建）
    suggested_scenes: List[str] = []

# --- /segment-script（脚本编辑后重新分镜用） ---

class SegmentScriptRequest(BaseModel):
    script: str
    template_id: str = "general"
    available_scenes: List[str] = []
    llm_provider: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model_name: Optional[str] = None

class SegmentScriptResponse(BaseModel):
    segments: List[ScriptSegment]
    suggested_scenes: List[str] = []

# --- /wizard/chat ---

class WizardMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str

class WizardChatRequest(BaseModel):
    messages: List[WizardMessage]
    language: str = "zh-CN"
    llm_provider: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model_name: Optional[str] = None

class WizardFields(BaseModel):
    topic: str = ""
    intro: str = ""
    length: str = "500"
    language: str = "zh-CN"
    style_hint: str = ""
    template_id: str = "general"  # 由 LLM 在向导里自动推断
    # 向导推荐用户应该建哪些 scene 目录（用户参考，不强制）
    suggested_scene_dirs: List[str] = []

class WizardChatResponse(BaseModel):
    done: bool
    reply: str
    fields: Optional[WizardFields] = None
    rounds: int = 0  # 已经走了几轮用户问答（方便前端做进度提示）

# --- /generate-audio ---

class LocalTTSParams(BaseModel):
    audio_speed: str = "normal"
    audio_seed: int = 42
    audio_temperature: float = 0.3
    audio_top_p: float = 0.7
    audio_top_k: int = 20
    text_seed: int = 42
    skip_refine_text: bool = True
    refine_text_prompt: str = ""
    # GPTSoVITS / CosyVoice specific
    refer_wav_path: Optional[str] = None
    prompt_text: Optional[str] = None
    prompt_language: Optional[str] = None
    text_language: Optional[str] = "zh"
    reference_audio_language: Optional[str] = None

class GenerateAudioRequest(BaseModel):
    text: str
    tts_type: str  # "remote" or "local"
    provider: str  # Azure / Ali / Tencent / chatTTS / GPTSoVITS / CosyVoice
    voice: Optional[str] = None
    rate: str = "0"
    output_filename: Optional[str] = None
    local_tts_params: Optional[LocalTTSParams] = None

class GenerateAudioResponse(BaseModel):
    audio_file: str
    duration_seconds: Optional[float] = None

# --- /generate-subtitle ---

class CaptionConfig(BaseModel):
    max_line_length: int = 30
    lines: int = 2
    delay_ms: int = 1000
    remain_time_ms: int = 1000

class GenerateSubtitleRequest(BaseModel):
    audio_file: str
    language: str = "zh-CN"
    recognition_type: str = "local"  # "local" or "remote"
    recognition_provider: str = "fasterwhisper"  # fasterwhisper / sensevoice / Azure / Ali / Tencent
    output_filename: Optional[str] = None
    caption_config: Optional[CaptionConfig] = None

class GenerateSubtitleResponse(BaseModel):
    subtitle_file: str
    line_count: int = 0

# --- /mix-video ---

class SceneItem(BaseModel):
    media_dir: str  # absolute path to local media folder
    text: str = ""  # optional overlay text for this scene

class VideoConfig(BaseModel):
    fps: int = 30
    width: int = 0           # 0 = auto-detect from first video
    height: int = 0          # 0 = auto-detect from first video
    segment_min_length: int = 3
    segment_max_length: int = 8
    enable_background_music: bool = False
    background_music: str = ""
    background_music_volume: float = 0.3
    enable_video_transition_effect: bool = False
    video_transition_effect_type: str = "xfade"
    video_transition_effect_value: str = "fade"
    video_transition_effect_duration: float = 1.0
    intro_text: str = ""     # text shown at the beginning (e.g. brand watermark)

class SubtitleConfig(BaseModel):
    enable: bool = True
    font_name: str = "Songti TC Bold"
    font_size: int = 16
    color: str = "#FFFFFF"
    border_color: str = "#000000"
    border_width: int = 1
    position: int = 2  # ASS alignment: 2=bottom-center

class MixVideoRequest(BaseModel):
    scenes: List[SceneItem]
    audio_file: str
    subtitle_file: Optional[str] = None
    video_config: VideoConfig
    subtitle_config: Optional[SubtitleConfig] = None
    # 脚本分镜：按段顺序选素材。空列表 → 走老逻辑（按目录顺序遍历）
    segments: List[ScriptSegment] = []

class MixVideoResponse(BaseModel):
    video_file: str
    duration_seconds: Optional[float] = None

# --- /generate-cover ---

class GenerateCoverRequest(BaseModel):
    video_file: str
    timestamp: str = "00:00:03"
    width: int = 1080
    height: int = 1920

class GenerateCoverResponse(BaseModel):
    cover_file: str

# --- /stock/* ---

class StockStatusResponse(BaseModel):
    pexels: dict
    ytdlp: dict

class StockFromUrlRequest(BaseModel):
    url: str
    sections: Optional[str] = "*0:00-0:08"
    max_height: int = 1080

class StockFromUrlResponse(BaseModel):
    path: str
    directory: str
    title: str = ""
    duration: Optional[float] = None

class StockSearchRequest(BaseModel):
    keyword: str
    count: int = Field(default=3, ge=1, le=8)
    max_seconds: float = Field(default=6.0, ge=2, le=15)

class StockSearchResponse(BaseModel):
    keyword: str
    directory: str
    paths: List[str]
    titles: List[str]
    sources: List[str]

class PexelsAutoRequest(BaseModel):
    query: str
    count: int = Field(default=3, ge=1, le=10)
    orientation: str = "portrait"
    api_key: Optional[str] = None

class PexelsAutoResponse(BaseModel):
    query: str
    directory: str
    paths: List[str]
    photographers: List[str]


# ========================== HELPER: VideoService Wrapper ==========================

def _build_video_service(video_list: list, audio_file: str, vc: VideoConfig):
    """
    Create a VideoService instance with explicit constructor parameters.

    Reuses:
      - services/video/video_service.py :: VideoService.normalize_video()
      - services/video/video_service.py :: VideoService.generate_video_with_audio()
    """
    svc = VideoService(
        video_list=video_list,
        audio_file=audio_file,
        fps=vc.fps,
        seg_min_duration=vc.segment_min_length,
        seg_max_duration=vc.segment_max_length,
        target_width=vc.width,
        target_height=vc.height,
        enable_background_music=vc.enable_background_music,
        background_music=vc.background_music,
        background_music_volume=vc.background_music_volume,
        enable_video_transition_effect=vc.enable_video_transition_effect,
        video_transition_effect_duration=vc.video_transition_effect_duration,
        video_transition_effect_type=vc.video_transition_effect_type,
        video_transition_effect_value=vc.video_transition_effect_value,
    )
    return svc


def _build_video_mix_service(vc: VideoConfig):
    """
    Create a VideoMixService instance with explicit constructor parameters.

    Reuses:
      - services/video/video_service.py :: VideoMixService.match_videos_from_dir()
    """
    svc = VideoMixService(
        fps=vc.fps,
        segment_min_length=vc.segment_min_length,
        segment_max_length=vc.segment_max_length,
        target_width=vc.width,
        target_height=vc.height,
        enable_background_music=vc.enable_background_music,
        background_music=vc.background_music,
        background_music_volume=vc.background_music_volume,
        enable_video_transition_effect=vc.enable_video_transition_effect,
        video_transition_effect_duration=vc.video_transition_effect_duration,
        video_transition_effect_type=vc.video_transition_effect_type,
        video_transition_effect_value=vc.video_transition_effect_value,
    )
    return svc


# ========================== HELPER: Stock acquisition ==========================

def _safe_stock_slug(value: str, fallback: str = "clip") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())[:64].strip("-._")
    return text or fallback


def _stock_dir(source: str) -> str:
    folder = os.path.join(STOCK_DIR, _safe_stock_slug(source, "source"))
    os.makedirs(folder, exist_ok=True)
    return folder


def _ytdlp_binary() -> str:
    venv_candidate = Path(sys.executable).parent / "yt-dlp"
    if venv_candidate.exists():
        return str(venv_candidate)
    binary = shutil.which("yt-dlp")
    if binary:
        return binary
    raise RuntimeError("yt-dlp is not installed. Run `pip install yt-dlp` in the ShadowBlade venv.")


def _probe_media(path: str) -> dict:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=width,height",
        "-of",
        "json",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def _trim_video(source: str, target: str, max_seconds: float = 6.0):
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-y",
        "-i",
        source,
        "-t",
        f"{max_seconds:.2f}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ac",
        "1",
        "-ar",
        "48000",
        target,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0 or not os.path.exists(target):
        raise RuntimeError(result.stderr[-500:] or "ffmpeg trim failed")


def _run_ytdlp(url: str, out_dir: str, sections: Optional[str], max_height: int, filename_hint: str):
    binary = _ytdlp_binary()
    output_template = os.path.join(out_dir, f"{_safe_stock_slug(filename_hint)}.%(ext)s")
    cmd = [
        binary,
        "--no-playlist",
        "--no-warnings",
        "--quiet",
        "--print-json",
        "-f",
        f"bv*[height<={max_height}][ext=mp4]+ba[ext=m4a]/b[height<={max_height}][ext=mp4]/b",
        "--merge-output-format",
        "mp4",
        "-o",
        output_template,
    ]
    if sections:
        cmd += ["--download-sections", sections]
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-700:] or "yt-dlp failed")

    meta = {}
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                meta = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

    candidates = sorted(
        Path(out_dir).glob(f"{_safe_stock_slug(filename_hint)}.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError("yt-dlp ran but produced no output file")
    produced = str(candidates[0])
    info = _probe_media(produced)
    return produced, meta, info


def _ytdlp_search_entries(keyword: str, limit: int, max_duration: int = 300) -> List[dict]:
    binary = _ytdlp_binary()
    cmd = [
        binary,
        "--dump-json",
        "--flat-playlist",
        "--no-warnings",
        "--quiet",
        "--match-filter",
        f"duration<{max_duration}",
        f"ytsearch{max(limit, 1)}:{keyword}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if result.returncode != 0 and not result.stdout:
        raise RuntimeError(result.stderr[-500:] or "yt-dlp search failed")

    entries = []
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            meta = json.loads(line)
        except json.JSONDecodeError:
            continue
        url = meta.get("webpage_url") or meta.get("url")
        if not url:
            continue
        if meta.get("ie_key") == "Youtube" and not str(url).startswith(("http://", "https://")):
            url = f"https://www.youtube.com/watch?v={url}"
        entries.append({
            "url": str(url),
            "id": str(meta.get("id") or len(entries)),
            "title": str(meta.get("title") or "Untitled stock clip"),
        })
    return entries


def _archive_search(keyword: str, count: int, out_dir: str, max_seconds: float):
    import requests

    search_url = "https://archive.org/advancedsearch.php"
    meta_url = "https://archive.org/metadata"
    params = {
        "q": f'"{keyword}" mediatype:movies',
        "fl[]": ["identifier", "title", "downloads"],
        "sort[]": "downloads desc",
        "rows": "12",
        "output": "json",
    }
    response = requests.get(search_url, params=params, timeout=15)
    response.raise_for_status()
    docs = (response.json().get("response") or {}).get("docs", [])
    paths = []
    titles = []
    for doc in docs:
        identifier = doc.get("identifier")
        if not identifier:
            continue
        meta = requests.get(f"{meta_url}/{identifier}", timeout=15)
        if meta.status_code != 200:
            continue
        files = meta.json().get("files", [])
        pick = None
        for item in sorted(files, key=lambda f: int(f.get("size") or 0)):
            name = item.get("name", "")
            size = int(item.get("size") or 0)
            if name.lower().endswith((".mp4", ".mov", ".m4v")) and 1_000_000 <= size <= 250_000_000:
                pick = item
                break
        if not pick:
            continue
        source_url = f"https://archive.org/download/{identifier}/{pick['name']}"
        raw_path = os.path.join(out_dir, f"archive-{_safe_stock_slug(identifier)}.source.mp4")
        final_path = os.path.join(out_dir, f"archive-{_safe_stock_slug(identifier)}.mp4")
        if not os.path.exists(final_path) or os.path.getsize(final_path) < 30_000:
            with requests.get(source_url, stream=True, timeout=60) as download:
                if download.status_code != 200:
                    continue
                with open(raw_path, "wb") as handle:
                    for chunk in download.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            handle.write(chunk)
            _trim_video(raw_path, final_path, max_seconds)
            try:
                os.remove(raw_path)
            except OSError:
                pass
        paths.append(os.path.abspath(final_path))
        titles.append(str(doc.get("title") or identifier))
        if len(paths) >= count:
            break
    return paths, titles


async def _pexels_auto_download(query: str, count: int, orientation: str, api_key: Optional[str]):
    import httpx

    key = api_key or os.environ.get("PEXELS_API_KEY") or os.environ.get("SHADOWBLADE_PEXELS_KEY")
    if not key:
        raise RuntimeError("PEXELS_API_KEY is not set.")
    out_dir = _stock_dir("pexels")
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0), follow_redirects=True) as client:
        response = await client.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "per_page": count + 4, "orientation": orientation, "size": "medium"},
            headers={"Authorization": key},
        )
        if response.status_code != 200:
            raise RuntimeError(f"Pexels search failed: {response.status_code} {response.text[:200]}")
        videos = response.json().get("videos", [])
        paths = []
        photographers = []
        for video in videos:
            files = [item for item in video.get("video_files", []) if item.get("file_type") == "video/mp4"]
            if not files:
                continue
            files.sort(key=lambda item: item.get("height") or 0, reverse=True)
            picked = next((item for item in files if (item.get("height") or 0) <= 1920), files[-1])
            target = os.path.join(out_dir, f"pexels-{video.get('id')}.source.mp4")
            final = os.path.join(out_dir, f"pexels-{video.get('id')}.mp4")
            if not os.path.exists(final) or os.path.getsize(final) < 30_000:
                async with client.stream("GET", picked.get("link", "")) as download:
                    if download.status_code != 200:
                        continue
                    with open(target, "wb") as handle:
                        async for chunk in download.aiter_bytes(64 * 1024):
                            handle.write(chunk)
                _trim_video(target, final, 6.0)
                try:
                    os.remove(target)
                except OSError:
                    pass
            paths.append(os.path.abspath(final))
            photographers.append((video.get("user") or {}).get("name", ""))
            if len(paths) >= count:
                break
    if not paths:
        raise RuntimeError("No Pexels clips downloaded.")
    return out_dir, paths, photographers


# ========================== HELPER: Remote TTS Factory ==========================

def _get_remote_audio_service(provider: str):
    """
    Factory for remote TTS services.

    Reuses:
      - services/audio/azure_service.py :: AzureAudioService
      - services/audio/alitts_service.py :: AliAudioService
      - services/audio/tencent_tts_service.py :: TencentAudioService
    """
    if provider == "Azure":
        return AzureAudioService()
    elif provider == "Ali":
        return AliAudioService()
    elif provider == "Tencent":
        return TencentAudioService()
    elif provider == "EdgeTTS":
        return EdgeTTSAudioService()
    else:
        raise ValueError(f"Unknown remote TTS provider: {provider}")


# ========================== HELPER: Local TTS Factory ==========================

def _create_local_tts_service(provider: str, params: LocalTTSParams):
    """
    Create a local TTS service instance with API params.

    Reuses:
      - services/audio/chattts_service.py :: ChatTTSAudioService.chat_with_content()
      - services/audio/gptsovits_service.py :: GPTSoVITSAudioService.chat_with_content()
      - services/audio/cosyvoice_service.py :: CosyVoiceAudioService.chat_with_content()
    """
    if provider == "chatTTS":
        from app.services.audio.chattts_service import ChatTTSAudioService
        svc = ChatTTSAudioService(
            skip_refine_text=params.skip_refine_text,
            refine_text_prompt=params.refine_text_prompt,
            text_seed=params.text_seed,
            audio_temperature=params.audio_temperature,
            audio_top_p=params.audio_top_p,
            audio_top_k=params.audio_top_k,
            audio_seed=params.audio_seed,
            audio_speed=params.audio_speed,
        )
        return svc

    elif provider == "GPTSoVITS":
        from app.services.audio.gptsovits_service import GPTSoVITSAudioService
        svc = GPTSoVITSAudioService(
            audio_temperature=params.audio_temperature,
            audio_top_p=params.audio_top_p,
            audio_top_k=params.audio_top_k,
            audio_speed=params.audio_speed,
            refer_wav_path=params.refer_wav_path,
            prompt_text=params.prompt_text,
            prompt_language=params.prompt_language,
            text_language=params.text_language,
        )
        return svc

    elif provider == "CosyVoice":
        from app.services.audio.cosyvoice_service import CosyVoiceAudioService
        svc = CosyVoiceAudioService(
            audio_seed=params.audio_seed,
            audio_speed=params.audio_speed,
            refer_wav_path=params.refer_wav_path,
            prompt_text=params.prompt_text,
            reference_audio_language=params.reference_audio_language,
        )
        return svc

    else:
        raise ValueError(f"Unknown local TTS provider: {provider}")


# ========================== HELPER: ASR dispatch ==========================

def _run_asr(audio_file: str, language: str, recognition_type: str, recognition_provider: str):
    """
    Run speech recognition and return a list of result objects.

    Reuses:
      - services/audio/faster_whisper_recognition_service.py :: FasterWhisperRecognitionService.process()
      - services/audio/sensevoice_whisper_recognition_service.py :: SenseVoiceRecognitionService.process()
    For remote providers, reuses:
      - services/alinls/speech_process.py :: AliRecognitionService.process()
      - services/audio/tencent_recognition_service.py :: TencentRecognitionService.process()
    """
    if recognition_type == "local":
        if recognition_provider == "fasterwhisper":
            svc = FasterWhisperRecognitionService()
            return svc.process(audio_file, language)
        elif recognition_provider == "sensevoice":
            svc = SenseVoiceRecognitionService()
            return svc.process(audio_file, language)
        else:
            raise ValueError(f"Unknown local ASR provider: {recognition_provider}")

    elif recognition_type == "remote":
        if recognition_provider == "Ali":
            from app.services.alinls.speech_process import AliRecognitionService
            svc = AliRecognitionService()
            return svc.process(audio_file)
        elif recognition_provider == "Tencent":
            from app.services.audio.tencent_recognition_service import TencentRecognitionService
            svc = TencentRecognitionService()
            return svc.process(audio_file, language)
        elif recognition_provider == "Azure":
            # Azure uses the full Captioning pipeline with real-time/offline recognition
            # For simplicity, we recommend using local ASR in the worker.
            raise NotImplementedError("Azure remote ASR requires the full Captioning pipeline. Use local ASR instead.")
        else:
            raise ValueError(f"Unknown remote ASR provider: {recognition_provider}")
    else:
        raise ValueError(f"Unknown recognition_type: {recognition_type}")


def _generate_srt_from_results(results, output_file: str, caption_cfg: CaptionConfig, language: str):
    """
    Convert ASR results into an SRT file using the Captioning engine.

    Reuses:
      - services/captioning/common_captioning_service.py :: Captioning class
      - services/captioning/caption_helper.py :: CaptionHelper
      - services/captioning/helper.py :: time utilities
    """
    from datetime import timedelta
    from app.services.captioning.common_captioning_service import Captioning
    from app.services.captioning import helper as cap_helper

    # Build a user_config dict directly (bypasses user_config_helper.py which reads st)
    user_config = cap_helper.Read_Only_Dict({
        "use_compressed_audio": None,
        "compressed_audio_format": None,
        "profanity_option": None,
        "language": language,
        "input_file": None,
        "output_file": output_file,
        "phrases": [],
        "suppress_console_output": True,
        "captioning_mode": type('Enum', (), {"value": 1})(),  # OFFLINE
        "remain_time": timedelta(milliseconds=caption_cfg.remain_time_ms),
        "delay": timedelta(milliseconds=caption_cfg.delay_ms),
        "use_sub_rip_text_caption_format": True,
        "max_line_length": caption_cfg.max_line_length,
        "lines": caption_cfg.lines,
        "stable_partial_result_threshold": None,
        "subscription_key": "",
        "region": "",
    })

    # Create Captioning instance and inject config + results
    captioning = object.__new__(Captioning)
    captioning._user_config = user_config
    captioning._srt_sequence_number = 1
    captioning._previous_caption = None
    captioning._previous_end_time = None
    captioning._previous_result_is_recognized = False
    captioning._recognized_lines = []
    captioning._offline_results = results

    # Remove existing output file
    if os.path.exists(output_file):
        os.remove(output_file)

    # Use the Captioning.finish() method to write SRT
    # We need to set captioning_mode to OFFLINE enum value properly
    from app.services.captioning.user_config_helper import CaptioningMode
    captioning._user_config = cap_helper.Read_Only_Dict({
        **dict(user_config),
        "captioning_mode": CaptioningMode.OFFLINE,
    })
    captioning.finish()

    return output_file


# ========================== ROUTES ==========================

@app.get("/health")
def health_check():
    """Health check endpoint."""
    ffmpeg_ok = False
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        ffmpeg_ok = result.returncode == 0
    except Exception:
        pass

    return {
        "status": "ok",
        "ffmpeg": ffmpeg_ok,
        "config_loaded": my_config is not None,
        "work_dir": WORK_DIR,
        "final_dir": FINAL_DIR,
    }


# ============================================================
# 脚本结构模板库 —— 本地生活高频场景
#
# 每个模板必须包含 {topic} {language} {length} 三个占位符；
# 模板由 generate_script() 包装成 langchain PromptTemplate 后喂给
# LLM service.generate_content()。这样不动 service 层就能切换结构。
#
# 模板里**不写**章节小标题、列表序号，因为最终要进 TTS 朗读，
# 直接说「开场：xxx」会被读出来。结构指令藏在 prompt 里给 LLM 看。
# ============================================================

_SCRIPT_TEMPLATES = {
    "general": (
        "请为以下主题写一段短视频解说稿，{length} 字以内。\n\n"
        "主题：{topic}\n\n"
        "要求：\n"
        "1. 直接输出解说稿正文，不要标题、不要章节标号、不要带「开场」「结尾」这类提示词。\n"
        "2. 句子短，口语化，适合朗读，不要书面语和长句子。\n"
        "3. 用 {language} 输出。"
    ),
    "promo": (
        "请围绕主题写一条短视频解说稿，类型是「产品/服务种草」，{length} 字以内。\n\n"
        "主题：{topic}\n\n"
        "解说稿要包含这些内容（按顺序，但用流畅自然的口语连起来，**不要写小标题**）：\n"
        "（a）开场抛一个痛点或反差，15 字以内；\n"
        "（b）引出店里做什么；\n"
        "（c）1–2 个具体的核心卖点，要有细节不要空泛；\n"
        "（d）一个使用场景或客户感受；\n"
        "（e）结尾的行动召唤（来店、私信、地址自然带出）。\n\n"
        "输出要求：直接是可口播的正文，用 {language}，不要章节序号、不要带「第一」「第二」这种连接词。"
    ),
    "testimonial": (
        "请围绕主题写一条短视频解说稿，类型是「客户证言」，**全程用第一人称**，{length} 字以内。\n\n"
        "主题：{topic}\n\n"
        "解说稿要按这个内在节奏（不要写小标题）：\n"
        "（a）我是谁、来自哪里、做了什么（一句话）；\n"
        "（b）之前的困扰或顾虑；\n"
        "（c）选择这家店的理由；\n"
        "（d）现在的效果或体验，要具体；\n"
        "（e）推荐给谁。\n\n"
        "要求：真实自然、不夸张、避免「特别赞」「非常棒」这类空话，用 {language}。"
    ),
    "promotion": (
        "请围绕主题写一条短视频解说稿，类型是「限时促销/活动」，{length} 字以内。\n\n"
        "主题：{topic}\n\n"
        "解说稿的内在节奏（不要写小标题）：\n"
        "（a）开场强紧迫感：限时 / 限量 / 活动名；\n"
        "（b）原价 vs 活动价的对比，有数字；\n"
        "（c）套餐内含什么，要具体；\n"
        "（d）适合谁；\n"
        "（e）截止时间 + 报名/到店方式。\n\n"
        "要求：节奏快、句子短、用 {language}。"
    ),
    "tutorial": (
        "请围绕主题写一条短视频解说稿，类型是「知识科普」，{length} 字以内。\n\n"
        "主题：{topic}\n\n"
        "解说稿的内在节奏（不要写小标题）：\n"
        "（a）开场抛一个误区或常见问题；\n"
        "（b）第一个关键点，要具体可执行；\n"
        "（c）第二个关键点；\n"
        "（d）给一个适用建议；\n"
        "（e）软引到店里咨询或试一下。\n\n"
        "要求：专业但不说教，避免「大家好我是xx」这类开场，用 {language}。"
    ),
    "event": (
        "请围绕主题写一条短视频解说稿，类型是「活动预告」，{length} 字以内。\n\n"
        "主题：{topic}\n\n"
        "解说稿的内在节奏（不要写小标题）：\n"
        "（a）活动名 + 时间 + 地点，一句话讲清；\n"
        "（b）活动核心内容；\n"
        "（c）亮点 1–2 个，告诉观众为什么应该来；\n"
        "（d）报名方式 + 截止时间；\n"
        "（e）友好收尾。\n\n"
        "要求：有期待感、用 {language}。"
    ),
}

_VALID_TEMPLATE_IDS = set(_SCRIPT_TEMPLATES.keys())


@app.post("/generate-script", response_model=GenerateScriptResponse)
def generate_script(req: GenerateScriptRequest):
    """
    Generate video script text via LLM.

    Reuses:
      - services/llm/llm_provider.py :: get_llm_provider()
      - services/llm/*_service.py :: generate_content()

    If req.llm_api_key / llm_base_url / llm_model_name are provided, they
    temporarily override config.yml -> llm.{provider}.* for this call only.

    If req.template_id is one of _SCRIPT_TEMPLATES, a custom PromptTemplate
    is built from it and used in place of the service's default
    topic_prompt_template.
    """
    try:
        provider_name = req.llm_provider or my_config['llm']['provider']

        # 决定脚本结构模板
        template_id = (req.template_id or "general").strip().lower()
        if template_id not in _VALID_TEMPLATE_IDS:
            template_id = "general"

        # Temporarily inject overrides into my_config so that the LLM service
        # constructor (which reads my_config['llm'][provider]['api_key'] etc.)
        # picks them up. Restore after the call.
        llm_cfg = my_config.setdefault('llm', {})
        prov_cfg = llm_cfg.setdefault(provider_name, {})
        backup = {k: prov_cfg.get(k) for k in ("api_key", "base_url", "model_name")}
        try:
            if req.llm_api_key:    prov_cfg["api_key"] = req.llm_api_key
            if req.llm_base_url:   prov_cfg["base_url"] = req.llm_base_url
            if req.llm_model_name: prov_cfg["model_name"] = req.llm_model_name

            llm_service = get_llm_provider(provider_name)

            # 用模板包一个 PromptTemplate 喂给 service，绕开默认的通用模板
            from langchain_core.prompts import PromptTemplate
            topic_prompt_template = PromptTemplate(
                input_variables=["topic", "language", "length"],
                template=_SCRIPT_TEMPLATES[template_id],
            )

            content = llm_service.generate_content(
                req.topic,
                topic_prompt_template,
                req.language,
                req.length,
            )
        finally:
            # restore original values whether we succeed or fail
            for k, v in backup.items():
                if v is None:
                    prov_cfg.pop(k, None)
                else:
                    prov_cfg[k] = v

        # Clean up LLM output: strip markdown formatting, headers, etc.
        import re as _re
        clean = content
        clean = _re.sub(r'#{1,6}\s*.*?\n', '', clean)          # remove ### headers
        clean = _re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', clean) # remove **bold** / *italic*
        clean = _re.sub(r'[-–—]\s*', '', clean)                 # remove list bullets
        clean = _re.sub(r'\n{2,}', '\n', clean)                 # collapse blank lines
        clean = _re.sub(r'[(（].*?字.*?[)）]', '', clean)       # remove "(约XXX字)" notes
        clean = clean.strip()
        content = clean

        # Generate keywords
        keywords = llm_service.generate_content(
            content,
            prompt_template=llm_service.keyword_prompt_template,
        )

        # 追加：把脚本切分成 segments + 推断 suggested_scenes
        # 失败不致命（内部函数已自带 fallback：返回 1 段 general）
        llm_overrides = {
            "api_key": req.llm_api_key,
            "base_url": req.llm_base_url,
            "model_name": req.llm_model_name,
        }
        segments, suggested_scenes = _segment_script_internal(
            content.strip(),
            template_id=template_id,
            available_scenes=req.available_scenes,
            llm_overrides=llm_overrides,
            provider_name=provider_name,
        )

        return GenerateScriptResponse(
            content=content.strip(),
            keywords=keywords.strip(),
            template_id=template_id,
            segments=segments,
            suggested_scenes=suggested_scenes,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/segment-script", response_model=SegmentScriptResponse)
def segment_script(req: SegmentScriptRequest):
    """
    把已经生成（或被用户编辑过）的脚本重新切分成 segments。

    前端在「重新分镜」按钮 / textarea 编辑后再跑 stage 2-6 之前调用。
    用法和 /generate-script 内部追加的分镜步骤一致，只是对外暴露 + 不重新出脚本。
    """
    try:
        script = (req.script or "").strip()
        if not script:
            raise HTTPException(status_code=400, detail="script 不能为空")

        provider_name = req.llm_provider or my_config.get('llm', {}).get('provider')
        llm_overrides = {
            "api_key": req.llm_api_key,
            "base_url": req.llm_base_url,
            "model_name": req.llm_model_name,
        }
        segments, suggested_scenes = _segment_script_internal(
            script,
            template_id=req.template_id or "general",
            available_scenes=req.available_scenes,
            llm_overrides=llm_overrides,
            provider_name=provider_name,
        )
        return SegmentScriptResponse(
            segments=segments,
            suggested_scenes=suggested_scenes,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========================== /wizard/chat ==========================

# 系统 prompt：给 LLM 解释它的角色 + 字段约束 + 终止协议
_WIZARD_SYSTEM_PROMPT = """你是「影刀短视频工作台」的智能向导，帮一个本地服务行业（餐饮 / 美容 / 零售 / 教育 / 家政 / 健身 等）的店主，通过最多 6 轮简短对话，收集生成一条短视频所需的核心信息。

# 你需要收集的字段
- topic：视频主题，一句话（包含业务 + 这条视频的核心内容），例如「夏季美白护理疗程种草」
- intro：必须出现在视频里的具体信息（门店地址、电话、活动截止日期、限时优惠 等），如果用户没提就留空字符串
- length：脚本字数，按用户期望的视频时长换算：30 秒 ≈ 200，45 秒 ≈ 300，60 秒 ≈ 400，90 秒 ≈ 600。返回字符串，不带单位
- language：固定 「zh-CN」
- style_hint：风格暗示，从这些里挑一个或自由组合：「快节奏种草」「故事化叙事」「教学科普」「客户证言」「价格促销」「活动预告」
- template_id：脚本结构模板。从下面 6 个里挑一个：
  · general —— 通用解说，不确定时用这个
  · promo —— 产品种草 / 服务种草（强调卖点和适合人群）
  · testimonial —— 客户证言（第一人称、有真实改善体验）
  · promotion —— 限时促销（强调价格、优惠、截止日期）
  · tutorial —— 知识科普 / 教学（讲一个误区或干货）
  · event —— 活动预告（活动名、时间、地点、报名方式）
  按用户的回答推断最合适的一个，不要直接把这些英文 id 念给用户听。

# 对话规则
1. 每轮只问 1 个问题，简短自然，不要给一堆并列选项让用户挑。
2. 如果用户的回答已经能推断出某个字段，就不要重复问。
3. 优先问最有信息密度的：业务和主题 → 这条视频的目的（种草 / 促销 / 客户证言 / 活动 / 干货 / 单纯介绍）→ 想给谁看 → 想突出什么 → 时长 → 必须出现的信息。
4. 用户回答非常短时，主动用一句话把推断的细节补出来让用户确认。
5. 最多 6 轮（用户消息数 ≤ 6）。即使信息不全也要在第 6 轮强制结束 —— 缺失的字段用合理的默认值填上（template_id 不确定就填 general）。

# 终止协议（非常重要）
当你认为信息够了、或者已经走完第 6 轮，必须按下面的格式结束。最后一条回复严格遵守：

先用一两句话总结你收集到的信息 + 告诉用户「已经准备好，可以开始生成了」+ 顺便告诉他应该建哪些场景目录（建议 4-6 个 kebab-case 英文名）。
然后另起一行，输出严格的标记包裹的 JSON：

###FIELDS###
{"topic": "...", "intro": "...", "length": "500", "language": "zh-CN", "style_hint": "...", "template_id": "general", "suggested_scene_dirs": ["store-front", "skincare-process", "customer-smile"]}
###END###

JSON 必须是合法的 UTF-8 JSON，所有字段都要有（intro / style_hint 可以是空字符串，suggested_scene_dirs 至少给 3 个），length 必须是字符串，template_id 必须是上面 6 个英文 id 之一。

# suggested_scene_dirs 怎么选
按 template_id 给典型场景名（英文 kebab-case）：
- promo（产品种草）→ store-front, product-closeup, before-after, customer-reaction
- testimonial（客户证言）→ customer-portrait, customer-using, results, store-front
- promotion（限时促销）→ store-front, promo-board, busy-store, price-tag
- tutorial（知识科普）→ host-talking, demo-process, infographic, store-front
- event（活动预告）→ event-poster, venue, host-talking, crowd
- general → store-front, daily-operation, customer-interaction

不要硬塞，根据用户的具体业务调整。

# 不要做的事
- 不要写超过 100 字的回复（用户在手机上看，太长会烦）
- 不要在 ###FIELDS### 之前或之后追加 markdown 标题、列表符号
- 不要把示例占位符直接放进 JSON
"""


def _llm_chat(provider_name, messages, overrides=None, max_tokens=600, temperature=0.4):
    """
    Run a single OpenAI-compatible chat completion using the provider config
    from my_config['llm'][provider_name], with optional runtime overrides.

    Supports: DeepSeek, Moonshot, OpenAI, Tongyi, Ollama (all OpenAI-compatible).
    Azure / Qianfan / Baichuan use proprietary SDKs and aren't supported here yet.

    `messages` is a list of {"role": ..., "content": ...} dicts, system prompt already
    included by the caller.
    """
    from openai import OpenAI  # lazy import; same SDK used by deepseek_service.py

    incompatible = {"Azure", "Qianfan", "Baichuan"}
    if provider_name in incompatible:
        raise HTTPException(
            status_code=400,
            detail=(
                f"向导功能暂未支持 {provider_name}（接口非 OpenAI 兼容）。"
                "请切换到 DeepSeek / Moonshot / OpenAI / Tongyi / Ollama 之一。"
            ),
        )

    llm_cfg = my_config.setdefault('llm', {})
    prov_cfg = llm_cfg.setdefault(provider_name, {})
    backup = {k: prov_cfg.get(k) for k in ("api_key", "base_url", "model_name")}
    try:
        if overrides:
            if overrides.get("api_key"):    prov_cfg["api_key"] = overrides["api_key"]
            if overrides.get("base_url"):   prov_cfg["base_url"] = overrides["base_url"]
            if overrides.get("model_name"): prov_cfg["model_name"] = overrides["model_name"]
        api_key = prov_cfg.get("api_key")
        base_url = prov_cfg.get("base_url")
        model_name = prov_cfg.get("model_name")
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail=f"未找到 {provider_name} 的 api_key（既不在 config.yml 也没从前端传入）",
            )
        if not model_name:
            raise HTTPException(
                status_code=400,
                detail=f"未找到 {provider_name} 的 model_name",
            )

        client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False,
        )
        return resp.choices[0].message.content or ""
    finally:
        for k, v in backup.items():
            if v is None:
                prov_cfg.pop(k, None)
            else:
                prov_cfg[k] = v


_FIELDS_RE = re.compile(
    r"###FIELDS###\s*(\{.*?\})\s*###END###",
    re.DOTALL,
)

_SEGMENTS_RE = re.compile(
    r"###SEGMENTS###\s*(\{.*?\})\s*###END###",
    re.DOTALL,
)


def _kebab_normalize(name: str) -> str:
    """
    把任意目录名规整成可以用来比较的 key：
    - 小写
    - 非字母数字下划线连字符 → 连字符
    - 多个连字符合并
    - 首尾连字符去掉
    用于 scene_hint 匹配时的容错对比（"Store-Front" / "store_front" / "store-front" 视为同一个）。
    中文字符保留（这样中文目录也能匹配，但匹配精度受 LLM 输出一致性影响）。
    """
    if not name:
        return ""
    s = name.strip().lower()
    s = re.sub(r"[\s/\\.]+", "-", s)
    s = re.sub(r"[^\w一-鿿-]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


_SEGMENT_SYSTEM_PROMPT = """你是「影刀短视频工作台」的分镜助手。任务：把一段中文短视频解说稿按口播节奏切成 6-12 段，每段绑一个 scene_hint（场景目录名），交给混剪器知道这一句应该配什么画面。

# scene_hint 规则（非常重要）
- 用户当前已经建好的目录会通过 `已有场景目录` 列表给你
- 你的 scene_hint **优先**从这个列表里挑（精确写法不变，照抄）
- 列表里**没有**合适的，才起一个新的 kebab-case 英文名（如 store-front / customer-smile / product-closeup / before-after），写进返回的 suggested_scenes 列表里，提醒用户「你应该补建这些目录」
- 不要在 scene_hint 里写中文，除非「已有场景目录」里就是中文（那就照抄）

# 切分原则
1. 一段 = 1-3 个完整的句子，对应 3-8 秒的画面（口播节奏）
2. 每段的 text 要是原脚本里**连续的、未改动的文字**，不要重写也不要省略，把整篇脚本拼起来要等于原文
3. 主题切换 / 节奏变化 / 强调点的地方要切段
4. 短视频通常 6-10 段比较合适，最少 4 段，最多 12 段

# 输出协议（严格）
先用一两句话说明你的切分思路，再另起一行输出：

###SEGMENTS###
{"segments": [{"text": "句子1", "scene_hint": "store-front"}, ...], "suggested_scenes": ["before-after"]}
###END###

JSON 必须合法 UTF-8。segments 数组里每个 element 必须有 text 和 scene_hint 两个字符串字段。suggested_scenes 可以是空数组 []。
"""


def _segment_script_internal(
    content: str,
    template_id: str = "general",
    available_scenes=None,
    llm_overrides=None,
    provider_name=None,
):
    """
    Run a single LLM call to split `content` into N segments, each with a scene_hint.

    Returns: (segments_list, suggested_scenes_list)
      - segments_list: List[ScriptSegment]
      - suggested_scenes_list: List[str] (LLM 推荐用户补建的目录，可能为空)

    解析失败时降级：整段脚本作为 1 个 segment，scene_hint = "general"，不抛错
    （分镜失败不应该让 stage 1 整体失败）。
    """
    available_scenes = available_scenes or []
    provider_name = provider_name or my_config.get('llm', {}).get('provider')
    if not provider_name:
        # 没 provider 就 fallback，不抛
        return [ScriptSegment(text=content.strip(), scene_hint="general")], []

    user_msg = (
        f"脚本模板类型：{template_id}\n"
        f"已有场景目录：{available_scenes if available_scenes else '（用户还没建任何目录，全部 scene_hint 写到 suggested_scenes 里）'}\n\n"
        f"脚本：\n{content.strip()}"
    )
    messages = [
        {"role": "system", "content": _SEGMENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    try:
        reply = _llm_chat(
            provider_name,
            messages,
            overrides=llm_overrides or {},
            max_tokens=1500,
            temperature=0.3,
        )
    except Exception as e:
        print(f"WARNING: _segment_script_internal LLM call failed: {e}")
        return [ScriptSegment(text=content.strip(), scene_hint="general")], []

    m = _SEGMENTS_RE.search(reply or "")
    if not m:
        print(f"WARNING: _segment_script_internal: no ###SEGMENTS### block in reply, falling back")
        return [ScriptSegment(text=content.strip(), scene_hint="general")], []

    try:
        import json as _json
        parsed = _json.loads(m.group(1))
        raw_segments = parsed.get("segments", [])
        raw_suggested = parsed.get("suggested_scenes", []) or []
        segments = []
        for seg in raw_segments:
            text = (seg.get("text") or "").strip()
            hint = (seg.get("scene_hint") or "general").strip() or "general"
            if text:
                segments.append(ScriptSegment(text=text, scene_hint=hint))
        if not segments:
            return [ScriptSegment(text=content.strip(), scene_hint="general")], []
        # 去重保持顺序
        seen = set()
        suggested = []
        for s in raw_suggested:
            s = (s or "").strip()
            if s and s not in seen:
                seen.add(s)
                suggested.append(s)
        return segments, suggested
    except Exception as e:
        print(f"WARNING: _segment_script_internal: parse failed: {e}")
        return [ScriptSegment(text=content.strip(), scene_hint="general")], []


def _parse_wizard_fields(reply_text):
    """
    Try to extract the ###FIELDS### { ... } ###END### block from the LLM reply.
    Returns (clean_reply_without_markers, fields_dict_or_None).
    """
    m = _FIELDS_RE.search(reply_text)
    if not m:
        return reply_text, None
    raw_json = m.group(1)
    try:
        import json as _json
        fields = _json.loads(raw_json)
    except Exception:
        return reply_text, None
    # 把标记块从展示给用户的 reply 里剥掉，只留前面的总结句
    clean = _FIELDS_RE.sub("", reply_text).strip()
    return clean, fields


@app.post("/wizard/chat", response_model=WizardChatResponse)
def wizard_chat(req: WizardChatRequest):
    """
    AI 多轮对话向导：用户/助手交替发消息，最多 6 轮内收集完字段后吐 JSON。
    前端传完整 messages 历史（不含 system），后端拼上系统 prompt 后调 LLM。
    """
    # 防御：超长 history 直接拒绝，避免 token 爆炸
    if len(req.messages) > 30:
        raise HTTPException(status_code=400, detail="对话历史过长，请重置向导后重新开始")

    # 统计用户回合数（用来给前端做进度，也作为强制终止的硬上限）
    user_rounds = sum(1 for m in req.messages if m.role == "user")

    provider_name = req.llm_provider or my_config.get('llm', {}).get('provider')
    if not provider_name:
        raise HTTPException(status_code=400, detail="未指定 LLM provider")

    # 构造发给 LLM 的消息：system + history
    sys_content = _WIZARD_SYSTEM_PROMPT
    if user_rounds >= 6:
        # 已经到第 6 轮了，最后一次必须强制终止
        sys_content += (
            "\n\n# 当前状态\n"
            "用户已经回答了 6 轮，这是最后一次回复。不要再问问题，"
            "立即用合理默认值补全缺失字段并输出 ###FIELDS### 标记。"
        )

    llm_messages = [{"role": "system", "content": sys_content}]
    for m in req.messages:
        if m.role not in ("user", "assistant"):
            continue
        llm_messages.append({"role": m.role, "content": m.content})

    # 如果是开场（history 里只有用户的"开始"伪消息或空），让 LLM 主动问第一个问题
    # 前端约定：用户点"开始向导"会发一个 role=user, content="__start__" 的伪消息

    overrides = {
        "api_key": req.llm_api_key,
        "base_url": req.llm_base_url,
        "model_name": req.llm_model_name,
    }

    try:
        reply_raw = _llm_chat(provider_name, llm_messages, overrides=overrides)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 调用失败：{e}")

    clean_reply, fields_dict = _parse_wizard_fields(reply_raw)

    if fields_dict is not None:
        # 兜底：language 必须是 zh-CN（让前端不用做这层防御）
        fields_dict.setdefault("language", req.language or "zh-CN")
        fields_dict.setdefault("intro", "")
        fields_dict.setdefault("style_hint", "")
        fields_dict.setdefault("length", "500")
        try:
            fields_obj = WizardFields(**fields_dict)
        except Exception as e:
            # JSON 解析了但字段不对 —— 当作"还没完成"，让用户/LLM 再来一轮
            return WizardChatResponse(
                done=False,
                reply=f"（向导回复格式有误，请再回答一次：{e}）\n\n{clean_reply or reply_raw}",
                fields=None,
                rounds=user_rounds,
            )
        return WizardChatResponse(
            done=True,
            reply=clean_reply or "已为你收集好所有信息，准备开始生成。",
            fields=fields_obj,
            rounds=user_rounds,
        )

    return WizardChatResponse(
        done=False,
        reply=clean_reply or reply_raw,
        fields=None,
        rounds=user_rounds,
    )


@app.post("/generate-audio", response_model=GenerateAudioResponse)
def generate_audio(req: GenerateAudioRequest):
    """
    Generate TTS audio from text.

    Reuses:
      - Remote: services/audio/{azure,alitts,tencent_tts}_service.py :: save_with_ssml()
      - Local: services/audio/{chattts,gptsovits,cosyvoice}_service.py :: chat_with_content()
      - tools/utils.py :: extent_audio() (pad 2s silence)
    """
    try:
        # Determine output path
        if req.output_filename:
            audio_output_file = os.path.join(WORK_DIR, req.output_filename)
        else:
            audio_output_file = os.path.join(WORK_DIR, f"{random_with_system_time()}.wav")

        if req.tts_type == "remote":
            audio_service = _get_remote_audio_service(req.provider)
            if not req.voice:
                raise HTTPException(status_code=400, detail="voice is required for remote TTS")
            audio_service.save_with_ssml(req.text, audio_output_file, req.voice, req.rate)

        elif req.tts_type == "local":
            params = req.local_tts_params or LocalTTSParams()
            audio_service = _create_local_tts_service(req.provider, params)
            audio_service.chat_with_content(req.text, audio_output_file)

        else:
            raise HTTPException(status_code=400, detail=f"Unknown tts_type: {req.tts_type}")

        # Pad 2s silence at the end to avoid abrupt cutoff
        extent_audio(audio_output_file, 2)

        # Get duration
        duration = get_audio_duration(audio_output_file)

        return GenerateAudioResponse(
            audio_file=os.path.abspath(audio_output_file),
            duration_seconds=duration,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-subtitle", response_model=GenerateSubtitleResponse)
def generate_subtitle(req: GenerateSubtitleRequest):
    """
    Generate SRT subtitle file from audio via speech recognition.

    Reuses:
      - services/audio/faster_whisper_recognition_service.py :: process()
      - services/audio/sensevoice_whisper_recognition_service.py :: process()
      - services/captioning/common_captioning_service.py :: Captioning
      - services/captioning/caption_helper.py :: CaptionHelper
    """
    try:
        if not os.path.exists(req.audio_file):
            raise HTTPException(status_code=400, detail=f"Audio file not found: {req.audio_file}")

        # Determine output path
        if req.output_filename:
            output_file = os.path.join(WORK_DIR, req.output_filename)
        else:
            output_file = os.path.join(WORK_DIR, f"{random_with_system_time()}.srt")

        # Run ASR
        results = _run_asr(req.audio_file, req.language, req.recognition_type, req.recognition_provider)
        if not results:
            raise HTTPException(status_code=500, detail="Speech recognition returned no results")

        # Generate SRT -- direct write using actual result attributes
        # FasterWhisperRecognitionResult has: .text, .begin_time, .end_time
        # SenseVoiceRecognitionResult may differ; we try multiple attr names
        def _format_srt_time(seconds):
            seconds = float(seconds)
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            ms = int((seconds % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        def _get_time(r, start_attrs, end_attrs):
            start = 0
            end = 5
            for attr in start_attrs:
                v = getattr(r, attr, None)
                if v is not None:
                    start = float(v)
                    break
            for attr in end_attrs:
                v = getattr(r, attr, None)
                if v is not None:
                    end = float(v)
                    break
            return start, end

        with open(output_file, 'w', encoding='utf-8') as f:
            line_count = 0
            for idx, r in enumerate(results, 1):
                start, end = _get_time(
                    r,
                    ['begin_time', 'start', 'offset'],
                    ['end_time', 'end']
                )
                text_val = getattr(r, 'text', '') or getattr(r, 'result', '') or ''
                text_val = text_val.strip()
                if text_val:
                    line_count += 1
                    f.write(f"{line_count}\n")
                    f.write(f"{_format_srt_time(start)} --> {_format_srt_time(end)}\n")
                    f.write(f"{text_val}\n\n")

        print(f"SRT written: {output_file} ({len(results)} segments, {line_count} non-empty lines)")

        # 显式抛错而不是默默返回空 SRT —— 上游 add_subtitles 会跳过，导致最终视频"看起来正常但没字幕"
        if line_count == 0:
            raise HTTPException(
                status_code=500,
                detail=(
                    "ASR 没有识别出任何字幕内容。常见原因："
                    "（1）音频质量过低 / 全静音；"
                    f"（2）language='{req.language}' 与音频实际语言不匹配；"
                    "（3）ASR 模型未正确加载。"
                    f"原始 ASR 返回 {len(results)} 段，但全部 text 为空。"
                ),
            )

        return GenerateSubtitleResponse(
            subtitle_file=os.path.abspath(output_file),
            line_count=line_count,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/mix-video", response_model=MixVideoResponse)
def mix_video(req: MixVideoRequest):
    """
    Core video mixing endpoint. Takes media scenes + audio + config, outputs mp4.

    Reuses:
      - services/video/video_service.py :: VideoMixService.match_videos_from_dir()
      - services/video/video_service.py :: VideoService.normalize_video()
      - services/video/video_service.py :: VideoService.generate_video_with_audio()
      - services/video/video_service.py :: add_background_music()
      - services/video/texiao_service.py :: gen_filter()
      - services/hunjian/hunjian_service.py :: concat_audio_list()
      - services/captioning/captioning_service.py :: add_subtitles()
    """
    try:
        vc = req.video_config

        if not os.path.exists(req.audio_file):
            raise HTTPException(status_code=400, detail=f"Audio file not found: {req.audio_file}")

        # ---- Step 0: Auto-detect resolution from first video ----
        import random
        import math

        all_scene_files = []
        for scene in req.scenes:
            if os.path.isdir(scene.media_dir):
                for f in os.listdir(scene.media_dir):
                    if f.lower().endswith(('.mp4', '.mov')):
                        all_scene_files.append(os.path.join(scene.media_dir, f))

        if not all_scene_files:
            raise HTTPException(status_code=400, detail="No video files found in scene directories")

        # Auto-detect: use first video's dimensions if width/height are 0
        if vc.width == 0 or vc.height == 0:
            probe_cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=width,height",
                         "-of", "csv=s=x:p=0", all_scene_files[0]]
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
            dims = probe_result.stdout.strip().split('x')
            if len(dims) == 2:
                vc.width = int(dims[0])
                vc.height = int(dims[1])
                print(f"Auto-detected resolution: {vc.width}x{vc.height}")
            else:
                vc.width = 1280
                vc.height = 720
                print(f"Could not detect resolution, defaulting to {vc.width}x{vc.height}")

        # ---- Step 0b: Generate intro clip if intro_text is provided ----
        intro_clip = None
        if vc.intro_text:
            intro_clip = os.path.join(WORK_DIR, f"intro-{random_with_system_time()}.mp4")
            # Create a 3-second black clip with white centered text
            intro_cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"color=c=black:s={vc.width}x{vc.height}:d=3:r={vc.fps}",
                "-vf", (
                    f"drawtext=text='{vc.intro_text}'"
                    f":fontsize={max(24, vc.height // 30)}"
                    f":fontcolor=white"
                    f":fontfile=C\\\\:/Windows/Fonts/msyh.ttc"
                    f":x=(w-text_w)/2:y=(h-text_h)/2"
                ),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-t", "3",
                intro_clip
            ]
            result = subprocess.run(intro_cmd, capture_output=True)
            if os.path.exists(intro_clip) and os.path.getsize(intro_clip) > 1000:
                print(f"Intro clip created: {intro_clip}")
            else:
                print(f"Intro clip failed, skipping. stderr: {result.stderr[-200:]}")
                intro_clip = None

        # ---- Step 1: Match videos from each scene directory ----
        video_mix_svc = _build_video_mix_service(vc)
        all_matching_videos = []

        audio_duration = get_audio_duration(req.audio_file)
        if audio_duration is None:
            raise HTTPException(status_code=500, detail="Cannot determine audio duration")

        # Reserve time for intro clip
        target_duration = audio_duration
        if intro_clip:
            target_duration = max(0, audio_duration - 3)

        # 校验目录存在
        for scene in req.scenes:
            if not os.path.isdir(scene.media_dir):
                raise HTTPException(status_code=400, detail=f"Scene media_dir not found: {scene.media_dir}")

        # 预扫描每个目录里的媒体文件，建立 scene_key → file_list 索引
        # scene_key 用规范化的目录最后一段（kebab-case 容错）
        scene_index = {}        # normalized_name → List[file_path]
        scene_label = {}        # normalized_name → 原始目录名（展示用）
        all_pool = []           # 所有目录的合并池（fallback 用）
        for scene in req.scenes:
            base = os.path.basename(scene.media_dir.rstrip("/\\"))
            key = _kebab_normalize(base)
            files = [
                os.path.join(scene.media_dir, f) for f in os.listdir(scene.media_dir)
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.mp4', '.mov'))
            ]
            random.shuffle(files)
            scene_index.setdefault(key, []).extend(files)
            scene_label.setdefault(key, base)
            all_pool.extend(files)
        random.shuffle(all_pool)

        def _pick_clip_from(file_list):
            """从给定文件池取下一个未使用的视频/图片，返回 (path, normalized_duration) 或 (None, 0)"""
            for mf in list(file_list):
                if mf in all_matching_videos:
                    continue
                if mf.lower().endswith(('.jpg', '.jpeg', '.png')):
                    return mf, max(5, vc.segment_min_length)
                dur = get_video_duration(mf) or 5
                return mf, max(vc.segment_min_length, min(dur, vc.segment_max_length))
            return None, 0

        total_collected_duration = 0.0

        if req.segments:
            # —— 方案 A：按 segment 顺序选片，scene_hint 命中目录则从该目录取，否则走通用池 ——
            for seg in req.segments:
                if total_collected_duration >= target_duration:
                    break
                hint_key = _kebab_normalize(seg.scene_hint)
                pool = scene_index.get(hint_key) or []
                pick, dur = _pick_clip_from(pool)
                if pick is None:
                    # fallback：通用池
                    pick, dur = _pick_clip_from(all_pool)
                if pick is None:
                    # 真的一个都没有了（所有目录都被抽空），跳过这段
                    print(f"WARNING: mix-video: no clip available for segment '{seg.text[:20]}...'")
                    continue
                if vc.enable_video_transition_effect and len(all_matching_videos) > 0:
                    total_collected_duration += dur - vc.video_transition_effect_duration
                else:
                    total_collected_duration += dur
                all_matching_videos.append(pick)

            # 段数走完但时长不够 → 从通用池接着补，保证视频不短于音频
            while total_collected_duration < target_duration:
                pick, dur = _pick_clip_from(all_pool)
                if pick is None:
                    break
                if vc.enable_video_transition_effect and len(all_matching_videos) > 0:
                    total_collected_duration += dur - vc.video_transition_effect_duration
                else:
                    total_collected_duration += dur
                all_matching_videos.append(pick)
        else:
            # —— 老逻辑：按目录顺序遍历，凑够时长就停 ——
            for i, scene in enumerate(req.scenes):
                media_files = [
                    os.path.join(scene.media_dir, f) for f in os.listdir(scene.media_dir)
                    if f.lower().endswith(('.jpg', '.jpeg', '.png', '.mp4', '.mov'))
                ]
                random.shuffle(media_files)

                video_files = [f for f in media_files if f.lower().endswith(('.mp4', '.mov'))]
                if video_files:
                    first_video = random.choice(video_files)
                    media_files.remove(first_video)
                    media_files.insert(0, first_video)

                for mf in media_files:
                    if total_collected_duration >= target_duration:
                        break

                    if mf.lower().endswith(('.jpg', '.jpeg', '.png')):
                        dur = max(5, vc.segment_min_length)
                    else:
                        dur = get_video_duration(mf) or 5
                        dur = max(vc.segment_min_length, min(dur, vc.segment_max_length))

                    if vc.enable_video_transition_effect and len(all_matching_videos) > 0:
                        total_collected_duration += dur - vc.video_transition_effect_duration
                    else:
                        total_collected_duration += dur

                    all_matching_videos.append(mf)

                if total_collected_duration >= target_duration:
                    break

        if not all_matching_videos:
            raise HTTPException(status_code=400, detail="No media files found in scene directories")

        # Prepend intro clip
        if intro_clip:
            all_matching_videos.insert(0, intro_clip)

        # Pad audio if video is slightly short
        total_with_intro = total_collected_duration + (3 if intro_clip else 0)
        if total_with_intro < audio_duration:
            pad = int(math.ceil(audio_duration - total_with_intro))
            if pad > 0:
                extent_audio(req.audio_file, pad)

        # ---- Step 2: Normalize all video clips ----
        video_svc = _build_video_service(all_matching_videos, req.audio_file, vc)
        video_svc.normalize_video()

        # ---- Step 3: Concatenate + add audio + transition effects ----
        video_file = video_svc.generate_video_with_audio()

        # ---- Step 4: Burn subtitles (if provided) ----
        if req.subtitle_file and req.subtitle_config and req.subtitle_config.enable:
            srt_path = req.subtitle_file
            if os.path.exists(srt_path):
                sc = req.subtitle_config
                add_subtitles(
                    video_file,
                    srt_path,
                    font_name=sc.font_name,
                    font_size=sc.font_size,
                    primary_colour=sc.color,
                    outline_colour=sc.border_color,
                    outline=sc.border_width,
                    alignment=sc.position,
                )
            else:
                print(f"WARNING: subtitle file not found at {srt_path}, skipping subtitles")

        # Get final duration
        final_duration = get_video_duration(video_file)

        return MixVideoResponse(
            video_file=os.path.abspath(video_file),
            duration_seconds=final_duration,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-cover", response_model=GenerateCoverResponse)
def generate_cover(req: GenerateCoverRequest):
    """
    Extract a cover image from a video file.

    New implementation (single ffmpeg command).
    """
    try:
        if not os.path.exists(req.video_file):
            raise HTTPException(status_code=400, detail=f"Video file not found: {req.video_file}")

        cover_file = os.path.join(FINAL_DIR, f"cover-{random_with_system_time()}.jpg")

        cmd = [
            "ffmpeg",
            "-i", req.video_file,
            "-ss", req.timestamp,
            "-vframes", "1",
            "-vf", f"scale={req.width}:{req.height}:force_original_aspect_ratio=decrease,pad={req.width}:{req.height}:(ow-iw)/2:(oh-ih)/2",
            "-q:v", "2",
            "-y",
            cover_file,
        ]
        result = subprocess.run(cmd, capture_output=True)
        if not os.path.exists(cover_file):
            raise HTTPException(status_code=500, detail="ffmpeg failed to generate cover")

        return GenerateCoverResponse(cover_file=os.path.abspath(cover_file))

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stock/status", response_model=StockStatusResponse)
def stock_status():
    return StockStatusResponse(
        pexels={
            "configured": bool(os.environ.get("PEXELS_API_KEY") or os.environ.get("SHADOWBLADE_PEXELS_KEY")),
            "hint": "Set PEXELS_API_KEY or SHADOWBLADE_PEXELS_KEY for Pexels.",
        },
        ytdlp={
            "configured": shutil.which("yt-dlp") is not None or (Path(sys.executable).parent / "yt-dlp").exists(),
            "hint": "Install with pip install yt-dlp.",
        },
    )


@app.post("/stock/from-url", response_model=StockFromUrlResponse)
def stock_from_url(req: StockFromUrlRequest):
    try:
        out_dir = _stock_dir("ytdlp")
        produced, meta, info = _run_ytdlp(
            req.url,
            out_dir,
            sections=req.sections,
            max_height=req.max_height,
            filename_hint=f"url-{random_with_system_time()}",
        )
        duration = float((info.get("format") or {}).get("duration") or meta.get("duration") or 0) or None
        return StockFromUrlResponse(
            path=os.path.abspath(produced),
            directory=os.path.abspath(out_dir),
            title=str(meta.get("title") or Path(produced).stem),
            duration=duration,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/stock/search", response_model=StockSearchResponse)
def stock_search(req: StockSearchRequest):
    try:
        out_dir = _stock_dir("search")
        paths = []
        titles = []
        sources = []
        try:
            entries = _ytdlp_search_entries(req.keyword, req.count + 4)
            for index, entry in enumerate(entries):
                if len(paths) >= req.count:
                    break
                produced, meta, _info = _run_ytdlp(
                    entry["url"],
                    out_dir,
                    sections=f"*0:00-0:{int(req.max_seconds):02d}",
                    max_height=720,
                    filename_hint=f"yt-{_safe_stock_slug(entry['id'], str(index))}-{random_with_system_time()}",
                )
                paths.append(os.path.abspath(produced))
                titles.append(str(meta.get("title") or entry["title"] or Path(produced).stem))
                sources.append("youtube")
        except Exception as ytdlp_error:
            logger.warning(f"yt-dlp keyword search failed, falling back to archive.org: {ytdlp_error}")

        if len(paths) < req.count:
            archive_paths, archive_titles = _archive_search(req.keyword, req.count - len(paths), out_dir, req.max_seconds)
            paths.extend(archive_paths)
            titles.extend(archive_titles)
            sources.extend(["archive"] * len(archive_paths))

        if not paths:
            raise RuntimeError(f"No stock footage found for keyword: {req.keyword}")

        return StockSearchResponse(
            keyword=req.keyword,
            directory=os.path.abspath(out_dir),
            paths=paths,
            titles=titles,
            sources=sources,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/stock/pexels/auto", response_model=PexelsAutoResponse)
async def stock_pexels_auto(req: PexelsAutoRequest):
    try:
        directory, paths, photographers = await _pexels_auto_download(
            req.query,
            req.count,
            req.orientation,
            req.api_key,
        )
        return PexelsAutoResponse(
            query=req.query,
            directory=os.path.abspath(directory),
            paths=paths,
            photographers=photographers,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========================== /smart-pad ==========================

class SmartPadRequest(BaseModel):
    keywords: List[str] = Field(default_factory=list)
    target_seconds: float = 60.0
    existing_dirs: List[str] = Field(default_factory=list)
    provider: str = "pexels"        # pexels | pixabay
    orientation: str = "portrait"   # pexels only
    api_key: Optional[str] = None   # override config.yml if set


class SmartPadResponse(BaseModel):
    needed: bool
    existing_seconds: float
    target_seconds: float
    stock_dir: Optional[str] = None
    downloaded: int = 0
    downloaded_seconds: float = 0
    files: List[str] = Field(default_factory=list)
    skipped_reasons: List[str] = Field(default_factory=list)


def _measure_dir_seconds(d: str) -> float:
    """Sum video duration in a directory; images count as 5s placeholder."""
    if not os.path.isdir(d):
        return 0.0
    total = 0.0
    for fn in os.listdir(d):
        path = os.path.join(d, fn)
        low = fn.lower()
        if low.endswith((".mp4", ".mov", ".mkv", ".webm")):
            total += get_video_duration(path) or 0.0
        elif low.endswith((".jpg", ".jpeg", ".png")):
            total += 5.0
    return total


@app.post("/smart-pad", response_model=SmartPadResponse)
def smart_pad(req: SmartPadRequest):
    """
    If existing_dirs total footage < target_seconds, search & download
    stock footage to a fresh dir under WORK_DIR/stock-<ts>/ until quota met.
    """
    try:
        existing_seconds = sum(_measure_dir_seconds(d) for d in req.existing_dirs)
        gap = req.target_seconds - existing_seconds

        if gap <= 0:
            return SmartPadResponse(
                needed=False,
                existing_seconds=existing_seconds,
                target_seconds=req.target_seconds,
            )

        # resolve api key
        api_key = req.api_key
        if not api_key:
            cfg = my_config.get("resource", {}) or {}
            prov_cfg = cfg.get(req.provider, {}) or {}
            api_key = prov_cfg.get("api_key")
            if api_key in (None, "", "API_KEY"):
                raise HTTPException(
                    status_code=400,
                    detail=f"resource.{req.provider}.api_key is not set in config.yml. "
                           f"Get one free at https://www.{req.provider}.com/api/",
                )

        out_dir = os.path.join(WORK_DIR, f"stock-{random_with_system_time()}")

        try:
            result = fetch_stock_footage(
                keywords=req.keywords,
                target_seconds=gap * 1.2,  # over-fetch 20%
                out_dir=out_dir,
                provider=req.provider,
                api_key=api_key,
                orientation=req.orientation,
            )
        except StockProviderError as e:
            raise HTTPException(status_code=502, detail=str(e))

        return SmartPadResponse(
            needed=True,
            existing_seconds=existing_seconds,
            target_seconds=req.target_seconds,
            stock_dir=os.path.abspath(out_dir),
            downloaded=result["downloaded"],
            downloaded_seconds=result["total_duration"],
            files=result["files"],
            skipped_reasons=result["skipped_reasons"],
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========================== ENTRY POINT ==========================

if __name__ == "__main__":
    uvicorn.run(
        "app.worker:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
