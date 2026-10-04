"""FFmpeg로 영상 자르기, 합치기, 자막 붙이기."""
import os
import re
import subprocess
import sys

W, H, FPS = 1080, 1920, 30
ENCODE = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
          "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2"]
BG_COLORS = ["0x1e2533", "0x2b1f3a", "0x13324a", "0x3a2420", "0x1f3a2b"]


def ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return "ffmpeg"


def run(args):
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.run([ffmpeg(), "-hide_banner", "-y", *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", creationflags=flags)
    if proc.returncode != 0:
        raise RuntimeError("영상 처리 중 오류가 났어요:\n" + proc.stderr[-1500:])
    return proc


def duration(path):
    """영상/소리 파일 길이(초)."""
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.run([ffmpeg(), "-hide_banner", "-i", path], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", creationflags=flags)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if not m:
        raise RuntimeError(f"파일 길이를 알 수 없어요: {path}")
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)


def _fill_frame(label_in, label_out):
    """어떤 비율의 영상이든 세로 화면(1080x1920)에 꽉 채우기."""
    return (f"[{label_in}]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1,fps={FPS}[{label_out}]")


def make_scene(audio, caption_png, out, background=None, title_png=None, index=0):
    """장면 하나: 배경 + 자막 + 목소리. 길이는 목소리에 맞춘다."""
    dur = duration(audio) + 0.25
    if background:
        inputs = ["-stream_loop", "-1", "-i", background]
    else:
        color = BG_COLORS[index % len(BG_COLORS)]
        inputs = ["-f", "lavfi", "-i", f"color=c={color}:s={W}x{H}:r={FPS}"]
    inputs += ["-i", audio, "-i", caption_png]
    filters = [_fill_frame("0:v", "bg"),
               "[bg]eq=brightness=-0.06[dim]",
               "[dim][2:v]overlay=(W-w)/2:H*0.62[v1]"]
    last = "v1"
    if title_png:
        inputs += ["-i", title_png]
        filters.append("[v1][3:v]overlay=(W-w)/2:H*0.09[v2]")
        last = "v2"
    run([*inputs, "-filter_complex", ";".join(filters),
         "-map", f"[{last}]", "-map", "1:a", "-t", f"{dur:.2f}", *ENCODE, out])
    return out


def concat(parts, out, bgm=None, work_dir=None):
    """장면들을 이어 붙이고, 배경음악이 있으면 작게 깐다."""
    list_file = os.path.join(work_dir or os.path.dirname(out), "concat.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for p in parts:
            f.write("file '" + os.path.abspath(p).replace("\\", "/").replace("'", "'\\''") + "'\n")
    if not bgm:
        run(["-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", out])
        return out
    joined = os.path.join(os.path.dirname(list_file), "joined.mp4")
    run(["-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", joined])
    run(["-i", joined, "-stream_loop", "-1", "-i", bgm, "-filter_complex",
         "[1:a]volume=0.12[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", out])
    return out


def cut_vertical(src, start, end, captions, out, title_png=None):
    """긴 영상의 start~end 구간을 세로로 잘라 자막을 붙인다.

    captions: [(시작초, 끝초, png경로)], 시간은 잘라낸 구간 기준(0부터).
    """
    inputs = ["-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", src]
    filters = [_fill_frame("0:v", "v0")]
    last = "v0"
    idx = 1
    if title_png:
        inputs += ["-i", title_png]
        filters.append(f"[{last}][{idx}:v]overlay=(W-w)/2:H*0.09[t]")
        last, idx = "t", idx + 1
    for i, (t0, t1, png) in enumerate(captions):
        inputs += ["-i", png]
        filters.append(f"[{last}][{idx}:v]overlay=(W-w)/2:H*0.66:"
                       f"enable='between(t,{t0:.2f},{t1:.2f})'[c{i}]")
        last, idx = f"c{i}", idx + 1
    run([*inputs, "-filter_complex", ";".join(filters),
         "-map", f"[{last}]", "-map", "0:a?", *ENCODE, out])
    return out
