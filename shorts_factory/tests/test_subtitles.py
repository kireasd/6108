import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import subtitles as subs  # noqa: E402


def test_vtt_rolling_autosub_dedup():
    raw = """WEBVTT

00:00:00.000 --> 00:00:02.000
hello there

00:00:02.000 --> 00:00:04.000
hello there
<00:00:02.500><c>general</c> kenobi

00:00:04.000 --> 00:00:05.000
general kenobi
"""
    segs = subs.parse_vtt_or_srt(raw)
    assert [s.text for s in segs] == ["hello there", "general kenobi"]
    assert segs[1].end == 5.0


def test_srt():
    raw = "1\n00:00:01,000 --> 00:00:02,500\n안녕하세요\n\n2\n00:00:03,000 --> 00:00:04,000\n반가워요\n"
    segs = subs.parse_vtt_or_srt(raw)
    assert [(s.start, s.end, s.text) for s in segs] == [(1.0, 2.5, "안녕하세요"), (3.0, 4.0, "반가워요")]


def test_json3():
    raw = json.dumps({"events": [
        {"tStartMs": 0, "dDurationMs": 3000, "segs": [{"utf8": "a "}, {"utf8": "b"}]},
        {"tStartMs": 2000, "dDurationMs": 1000, "segs": [{"utf8": "c"}]},
        {"tStartMs": 5000, "dDurationMs": 1000},
    ]})
    segs = subs.parse_json3(raw)
    assert [s.text for s in segs] == ["a b", "c"]
    assert segs[0].end == 2.0  # 겹침 정리


def test_retime_speed_and_limit():
    segs = [subs.Segment(10, 12, "x"), subs.Segment(20, 30, "y"), subs.Segment(80, 90, "z")]
    out = subs.retime(segs, offset=10, speed=2.0, max_duration=10)
    assert [(s.start, s.end) for s in out] == [(0, 1), (5, 10)]


def test_ass_highlight_and_escape():
    ass = subs.build_ass("Font", "black", ["해외 {충격} 실험", "결과"], "충격", [subs.Segment(0, 1, "a{b}")], 5)
    assert "\\c&H0000D4FF&" in ass  # #FFD400 -> BGR
    assert "{b}" not in ass
    assert "Dialogue" in ass


def test_wrap_korean():
    assert subs.wrap_korean("짧은 자막") == ["짧은 자막"]
    lines = subs.wrap_korean("이건 진짜 말도 안 되는 장면이라서 꼭 보셔야 합니다 여러분")
    assert len(lines) == 2
