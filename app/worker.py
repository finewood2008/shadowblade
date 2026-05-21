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
import subprocess
import logging
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
os.makedirs(WORK_DIR, exist_ok=True)
os.makedirs(FINAL_DIR, exist_ok=True)

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
from tools.utils import random_with_system_time, run_ffmpeg_command, extent_audio
from tools.file_utils import generate_temp_filename

# ---------------------------------------------------------------------------
# 4. FASTAPI APP
# ---------------------------------------------------------------------------

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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

class GenerateScriptResponse(BaseModel):
    content: str
    keywords: str

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


@app.post("/generate-script", response_model=GenerateScriptResponse)
def generate_script(req: GenerateScriptRequest):
    """
    Generate video script text via LLM.

    Reuses:
      - services/llm/llm_provider.py :: get_llm_provider()
      - services/llm/*_service.py :: generate_content()
    """
    try:
        provider_name = req.llm_provider or my_config['llm']['provider']
        llm_service = get_llm_provider(provider_name)

        # Generate main content
        content = llm_service.generate_content(
            req.topic,
            llm_service.topic_prompt_template,
            req.language,
            req.length,
        )

        # Clean up LLM output: strip markdown formatting, headers, etc.
        import re as _re
        clean = content
        clean = _re.sub(r'#{1,6}\s*.*?\n', '', clean)          # remove ### headers
        clean = _re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', clean) # remove **bold** / *italic*
        clean = _re.sub(r'[-–—]\s*', '', clean)                 # remove list bullets
        clean = _re.sub(r'\n{2,}', '\n', clean)                 # collapse blank lines
        clean = _re.sub(r'[（(].*?字.*?[）)]', '', clean)       # remove "(约XXX字)" notes
        clean = clean.strip()
        content = clean

        # Generate keywords
        keywords = llm_service.generate_content(
            content,
            prompt_template=llm_service.keyword_prompt_template,
        )

        return GenerateScriptResponse(content=content.strip(), keywords=keywords.strip())

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
            for idx, r in enumerate(results, 1):
                start, end = _get_time(
                    r,
                    ['begin_time', 'start', 'offset'],
                    ['end_time', 'end']
                )
                text_val = getattr(r, 'text', '') or getattr(r, 'result', '') or ''
                text_val = text_val.strip()
                if text_val:
                    f.write(f"{idx}\n")
                    f.write(f"{_format_srt_time(start)} --> {_format_srt_time(end)}\n")
                    f.write(f"{text_val}\n\n")

        print(f"SRT written: {output_file} ({len(results)} segments)")

        return GenerateSubtitleResponse(subtitle_file=os.path.abspath(output_file))

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

        total_collected_duration = 0.0
        for i, scene in enumerate(req.scenes):
            if not os.path.isdir(scene.media_dir):
                raise HTTPException(status_code=400, detail=f"Scene media_dir not found: {scene.media_dir}")

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


# ========================== ENTRY POINT ==========================

if __name__ == "__main__":
    uvicorn.run(
        "app.worker:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
