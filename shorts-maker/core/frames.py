"""영상에서 장면 뽑기와 장면끼리 얼마나 닮았는지 비교하기."""
import base64
import glob
import os
import re
from io import BytesIO

from PIL import Image, ImageStat

from . import video


def extract(src, out_dir, count=12, width=480):
    """영상 전체에서 고르게 count장 뽑는다. [(초, jpg경로)]"""
    os.makedirs(out_dir, exist_ok=True)
    total = video.duration(src)
    frames = []
    for i in range(count):
        t = total * (i + 0.5) / count
        path = os.path.join(out_dir, f"q_{i:02d}.jpg")
        video.run(["-ss", f"{t:.2f}", "-i", src, "-frames:v", "1",
                   "-vf", f"scale={width}:-2", "-q:v", "3", path])
        if os.path.exists(path):
            frames.append((t, path))
    return frames


def scenes(src, out_dir, max_segments=30, min_len=1.0, width=480):
    """장면이 바뀌는 곳마다 영상을 나눈다.

    [{"index", "start", "end", "time"(대표 장면 시각), "frame"(jpg경로)}]
    모음 영상이면 장면마다 원본이 다를 수 있어서, 장면마다 따로 찾는 데 쓴다.
    """
    os.makedirs(out_dir, exist_ok=True)
    total = video.duration(src)
    proc = video.run(["-i", src, "-vf", "scale=320:-2,select='gt(scene,0.32)',showinfo",
                      "-an", "-f", "null", "-"])
    cuts = [float(t) for t in re.findall(r"pts_time:([\d.]+)", proc.stderr)]
    bounds = [0.0] + [t for t in cuts if 0 < t < total] + [total]
    segs = []
    for a, b in zip(bounds, bounds[1:]):
        if segs and b - a < min_len:  # 너무 짧은 조각은 앞 장면에 붙인다
            segs[-1][1] = b
        else:
            segs.append([a, b])
    if len(segs) > max_segments:  # 롱폼처럼 장면이 많으면 긴 장면 위주로
        segs = sorted(sorted(segs, key=lambda s: s[1] - s[0], reverse=True)[:max_segments])
    result = []
    for i, (a, b) in enumerate(segs):
        t = (a + b) / 2
        path = os.path.join(out_dir, f"scene_{i:02d}.jpg")
        video.run(["-ss", f"{t:.2f}", "-i", src, "-frames:v", "1",
                   "-vf", f"scale={width}:-2", "-q:v", "3", path])
        if os.path.exists(path):
            result.append({"index": len(result), "start": round(a, 2), "end": round(b, 2),
                           "time": t, "frame": path})
    return result


def data_uri(path, width=320):
    """화면에 바로 보여줄 수 있게 작은 jpg 글자로 바꾼다."""
    img = Image.open(path).convert("RGB")
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def sample(src, out_dir, every=2.0, width=240):
    """영상을 every초마다 작게 뽑는다 (원본 후보 정밀 비교용). [(초, jpg경로)]"""
    os.makedirs(out_dir, exist_ok=True)
    video.run(["-i", src, "-vf", f"fps=1/{every},scale={width}:-2", "-q:v", "5",
               os.path.join(out_dir, "s_%05d.jpg")])
    paths = sorted(glob.glob(os.path.join(out_dir, "s_*.jpg")))
    return [(i * every, p) for i, p in enumerate(paths)]


def _dhash(img):
    small = img.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(small.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return bits


def _center(img, w_ratio, h_ratio):
    w, h = img.size
    cw, ch = int(w * w_ratio), int(h * h_ratio)
    left, top = (w - cw) // 2, (h - ch) // 2
    return img.crop((left, top, left + cw, top + ch))


def _middle(img, top=0.22, bottom=0.78):
    """위아래(제목·자막이 자주 붙는 곳)를 빼고 가운데 띠만."""
    w, h = img.size
    return img.crop((0, int(h * top), w, int(h * bottom)))


def _aspect_crop(img, aspect):
    """가운데를 aspect(가로/세로) 비율로 자른다."""
    w, h = img.size
    if w / h > aspect:
        return _center(img, aspect * h / w, 1)
    return _center(img, 1, (w / aspect) / h)


def _is_flat(img):
    """거의 한 색인 화면(검은 화면 등)은 비교에서 뺀다."""
    return ImageStat.Stat(img.convert("L")).stddev[0] < 12


def query_hashes(path):
    """쇼츠(찾고 싶은 영상) 한 장면의 비교용 지문들.

    쇼츠는 원본을 세로로 꽉 채우거나(잘림), 가운데에 가로 영상을 두고 위아래에
    글씨를 넣는 경우가 많아서 여러 가지로 잘라 본다.
    """
    img = Image.open(path)
    if _is_flat(img):
        return []
    variants = [img, _center(img, 0.8, 0.8), _middle(img)]
    w, h = img.size
    if h > w:  # 세로 영상 가운데의 가로 화면 부분
        band = _aspect_crop(img, 16 / 9)
        variants += [band, _center(band, 0.85, 0.85)]
    return [_dhash(v) for v in variants]


def ref_hashes(path):
    """원본 후보 한 장면의 비교용 지문들."""
    img = Image.open(path)
    if _is_flat(img):
        return []
    variants = [img, _center(img, 0.8, 0.8)]
    w, h = img.size
    if w > h:  # 원본을 세로로 꽉 채워 자른 쇼츠에 대비
        tall = _aspect_crop(img, 9 / 16)
        variants += [tall, _center(tall, 0.8, 0.8), _middle(tall)]
    else:
        variants.append(_middle(img))
    return [_dhash(v) for v in variants]


def distance(qh, rh):
    """두 장면 지문의 차이 (0=똑같음, 64=완전 다름)."""
    if not qh or not rh:
        return 64
    return min(bin(a ^ b).count("1") for a in qh for b in rh)
