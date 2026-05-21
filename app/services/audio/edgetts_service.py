"""
Edge-TTS audio service -- free Microsoft TTS via edge_tts library.
No API key required. Supports all Azure Neural voices.
"""

import asyncio
import edge_tts
from services.audio.audio_service import AudioService


class EdgeTTSAudioService(AudioService):
    def __init__(self):
        super().__init__()

    def save_with_ssml(self, text, file_name, voice="zh-CN-XiaoxiaoNeural", rate="0"):
        rate_str = self._format_rate(rate)
        asyncio.run(self._generate(text, file_name, voice, rate_str))

    def read_with_ssml(self, text, voice="zh-CN-XiaoxiaoNeural", rate="0"):
        pass

    async def _generate(self, text, file_name, voice, rate_str):
        communicate = edge_tts.Communicate(text, voice, rate=rate_str)
        await communicate.save(file_name)

    @staticmethod
    def _format_rate(rate):
        try:
            val = float(rate)
            if val == 0:
                return "+0%"
            sign = "+" if val > 0 else ""
            return f"{sign}{int(val * 100)}%"
        except (ValueError, TypeError):
            return "+0%"
