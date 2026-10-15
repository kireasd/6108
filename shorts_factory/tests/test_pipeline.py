"""FFmpeg 실제 렌더 + AI 각색 경로(모의 Claude 응답) 통합 테스트."""
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ai  # noqa: E402
import config  # noqa: E402
import pipeline  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg 필요")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setattr(pipeline, "OUTPUT_DIR", str(tmp_path / "out"))
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:d=4:r=30",
                    "-f", "lavfi", "-i", "sine=f=440:d=4", "-shortest", str(src)], check=True)
    srt = tmp_path / "work" / "j1"
    srt.mkdir(parents=True)
    (srt / "source.en.srt").write_text("1\n00:00:00,500 --> 00:00:02,000\nHello world\n\n"
                                       "2\n00:00:02,000 --> 00:00:03,500\nLook at this\n", encoding="utf-8")
    return tmp_path, src


@pytest.mark.parametrize("layout", ["black", "white", "blur"])
def test_ai_plan_render(env, monkeypatch, layout):
    tmp_path, src = env
    seen = {}

    def fake_plan(api_key, model, tone, title, desc, segments, translate=True):
        seen["segments"] = [s.text for s in segments]
        return ai.ShortsPlan(title_line1="해외에서 난리난", title_line2="충격 실험", highlight_word="충격",
                             subtitles=[ai.SubLine(i=0, text="안녕 세상아"), ai.SubLine(i=1, text="이것 좀 봐")],
                             upload_title="충격 실험", description="설명", hashtags=["실험", "#해외"])

    monkeypatch.setattr(ai, "make_plan", fake_plan)
    settings = {**config.DEFAULT_SETTINGS, "anthropic_api_key": "test"}
    channel = {**config.DEFAULT_CHANNEL, "layout": layout, "name": "테스트"}
    res = pipeline.run_job({"id": "j1", "file": str(src)}, settings, channel, log=lambda m: None)

    assert seen["segments"] == ["Hello world", "Look at this"]
    assert res["title"] == ["해외에서 난리난", "충격 실험"]
    meta = pipeline.probe(res["output"])
    assert (meta["w"], meta["h"]) == (1080, 1920)
    assert meta["has_audio"]
    assert abs(meta["duration"] - 4 / 1.05) < 0.2
    txt = open(res["output"][:-4] + ".txt", encoding="utf-8").read()
    assert "#실험 #해외 #shorts" in txt
