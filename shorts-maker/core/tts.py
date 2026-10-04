"""AI 목소리로 문장 읽기 (Microsoft Edge 무료 음성, 인터넷 필요)."""
import asyncio

import edge_tts

VOICES = {
    "선희 (여자, 밝음)": "ko-KR-SunHiNeural",
    "인준 (남자, 차분)": "ko-KR-InJoonNeural",
    "현수 (남자, 다양한 톤)": "ko-KR-HyunsuMultilingualNeural",
}


async def _speak(text, voice, rate, out_path):
    await edge_tts.Communicate(text, voice, rate=rate).save(out_path)


def speak(text, out_path, settings):
    asyncio.run(_speak(text, settings["voice"], settings["voice_rate"], out_path))
    return out_path
