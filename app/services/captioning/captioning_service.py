#  Copyright © [2024] 程序那些事
#
#  All rights reserved. This software and associated documentation files (the "Software") are provided for personal and educational use only. Commercial use of the Software is strictly prohibited unless explicit permission is obtained from the author.
#
#  Permission is hereby granted to any person to use, copy, and modify the Software for non-commercial purposes, provided that the following conditions are met:
#
#  1. The original copyright notice and this permission notice must be included in all copies or substantial portions of the Software.
#  2. Modifications, if any, must retain the original copyright information and must not imply that the modified version is an official version of the Software.
#  3. Any distribution of the Software or its modifications must retain the original copyright notice and include this permission notice.
#
#  For commercial use, including but not limited to selling, distributing, or using the Software as part of any commercial product or service, you must obtain explicit authorization from the author.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHOR OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
#  Author: 程序那些事
#  email: flydean@163.com
#  Website: [www.flydean.com](http://www.flydean.com)
#  GitHub: [https://github.com/ddean2009/MoneyPrinterPlus](https://github.com/ddean2009/MoneyPrinterPlus)
#
#  All rights reserved.
#
#

import json
import os
import platform
import shlex
from typing import Optional

from config.config import my_config
from services.alinls.speech_process import AliRecognitionService
from services.audio.faster_whisper_recognition_service import FasterWhisperRecognitionService
from services.audio.sensevoice_whisper_recognition_service import SenseVoiceRecognitionService
from services.audio.tencent_recognition_service import TencentRecognitionService
from services.captioning.common_captioning_service import Captioning
import subprocess

from tools.file_utils import generate_temp_filename

# 获取当前脚本的绝对路径
script_path = os.path.abspath(__file__)

# print("当前脚本的绝对路径是:", script_path)

# 脚本所在的目录
script_dir = os.path.dirname(script_path)


def _resolve_font_dir():
    """
    依次向上查找一个真实存在的 fonts/ 目录：
      1. app/services/captioning/../fonts        （旧 fork 习惯）
      2. app/services/captioning/../../fonts     （app/ 同级）
      3. app/services/captioning/../../../fonts  （仓库根，shadowblade 仓库的位置）

    全找不到就返回 None，调用方应当不传 fontsdir，让 libass 走系统字体回退
    （Windows 上 'Microsoft YaHei' 通常都装着）。
    """
    candidates = [
        os.path.normpath(os.path.join(script_dir, p))
        for p in ("../fonts", "../../fonts", "../../../fonts")
    ]
    for cand in candidates:
        if os.path.isdir(cand):
            try:
                if any(f.lower().endswith((".ttc", ".ttf", ".otf"))
                       for f in os.listdir(cand)):
                    return cand
            except OSError:
                pass
    return None


_resolved_font_dir = _resolve_font_dir()
font_dir = _resolved_font_dir or ""

# windows路径需要特殊处理
if font_dir and platform.system() == "Windows":
    font_dir = font_dir.replace("\\", "\\\\\\\\")
    font_dir = font_dir.replace(":", "\\\\:")


def _ffmpeg_has_filter(filter_name):
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False
    return any(
        line.split()[1:2] == [filter_name]
        for line in (result.stdout or "").splitlines()
    )


def _replace_video_file(output_file, video_file):
    if os.path.exists(output_file):
        os.remove(video_file)
        os.renames(output_file, video_file)


def _embed_subtitle_track(video_file, subtitle_file, output_file):
    ffmpeg_cmd = [
        'ffmpeg',
        '-i', video_file,
        '-i', subtitle_file,
        '-map', '0:v:0',
        '-map', '0:a?',
        '-map', '1:0',
        '-c:v', 'copy',
        '-c:a', 'copy',
        '-c:s', 'mov_text',
        '-metadata:s:s:0', 'language=chi',
        '-y',
        output_file,
    ]
    print(" ".join(shlex.quote(item) for item in ffmpeg_cmd))
    subprocess.run(ffmpeg_cmd, check=True)
    _replace_video_file(output_file, video_file)


