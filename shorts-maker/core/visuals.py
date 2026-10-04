"""장면에 어울리는 무료 배경 영상 찾기 (Pexels, 무료 키 필요)."""
import requests

API = "https://api.pexels.com/videos/search"


def find_video(keyword, out_path, settings, used=None):
    """키워드로 세로 영상을 찾아 내려받는다. 못 찾으면 None."""
    key = settings.get("pexels_key", "").strip()
    if not key or not keyword:
        return None
    used = used if used is not None else set()
    try:
        res = requests.get(
            API,
            headers={"Authorization": key},
            params={"query": keyword, "orientation": "portrait", "per_page": 10},
            timeout=20,
        )
        res.raise_for_status()
        videos = res.json().get("videos", [])
    except (requests.RequestException, ValueError):
        return None
    for video in videos:
        if video["id"] in used:
            continue
        files = [f for f in video.get("video_files", [])
                 if f.get("height") and f.get("width") and f["height"] >= f["width"]]
        if not files:
            continue
        # 1080p 근처에서 가장 작은 파일 (너무 큰 4K는 피함)
        files.sort(key=lambda f: (abs(f["height"] - 1920), f["height"]))
        try:
            data = requests.get(files[0]["link"], timeout=120)
            data.raise_for_status()
        except requests.RequestException:
            continue
        with open(out_path, "wb") as f:
            f.write(data.content)
        used.add(video["id"])
        return out_path
    return None


def has_key(settings):
    return bool(settings.get("pexels_key", "").strip())

