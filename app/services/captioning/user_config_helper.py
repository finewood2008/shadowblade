#
# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE.md file in the project root for full license information.
#

from datetime import timedelta
from enum import Enum
from os import linesep, environ
from sys import argv
from typing import List, Optional
import azure.cognitiveservices.speech as speechsdk  # type: ignore
from config.config import my_config

from services.captioning import helper
from tools.utils import must_have_value

key = my_config['audio']['Azure']['speech_key']
region = my_config['audio']['Azure']['service_region']

# must_have_value(key, "请设置Azure speech_key")
# must_have_value(region, "请设置Azure service_region")


class CaptioningMode(Enum):
    OFFLINE = 1
    REALTIME = 2


def get_language(language=None) -> str:
    if language is not None:
        return language
    return "zh-CN"


def get_phrases(phrases=None) -> List[str]:
    if phrases is not None:
        return list(map(lambda phrase: phrase.strip(), phrases.split(';')))
    return []


def get_compressed_audio_format(captioning_format=None) -> speechsdk.AudioStreamContainerFormat:
    if captioning_format is None:
        return speechsdk.AudioStreamContainerFormat.ANY
    else:
        value = captioning_format.lower()
        if "alaw" == value:
            return speechsdk.AudioStreamContainerFormat.ALAW
        elif "flac" == value:
            return speechsdk.AudioStreamContainerFormat.FLAC
        elif "mp3" == value:
            return speechsdk.AudioStreamContainerFormat.MP3
        elif "mulaw" == value:
            return speechsdk.AudioStreamContainerFormat.MULAW
        elif "ogg_opus" == value:
            return speechsdk.AudioStreamContainerFormat.OGG_OPUS
        else:
            return speechsdk.AudioStreamContainerFormat.ANY


def get_profanity_option(captioning_profanity=None) -> speechsdk.ProfanityOption:
    if captioning_profanity is None:
        return speechsdk.ProfanityOption.Masked
    else:
        value = captioning_profanity.lower()
        if "raw" == value:
            return speechsdk.ProfanityOption.Raw
        elif "remove" == value:
            return speechsdk.ProfanityOption.Removed
        else:
            return speechsdk.ProfanityOption.Masked


def user_config_from_args(captioning_mode=None, audio_language=None,
                          audio_output_file=None, captioning_output=None,
                          captioning_format=None, captioning_profanity=None,
                          captioning_phrases=None, captioning_quiet=None,
                          captioning_remainTime=None, captioning_delay=None,
                          captioning_maxLineLength=None, captioning_lines=None,
                          captioning_threshold=None) -> helper.Read_Only_Dict:
    if captioning_mode == "realtime":
        mode = CaptioningMode.REALTIME
    else:
        mode = CaptioningMode.OFFLINE

    td_remain_time = timedelta(milliseconds=1000)
    if captioning_remainTime is not None:
        int_remain_time = float(captioning_remainTime)
        if int_remain_time < 0:
            int_remain_time = 1000
        td_remain_time = timedelta(milliseconds=int_remain_time)

    td_delay = timedelta(milliseconds=1000)
    if captioning_delay is not None:
        int_delay = float(captioning_delay)
        if int_delay < 0:
            int_delay = 1000
        td_delay = timedelta(milliseconds=int_delay)

    int_max_line_length = helper.DEFAULT_MAX_LINE_LENGTH_SBCS
    if captioning_maxLineLength is not None:
        int_max_line_length = int(captioning_maxLineLength)
        if int_max_line_length < 20:
            int_max_line_length = 20

    int_lines = 2
    if captioning_lines is not None:
        int_lines = int(captioning_lines)
        if int_lines < 1:
            int_lines = 2

    return helper.Read_Only_Dict({
        "use_compressed_audio": captioning_format,
        "compressed_audio_format": get_compressed_audio_format(captioning_format),
        "profanity_option": get_profanity_option(captioning_profanity),
        "language": get_language(audio_language),
        "input_file": audio_output_file,
        "output_file": captioning_output,
        "phrases": get_phrases(captioning_phrases),
        "suppress_console_output": captioning_quiet,
        "captioning_mode": mode,
        "remain_time": td_remain_time,
        "delay": td_delay,
        "use_sub_rip_text_caption_format": True,
        "max_line_length": int_max_line_length,
        "lines": int_lines,
        "stable_partial_result_threshold": captioning_threshold,
        "subscription_key": key,
        "region": region,
    })
