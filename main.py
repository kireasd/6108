import eel
import os
import json
import sys
import requests
import re

def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# 데이터 경로는 실행 파일 옆
if getattr(sys, 'frozen', False):
    EXE_DIR = os.path.dirname(sys.executable)
else:
    EXE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(EXE_DIR, "data.json")

# 웹 리소스 초기화 - 절대 경로로 고정
web_root = get_resource_path("web")
eel.init(web_root)

@eel.expose
def get_youtube_info(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        res = requests.get(url, headers=headers)
        html = res.text
        name = re.search(r'\"name\":\"(.*?)\"', html).group(1)
        sub = re.search(r'\"subscriberCountText\":\{\"simpleText\":\"(.*?)\"\}', html).group(1)
        avatar = re.search(r'\"avatar\":\{\"thumbnails\":\[\{\"url\":\"(.*?)\"', html).group(1)
        return {"success": True, "name": name, "subscribers": sub, "avatar": avatar, "platform": "YouTube"}
    except: return {"success": False}

@eel.expose
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {"folders": [], "channels": []}
    return {"folders": [], "channels": []}

@eel.expose
def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    return True

# 포트 자동 할당 및 경로 명시
eel.start("index.html", size=(1200, 850), port=0)