# 生成字幕
def generate_caption(recognition_type="local", audio_output_file=None,
                     audio_language="zh-CN", audio_provider=None):
    captioning = Captioning()
    captioning.initialize()
    speech_recognizer_data = captioning.speech_recognizer_from_user_config()
    if recognition_type == "remote":
        selected_audio_provider = audio_provider or my_config['audio']['provider']
        if selected_audio_provider == 'Azure':
            print("selected_audio_provider: Azure")
            captioning.recognize_continuous(speech_recognizer=speech_recognizer_data["speech_recognizer"],
                                            format=speech_recognizer_data["audio_stream_format"],
                                            callback=speech_recognizer_data["pull_input_audio_stream_callback"],
                                            stream=speech_recognizer_data["pull_input_audio_stream"])
        if selected_audio_provider == 'Ali':
            print("selected_audio_provider: Ali")
            ali_service = AliRecognitionService()
            result_list = ali_service.process(audio_output_file)
            captioning._offline_results = result_list
        if selected_audio_provider == 'Tencent':
            print("selected_audio_provider: Tencent")
            tencent_service = TencentRecognitionService()
            result_list = tencent_service.process(audio_output_file, audio_language)
            if result_list is None:
                return
            captioning._offline_results = result_list
    if recognition_type == "local":
        selected_audio_provider = audio_provider or my_config['audio'].get('local_recognition',{}).get('provider')
        if selected_audio_provider =='fasterwhisper':
            print("selected_audio_provider: fasterwhisper")
            fasterwhisper_service = FasterWhisperRecognitionService()
            result_list = fasterwhisper_service.process(audio_output_file, audio_language)
            print(result_list)
            if result_list is None:
                return
            captioning._offline_results = result_list

        if selected_audio_provider =='sensevoice':
            print("selected_audio_provider: sensevoice")
            fasterwhisper_service = SenseVoiceRecognitionService()
            result_list = fasterwhisper_service.process(audio_output_file, audio_language)
            print(result_list)
            if result_list is None:
                return
            captioning._offline_results = result_list

    captioning.finish()


# 添加字幕
def add_subtitles(video_file, subtitle_file, font_name='Songti TC Bold', font_size=12, primary_colour='#FFFFFF',
                  outline_colour='#FFFFFF', margin_v=16, margin_l=4, margin_r=4, border_style=1, outline=0, alignment=2,
                  shadow=0, spacing=2):
    # 防御性检查：SRT 不存在 / 是空文件 / 只有空白 → 不烧字幕，原视频不变
    if not subtitle_file or not os.path.isfile(subtitle_file):
        print(f"WARNING: add_subtitles: SRT not found at {subtitle_file}, skipping")
        return
    try:
        with open(subtitle_file, 'r', encoding='utf-8') as _sf:
            srt_text = _sf.read().strip()
        if not srt_text:
            print(f"WARNING: add_subtitles: SRT is empty at {subtitle_file}, skipping")
            return
    except Exception as e:
        print(f"WARNING: add_subtitles: cannot read SRT {subtitle_file}: {e}, skipping")
        return

    output_file = generate_temp_filename(video_file)
    if not _ffmpeg_has_filter("subtitles"):
        print("WARNING: ffmpeg subtitles filter is unavailable; embedding MP4 subtitle track instead.")
        _embed_subtitle_track(video_file, subtitle_file, output_file)
        return

    # 添加透明度通道（AA），默认00表示不透明，并确保颜色值为6位
    # 将HEX颜色转换为BGRA格式（AARRGGBB -> BBGGRRAA）
    def hex_to_bgra(hex_color):
        hex_color = hex_color.lstrip('#')
        alpha = hex_color[6:8] if len(hex_color) >= 8 else '00'
        rgb = hex_color[:6].ljust(6, '0')
        bgr = rgb[4:6] + rgb[2:4] + rgb[0:2]  # RRGGBB -> BBGGRR
        return f"&H{alpha}{bgr}&"

    primary_colour = hex_to_bgra(primary_colour)
    outline_colour = hex_to_bgra(outline_colour)
    # windows路径需要特殊处理
    sub_path = subtitle_file
    if platform.system() == "Windows":
        sub_path = sub_path.replace("\\", "\\\\\\\\")
        sub_path = sub_path.replace(":", "\\\\:")

    # fontsdir 只在仓库里真的能找到 fonts/ 时才传；否则 libass 走系统字体回退
    fontsdir_clause = f":fontsdir='{font_dir}'" if font_dir else ""
    vf_text = (
        f"subtitles=filename='{sub_path}'{fontsdir_clause}"
        f":force_style='Fontname={font_name},Fontsize={font_size},"
        f"Alignment={alignment},MarginV={margin_v},MarginL={margin_l},"
        f"MarginR={margin_r},BorderStyle={border_style},Outline={outline},"
        f"Shadow={shadow},PrimaryColour={primary_colour},"
        f"OutlineColour={outline_colour},Spacing={spacing}'"
    )
    # 构建FFmpeg命令
    ffmpeg_cmd = [
        'ffmpeg',
        '-i', video_file,  # 输入视频文件
        '-vf', vf_text,  # 输入字幕文件
        '-y',
        output_file  # 输出文件
    ]
    print(" ".join(shlex.quote(item) for item in ffmpeg_cmd))
    # 调用ffmpeg；失败时把 stderr 一起抛出来，方便上层定位
    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or "")[-2000:]
        raise RuntimeError(
            f"ffmpeg subtitles burn-in failed (rc={result.returncode}). "
            f"stderr tail:\n{tail}"
        )
    if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        raise RuntimeError("ffmpeg subtitles burn-in produced no output file")
    # 重命名最终的文件
    _replace_video_file(output_file, video_file)
